"""Engine adapters for the Conductor-vs-RQ KPI suite.

Each Engine knows how to:
- spawn a worker subprocess on a dedicated test queue
- enqueue work using its native API
- wait for a job to reach a terminal state
- list permanently failed jobs (for KPI 3 / KPI 4)
- kill its workers

KPIs are written against the abstract Engine interface so they run
against both adapters without engine-specific code.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

BENCH_ROOT = Path("/Users/osamamuhammed/frappe_15")
SITE = "frappe.localhost"
CONDUCTOR_QUEUE = "kpi-conductor"
RQ_QNAME = f"kpi-rq:{SITE}"

TERMINAL_SUCCEEDED = "SUCCEEDED"
TERMINAL_FAILED = "FAILED"
TERMINAL_DLQ = "DLQ"
TERMINAL_LOST = "LOST"
PENDING = "PENDING"  # not yet terminal — used by get_status_nonblocking


@dataclass
class FailedJob:
    job_id: str
    method: str
    error: str
    traceback: str
    attempts: int


class Engine(ABC):
    name: str

    @abstractmethod
    def setup(self) -> None: ...

    @abstractmethod
    def teardown(self) -> None: ...

    @abstractmethod
    def cleanup_state(self) -> None: ...

    @abstractmethod
    def spawn_worker(self) -> int:
        """Return the PID of the spawned worker (its process group leader)."""

    @abstractmethod
    def kill_worker(self, pid: int, sig: int = signal.SIGKILL) -> None: ...

    @abstractmethod
    def enqueue(self, method: str, *, idempotency_key: Optional[str] = None,
                max_attempts: Optional[int] = None, timeout: int = 300, **kwargs) -> str:
        """Enqueue a job. `max_attempts=None` means "use whatever the
        platform's out-of-the-box default is" — the framing for
        any KPI that measures default behavior."""

    @abstractmethod
    def wait_for_terminal(self, job_id: str, timeout: float) -> str:
        """Returns one of TERMINAL_SUCCEEDED/FAILED/DLQ/LOST."""

    @abstractmethod
    def get_status_nonblocking(self, job_id: str) -> str:
        """Single non-blocking status check. Returns SUCCEEDED/FAILED/DLQ/PENDING.
        Never returns LOST — that's reserved for wait_for_terminal's timeout path."""

    @abstractmethod
    def list_failed_jobs(self) -> list[FailedJob]: ...

    @abstractmethod
    def count_attempt_records(self, job_id: str) -> int: ...

    @abstractmethod
    def queryable_via_sql(self) -> bool:
        """True if list_failed_jobs() is backed by a SQL query, not Redis introspection."""


# ---------------------------------------------------------------------------
# Conductor
# ---------------------------------------------------------------------------

class ConductorEngine(Engine):
    name = "conductor"

    def __init__(self, *, concurrency: int = 4):
        self._workers: list[subprocess.Popen] = []
        self._scheduler: Optional[subprocess.Popen] = None
        self._concurrency = concurrency

    def setup(self) -> None:
        import frappe
        # Ensure the queue row exists.
        # Idempotent — create or update so the KPI always runs against
        # the master-design defaults regardless of prior state.
        defaults = {
            "concurrency": self._concurrency,
            "default_max_attempts": 3,
            "default_timeout": 300,
            "default_backoff": "exponential",
            "default_base_delay_seconds": 2,
            "default_max_delay_seconds": 600,
            "default_jitter": "full",
            "enabled": 1,
        }
        if frappe.db.exists("Conductor Queue", CONDUCTOR_QUEUE):
            queue = frappe.get_doc("Conductor Queue", CONDUCTOR_QUEUE)
            for k, v in defaults.items():
                setattr(queue, k, v)
            queue.save(ignore_permissions=True)
        else:
            queue = frappe.new_doc("Conductor Queue")
            queue.queue_name = CONDUCTOR_QUEUE
            for k, v in defaults.items():
                setattr(queue, k, v)
            queue.insert(ignore_permissions=True)
        frappe.db.commit()
        self.cleanup_state()

    def teardown(self) -> None:
        procs = list(self._workers)
        if self._scheduler is not None:
            procs.append(self._scheduler)
        for p in procs:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
        self._workers.clear()
        self._scheduler = None

    def spawn_scheduler(self) -> int:
        """Phase 2+: scheduler owns the delay-drain loop. KPIs that exercise
        retries need this; KPIs that don't can skip it."""
        p = subprocess.Popen(
            ["bench", "--site", SITE, "conductor", "scheduler"],
            cwd=str(BENCH_ROOT),
            preexec_fn=os.setsid,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._scheduler = p
        time.sleep(2.0)
        return p.pid

    def cleanup_state(self) -> None:
        import frappe
        from conductor.client import get_redis
        from conductor.config import load_config
        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)

        prefix = f"conductor:{SITE}:".encode()
        for key in r.scan_iter(match=f"conductor:{SITE}:*"):
            r.delete(key)
        # Workload counters live on the same redis.
        for key in r.scan_iter(match="kpi:*"):
            r.delete(key)

        # DocType rows for the test queue only.
        for doctype in ("Conductor DLQ Entry", "Conductor Job Run", "Conductor Job"):
            rows = frappe.get_all(doctype, filters={"queue": CONDUCTOR_QUEUE} if doctype == "Conductor Job" else {})
            if doctype != "Conductor Job":
                # Job Run / DLQ Entry are filtered by linked job — easier:
                # delete everything from the test queue's job lineage.
                rows = frappe.get_all(doctype)
            for n in rows:
                try:
                    frappe.delete_doc(doctype, n.name, force=True, delete_permanently=True)
                except Exception:
                    pass
        frappe.db.commit()

    def spawn_worker(self) -> int:
        env = {
            **os.environ,
            "CONDUCTOR_TEST_AUTOCLAIM_IDLE_MS": "8000",
            "CONDUCTOR_TEST_EXEC_LOCK_TTL_SECONDS": "5",
        }
        p = subprocess.Popen(
            ["bench", "--site", SITE, "conductor", "worker",
             "--queue", CONDUCTOR_QUEUE,
             "--concurrency", str(self._concurrency),
             "--grace", "5"],
            cwd=str(BENCH_ROOT),
            preexec_fn=os.setsid,
            env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._workers.append(p)
        # Brief warmup: let the worker register and join the consumer group.
        time.sleep(2.0)
        return p.pid

    def kill_worker(self, pid: int, sig: int = signal.SIGKILL) -> None:
        try:
            os.killpg(os.getpgid(pid), sig)
        except ProcessLookupError:
            pass

    def enqueue(self, method: str, *, idempotency_key: Optional[str] = None,
                max_attempts: Optional[int] = None, timeout: int = 300, **kwargs) -> str:
        import conductor
        # `max_attempts=None` → omit the kwarg so the queue default applies.
        extra = {} if max_attempts is None else {"max_attempts": max_attempts}
        return conductor.enqueue(
            method,
            queue=CONDUCTOR_QUEUE,
            timeout=timeout,
            idempotency_key=idempotency_key,
            **extra,
            **kwargs,
        )

    def wait_for_terminal(self, job_id: str, timeout: float) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self.get_status_nonblocking(job_id)
            if status != PENDING:
                return status
            time.sleep(0.5)
        return TERMINAL_LOST

    def get_status_nonblocking(self, job_id: str) -> str:
        import frappe
        # Force a fresh read by ending the current read snapshot.
        frappe.db.commit()
        status = frappe.db.get_value("Conductor Job", job_id, "status")
        if status == "SUCCEEDED":
            return TERMINAL_SUCCEEDED
        if status == "FAILED":
            return TERMINAL_FAILED
        if status == "DLQ":
            return TERMINAL_DLQ
        return PENDING

    def list_failed_jobs(self) -> list[FailedJob]:
        import frappe
        rows = frappe.db.sql(
            """
            SELECT j.name, j.method, j.last_error_message, j.last_traceback, j.attempt
            FROM `tabConductor Job` j
            WHERE j.queue = %s
              AND j.status = 'DLQ'
            """,
            (CONDUCTOR_QUEUE,),
            as_dict=True,
        )
        return [
            FailedJob(
                job_id=r["name"],
                method=r["method"],
                error=r.get("last_error_message") or "",
                traceback=r.get("last_traceback") or "",
                attempts=r.get("attempt") or 0,
            )
            for r in rows
        ]

    def count_attempt_records(self, job_id: str) -> int:
        import frappe
        return int(frappe.db.count("Conductor Job Run", filters={"job": job_id}))

    def queryable_via_sql(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Frappe RQ
# ---------------------------------------------------------------------------

class RQEngine(Engine):
    name = "rq"

    def __init__(self):
        self._workers: list[subprocess.Popen] = []
        self._connection = None
        self._queue = None

    def _conn(self):
        if self._connection is None:
            from frappe.utils.background_jobs import get_redis_conn
            self._connection = get_redis_conn()
        return self._connection

    def _q(self):
        if self._queue is None:
            from rq import Queue
            self._queue = Queue(RQ_QNAME, connection=self._conn())
        return self._queue

    def setup(self) -> None:
        # Force connection establishment + queue registration.
        self._q()
        self.cleanup_state()

    def teardown(self) -> None:
        for p in self._workers:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
        for p in self._workers:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
        self._workers.clear()

    def cleanup_state(self) -> None:
        r = self._conn()
        # Test queue artifacts.
        for key in r.scan_iter(match=f"rq:queue:{RQ_QNAME}*"):
            r.delete(key)
        for key in r.scan_iter(match=f"rq:queues"):
            r.srem(key, f"rq:queue:{RQ_QNAME}")
        # Failed registry for the test queue.
        for key in r.scan_iter(match=f"rq:failed:{RQ_QNAME}"):
            r.delete(key)
        for key in r.scan_iter(match=f"rq:wip:{RQ_QNAME}"):
            r.delete(key)
        for key in r.scan_iter(match=f"rq:finished:{RQ_QNAME}"):
            r.delete(key)
        for key in r.scan_iter(match=f"rq:scheduled:{RQ_QNAME}"):
            r.delete(key)
        # Workload counters (shared with Conductor's).
        for key in r.scan_iter(match="kpi:*"):
            r.delete(key)

    def spawn_worker(self) -> int:
        # Use the bench's Python so frappe imports correctly.
        bench_python = str(BENCH_ROOT / "env" / "bin" / "python")
        # Apps directory must be on PYTHONPATH so the launcher module resolves.
        # The launcher is under apps/conductor/tests/comparative/_rq_worker_launcher.py
        env = {
            **os.environ,
            "PYTHONPATH": f"{BENCH_ROOT}/apps/conductor:{os.environ.get('PYTHONPATH','')}",
        }
        p = subprocess.Popen(
            [bench_python, "-m", "tests.comparative._rq_worker_launcher", RQ_QNAME, SITE],
            cwd=str(BENCH_ROOT / "sites"),
            preexec_fn=os.setsid,
            env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._workers.append(p)
        time.sleep(3.0)  # rq worker boot is slower than conductor's
        return p.pid

    def kill_worker(self, pid: int, sig: int = signal.SIGKILL) -> None:
        try:
            os.killpg(os.getpgid(pid), sig)
        except ProcessLookupError:
            pass

    def enqueue(self, method: str, *, idempotency_key: Optional[str] = None,
                max_attempts: Optional[int] = None, timeout: int = 300, **kwargs) -> str:
        # RQ has no `idempotency_key` parameter and no content-based dedupe.
        # We deliberately IGNORE `idempotency_key` here so the KPI suite
        # measures RQ's out-of-the-box behavior on a business key — the user
        # would have to translate the key to `job_id` themselves and accept
        # the registry-eviction window. RQ's `job_id` dedupe is acknowledged
        # in the KPI plan §3 KPI 4 caveat.
        # RQ's out-of-the-box default is 1 attempt (no retry); only attach
        # rq.Retry when the caller explicitly opts in via max_attempts.
        from frappe.utils.background_jobs import execute_job
        from rq import Retry
        job_id = str(uuid.uuid4())
        retry = Retry(max=max_attempts) if (max_attempts and max_attempts > 1) else None
        queue_args = {
            "site": SITE,
            "user": "Administrator",
            "method": method,
            "event": None,
            "job_name": method,
            "is_async": True,
            "kwargs": kwargs,
        }
        job = self._q().enqueue_call(
            execute_job,
            kwargs=queue_args,
            timeout=timeout,
            job_id=job_id,
            retry=retry,
        )
        return job.id

    def wait_for_terminal(self, job_id: str, timeout: float) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self.get_status_nonblocking(job_id)
            if status != PENDING:
                return status
            time.sleep(0.5)
        return TERMINAL_LOST

    def get_status_nonblocking(self, job_id: str) -> str:
        from rq.job import Job, JobStatus
        try:
            job = Job.fetch(job_id, connection=self._conn())
        except Exception:
            return PENDING
        status = job.get_status(refresh=True)
        if status == JobStatus.FINISHED:
            return TERMINAL_SUCCEEDED
        if status == JobStatus.FAILED:
            return TERMINAL_FAILED
        return PENDING

    def list_failed_jobs(self) -> list[FailedJob]:
        from rq.job import Job
        from rq.registry import FailedJobRegistry
        reg = FailedJobRegistry(name=RQ_QNAME, connection=self._conn())
        out: list[FailedJob] = []
        for jid in reg.get_job_ids():
            try:
                j = Job.fetch(jid, connection=self._conn())
            except Exception:
                continue
            out.append(FailedJob(
                job_id=j.id,
                method=str(j.kwargs.get("method") or j.func_name),
                error=str(j.exc_info or "").splitlines()[-1] if j.exc_info else "",
                traceback=str(j.exc_info or ""),
                attempts=getattr(j, "retries_left", None) and 1 or 1,
            ))
        return out

    def count_attempt_records(self, job_id: str) -> int:
        # RQ stores at most one record per job: the last failure's traceback.
        # The job either has exc_info (=> 1) or not (=> 0).
        from rq.job import Job
        try:
            j = Job.fetch(job_id, connection=self._conn())
        except Exception:
            return 0
        return 1 if j.exc_info else 0

    def queryable_via_sql(self) -> bool:
        return False


def make_engine(name: str) -> Engine:
    if name == "conductor":
        return ConductorEngine()
    if name == "rq":
        return RQEngine()
    raise ValueError(f"unknown engine: {name!r}")
