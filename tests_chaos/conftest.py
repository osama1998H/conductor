"""Chaos-test fixtures: spawn `bench conductor worker` and `bench conductor
scheduler` as subprocesses so we can kill -9 them mid-job and verify reclaim
+ retry semantics.

Highlights:
  - autouse `spawn_scheduler` fixture: every chaos test gets a scheduler
    process running by default (the worker no longer drains the scheduled
    set — that lives in the scheduler).
  - per-test teardown: `XGROUP DESTROY` every consumer group on every conductor
    stream key before deletion — scrubs PEL stale message-IDs that survive
    `r.delete(key)`.
  - tight subprocess teardown: poll until the process group is empty before
    moving on, so a slow exit cannot leak state into the next test.
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
SUBPROCESS_TEARDOWN_GRACE_SECONDS = 10


@pytest.fixture(scope="session")
def site():
    return DEFAULT_SITE


def _wipe_conductor_state(site_name: str) -> None:
    """XGROUP DESTROY all conductor consumer groups, then delete all
    conductor:{site}:* keys, then delete all DocType rows."""
    import frappe
    from conductor.client import get_redis
    from conductor.config import load_config
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)

    # First: XGROUP DESTROY on every stream key (queues + DLQ). This scrubs
    # the PEL of stale message-IDs even when the stream itself is recreated.
    stream_keys = list(r.keys(f"conductor:{site_name}:stream:*"))
    dlq_keys = list(r.keys(f"conductor:{site_name}:dlq:*"))
    for skey in stream_keys + dlq_keys:
        try:
            for g in (r.xinfo_groups(skey) or []):
                gname = g["name"]
                try:
                    r.xgroup_destroy(skey, gname)
                except Exception:
                    pass
        except Exception:
            # NOGROUP / stream missing — fine.
            pass

    # Then: delete every conductor key for this site.
    for key in r.keys(f"conductor:{site_name}:*"):
        r.delete(key)

    # Then: delete DocType rows in dependency order (DLQ Entry → Job Run → Job).
    for doctype in ("Conductor DLQ Entry", "Conductor Job Run", "Conductor Job"):
        for n in frappe.get_all(doctype, pluck="name"):
            frappe.delete_doc(doctype, n, force=True)
    frappe.db.commit()


@pytest.fixture(scope="session", autouse=True)
def _frappe_init(site):
    """One-time Frappe init for the test process. Wipes any leftover Conductor
    state from prior chaos runs."""
    os.chdir(str(BENCH_ROOT))
    import frappe
    frappe.init(site=site, sites_path=str(BENCH_ROOT / "sites"))
    frappe.connect()
    _wipe_conductor_state(site)
    yield
    frappe.destroy()


@pytest.fixture(autouse=True)
def _wipe_conductor_state_per_test(site):
    """Per-test: wipe Conductor Redis keys + DocType rows BEFORE each test.

    Includes XGROUP DESTROY to scrub PEL state so stale pending message IDs
    cannot leak across tests."""
    _wipe_conductor_state(site)
    yield
    # Post-test: same wipe, so no state leaks to the next test even if a
    # subprocess wrote something during teardown.
    _wipe_conductor_state(site)


def _terminate_pgroup(proc: subprocess.Popen, timeout: float = 5.0) -> None:
    """Send SIGTERM to the process group; wait until pgroup is empty (or
    SUBPROCESS_TEARDOWN_GRACE_SECONDS, then SIGKILL)."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return  # already dead
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.killpg(proc.pid, 0)  # raises if no process in group
        except (ProcessLookupError, PermissionError):
            return  # cleanly drained
        time.sleep(0.1)
    # Grace exhausted — escalate.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    # Final wait so the OS reaps the zombie.
    deadline = time.time() + SUBPROCESS_TEARDOWN_GRACE_SECONDS
    while time.time() < deadline:
        try:
            os.killpg(proc.pid, 0)
        except (ProcessLookupError, PermissionError):
            return
        time.sleep(0.1)


@pytest.fixture
def spawn_worker(site):
    """Spawn `bench --site SITE conductor worker` as a subprocess. Teardown
    polls until the process group is empty so a slow worker shutdown cannot
    leak state into the next test."""
    procs: list[subprocess.Popen] = []

    @contextmanager
    def _spawn(*, queue: str = "default", concurrency: int = 1):
        cmd = [
            "bench", "--site", site, "conductor", "worker",
            "--queue", queue, "--concurrency", str(concurrency),
        ]
        env = os.environ.copy()
        env.setdefault("CONDUCTOR_TEST_EXEC_LOCK_TTL_SECONDS", "5")
        env.setdefault("CONDUCTOR_TEST_AUTOCLAIM_IDLE_MS", "8000")
        proc = subprocess.Popen(
            cmd, cwd=str(BENCH_ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
            preexec_fn=os.setsid, env=env,
        )
        procs.append(proc)
        time.sleep(2.0)
        try:
            yield proc
        finally:
            _terminate_pgroup(proc)

    yield _spawn

    for p in procs:
        _terminate_pgroup(p, timeout=0)  # immediate kill on session teardown


@pytest.fixture(autouse=True)
def spawn_scheduler(site):
    """AUTO-spawn a scheduler subprocess for every chaos test.

    The scheduler owns the delay drainer, so any chaos test that exercises
    retries needs the scheduler running. Tests that want to exercise scheduler
    death (test_scheduler_handoff) override this fixture with their own spawn
    pattern."""
    cmd = [
        "bench", "--site", site, "conductor", "scheduler",
        "--lock-ttl-seconds=3",
        "--renew-interval-seconds=1",
        "--poll-interval-seconds=1",
    ]
    proc = subprocess.Popen(
        cmd, cwd=str(BENCH_ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
    )
    time.sleep(2.0)
    try:
        yield proc
    finally:
        _terminate_pgroup(proc)


@pytest.fixture
def fakemethod_failing():
    """Returns the dotted-path of a function that always raises.

    Uses conductor.demo.boom, which already serves this purpose throughout the
    test suite. Adding a separate always_raises would duplicate intent."""
    return "conductor.demo.boom"


def wait_for_status(job_id: str, expected: str, *, timeout: float = 30.0) -> str:
    """Poll the DB until job reaches `expected` or timeout."""
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
