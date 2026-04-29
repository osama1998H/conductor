"""Phase 6 exit criterion #3: per-(site, queue) concurrency cap holds — no
sample shows more than `max_concurrent` jobs simultaneously RUNNING.

Configures Conductor Queue 'default' with max_concurrent=2. Dispatches 10
jobs that each sleep 1.0 s (via conductor.demo.sleep — `time.sleep` cannot
be used directly because frappe.get_attr treats the first dotted segment as
an app name). Worker concurrency=10 is intentionally larger than the cap so
the worker would happily run all 10 in parallel if the throttle gate ever
leaked. The main loop polls Conductor Job status every 100 ms (no background
thread, since `frappe.db` is a werkzeug-local proxy bound to the main thread)
and records the max RUNNING count observed across the lifetime of the run.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import frappe
import pytest

BENCH_ROOT = Path("/Users/osamamuhammed/frappe_15")
SITE = "frappe.localhost"

SAMPLE_INTERVAL_S = 0.1
DRAIN_DEADLINE_S = 30.0


def _parse_job_id(raw: bytes) -> str:
    """`bench execute` prints structlog info lines + the quoted return value.
    Pull the UUID out of the last non-empty line."""
    last_line = next(
        (ln.strip() for ln in reversed(raw.decode().splitlines()) if ln.strip()),
        "",
    )
    return last_line.strip("'").strip('"').strip()


@pytest.fixture
def concurrency_cap_set():
    """Set max_concurrent=2 on 'default'; restore original on teardown."""
    q = frappe.get_doc("Conductor Queue", "default")
    original = int(q.max_concurrent or 0)
    q.max_concurrent = 2
    q.save(ignore_permissions=True)
    frappe.db.commit()
    yield
    q = frappe.get_doc("Conductor Queue", "default")
    q.max_concurrent = original
    q.save(ignore_permissions=True)
    frappe.db.commit()


def _enqueue_sleep(n: int, seconds: float) -> list[str]:
    ids: list[str] = []
    for _ in range(n):
        out = subprocess.check_output(
            ["bench", "--site", SITE, "execute", "conductor.enqueue",
             "--kwargs",
             f'{{"method": "conductor.demo.sleep", "queue": "default", "seconds": {seconds}}}'],
            cwd=str(BENCH_ROOT), timeout=60,
        )
        jid = _parse_job_id(out)
        if jid:
            ids.append(jid)
    return ids


def _spawn_worker() -> subprocess.Popen:
    return subprocess.Popen(
        ["bench", "--site", SITE, "conductor", "worker",
         "--queue", "default", "--concurrency", "10", "--grace", "5"],
        cwd=str(BENCH_ROOT),
        preexec_fn=os.setsid,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _sample_running_and_unfinished(job_ids: list[str]) -> tuple[int, int]:
    """Return (running_count, unfinished_count) in a single round-trip.
    Rollback is required because the worker process commits status changes
    in a separate connection."""
    frappe.db.rollback()
    rows = frappe.db.sql(
        "SELECT "
        "  SUM(status='RUNNING'), "
        "  SUM(status NOT IN ('SUCCEEDED','FAILED','TIMED_OUT','DLQ')) "
        "FROM `tabConductor Job` WHERE name IN %s",
        (tuple(job_ids),),
    )
    if not rows:
        return 0, 0
    running, unfinished = rows[0]
    return int(running or 0), int(unfinished or 0)


def _kill_worker(worker: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(worker.pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    worker.wait(timeout=10)


def test_concurrency_cap_caps_running(concurrency_cap_set):
    """10 jobs × 1.0s sleep, max_concurrent=2, worker concurrency=10 →
    no sample observes more than 2 simultaneously RUNNING."""
    job_ids = _enqueue_sleep(10, 1.0)
    assert len(job_ids) == 10

    worker = _spawn_worker()
    samples: list[int] = []
    max_running = 0
    drained = False
    try:
        deadline = time.time() + DRAIN_DEADLINE_S
        while time.time() < deadline:
            running, unfinished = _sample_running_and_unfinished(job_ids)
            samples.append(running)
            if running > max_running:
                max_running = running
            if unfinished == 0:
                drained = True
                break
            time.sleep(SAMPLE_INTERVAL_S)
    finally:
        _kill_worker(worker)

    assert drained, f"jobs did not drain within {DRAIN_DEADLINE_S}s"

    print(
        f"\nMAX RUNNING SAMPLED: {max_running} "
        f"(cap=2; samples={len(samples)})"
    )
    assert max_running <= 2, (
        f"observed {max_running} simultaneously RUNNING — concurrency cap leak"
    )
    assert max_running >= 1, (
        "sampler never caught a RUNNING job — test is meaningless"
    )
