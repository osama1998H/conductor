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
    """One-time per-session Frappe init for the test process itself."""
    import os
    os.chdir(str(BENCH_ROOT))
    import frappe
    frappe.init(site=site, sites_path=str(BENCH_ROOT / "sites"))
    frappe.connect()
    yield
    frappe.destroy()


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
