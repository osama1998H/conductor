"""Chaos-test fixtures: spawn `bench conductor worker` as a subprocess so we
can kill -9 it mid-job and verify reclaim semantics.

Chaos tests need a real Frappe site connection inside the test process to
inspect rows, so each test does its own frappe.init/connect/destroy.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

BENCH_ROOT = Path("/Users/osamamuhammed/frappe_15")
DEFAULT_SITE = "frappe.localhost"


@pytest.fixture(scope="session")
def site():
    return DEFAULT_SITE


@pytest.fixture(scope="session", autouse=True)
def _frappe_init(site):
    """One-time per-session Frappe init for the test process itself.

    Also wipes any leftover Conductor state from prior chaos runs so each
    suite starts on a clean slate (scheduled-set retries, DLQ stream entries,
    and idempotency locks all accumulate otherwise and cross-pollinate tests).
    """
    import os
    os.chdir(str(BENCH_ROOT))
    import frappe
    frappe.init(site=site, sites_path=str(BENCH_ROOT / "sites"))
    frappe.connect()

    # Wipe per-site Conductor Redis keys (queue streams, scheduled set, DLQ
    # streams, idempotency locks). Default queues will be recreated lazily
    # by ensure_consumer_group on first dispatch.
    from conductor.client import get_redis
    from conductor.config import load_config
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    for key in r.keys(f"conductor:{site}:*"):
        r.delete(key)

    # Wipe leftover Conductor Job / Job Run / DLQ Entry rows from prior runs.
    for doctype in ("Conductor DLQ Entry", "Conductor Job Run", "Conductor Job"):
        for name in frappe.get_all(doctype, pluck="name"):
            frappe.delete_doc(doctype, name, force=True)
    frappe.db.commit()

    yield
    frappe.destroy()


@pytest.fixture(autouse=True)
def _wipe_conductor_state_per_test(site):
    """Per-test cleanup: wipe Conductor Redis keys + DocType rows BEFORE each
    chaos test runs. Within a single pytest session, prior tests can leave
    state behind (stream entries from idempotency tests, scheduled-set retries
    from kill tests) that confuses the next test's worker."""
    import frappe
    from conductor.client import get_redis
    from conductor.config import load_config
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    for key in r.keys(f"conductor:{site}:*"):
        r.delete(key)
    for doctype in ("Conductor DLQ Entry", "Conductor Job Run", "Conductor Job"):
        for name in frappe.get_all(doctype, pluck="name"):
            frappe.delete_doc(doctype, name, force=True)
    frappe.db.commit()
    yield


@pytest.fixture
def spawn_worker(site):
    """Spawn `bench --site SITE conductor worker --queue default --concurrency 1`
    as a subprocess. Returns a callable that yields the subprocess.Popen
    handle; the test is responsible for kill/wait."""
    procs: list[subprocess.Popen] = []

    @contextmanager
    def _spawn(*, queue: str = "default", concurrency: int = 1):
        cmd = [
            "bench", "--site", site, "conductor", "worker",
            "--queue", queue, "--concurrency", str(concurrency),
        ]
        env = os.environ.copy()
        # Exec lock expires in 5s (must be < AUTOCLAIM_IDLE_MS/1000) so the
        # peer that reclaims after the lock expires can actually acquire it.
        env.setdefault("CONDUCTOR_TEST_EXEC_LOCK_TTL_SECONDS", "5")
        # Reclaim idle threshold: must exceed EXEC_LOCK_TTL_SECONDS*1000 so
        # that by the time XAUTOCLAIM fires, the dead worker's lock is gone.
        env.setdefault("CONDUCTOR_TEST_AUTOCLAIM_IDLE_MS", "8000")
        proc = subprocess.Popen(
            cmd,
            cwd=str(BENCH_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            env=env,
        )
        procs.append(proc)
        time.sleep(2.0)
        try:
            yield proc
        finally:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=5)
            except Exception:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass  # already dead or in a different session

    yield _spawn

    for p in procs:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass  # already dead or in a different session


def wait_for_status(job_id: str, expected: str, *, timeout: float = 30.0) -> str:
    """Poll the DB until the job reaches `expected` or timeout. Returns the
    last-observed status (whether or not it matched)."""
    import frappe
    end = time.time() + timeout
    last = None
    while time.time() < end:
        frappe.db.rollback()
        last = frappe.db.get_value("Conductor Job", job_id, "status")
        if last == expected:
            return last
        time.sleep(0.2)
    return last or ""
