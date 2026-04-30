"""Rate-limit chaos: per-(site, queue) rate limit caps throughput.

Configures Conductor Queue 'default' with max_rps=10. Dispatches 50 jobs that
sleep 100 ms each (via conductor.demo.sleep — `time.sleep` cannot be used
directly because frappe.get_attr treats the first dotted segment as an app
name). With concurrency=20, no rate limit would mean wall time
≈ 50 × 0.1 / 20 = 0.25 s. With max_rps=10 (and 1s delay-loop tick), realistic
wall time is 4–6 s. We assert [3.5, 8.0] for CI tolerance.
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


@pytest.fixture
def rate_limit_set():
    """Set max_rps=10 for 'default'; reset to 0 in teardown.

    Uses frappe.db.set_value + clear_document_cache rather than `q.save()`
    because q.save() has been observed to leave a stale Redis-side cached
    doc that worker subprocesses read before seeing the new value."""
    original_rps = int(frappe.db.get_value("Conductor Queue", "default", "max_rps") or 0)
    frappe.db.set_value("Conductor Queue", "default", "max_rps", 10)
    frappe.db.commit()
    frappe.clear_document_cache("Conductor Queue", "default")
    yield
    frappe.db.set_value("Conductor Queue", "default", "max_rps", original_rps)
    frappe.db.commit()
    frappe.clear_document_cache("Conductor Queue", "default")


def _parse_job_id(raw: bytes) -> str:
    """`bench execute` prints structlog info lines + the quoted return value.
    Pull the UUID out of the last non-empty line."""
    last_line = next(
        (ln.strip() for ln in reversed(raw.decode().splitlines()) if ln.strip()),
        "",
    )
    return last_line.strip("'").strip('"').strip()


def _enqueue_sleep(site: str, n: int, sleep_s: float) -> list[str]:
    ids: list[str] = []
    for _ in range(n):
        out = subprocess.check_output(
            ["bench", "--site", site, "execute", "conductor.enqueue",
             "--kwargs", f'{{"method": "conductor.demo.sleep", "queue": "default", "seconds": {sleep_s}}}'],
            cwd=str(BENCH_ROOT), timeout=60,
        )
        jid = _parse_job_id(out)
        if jid:
            ids.append(jid)
    return ids


def _spawn_worker(concurrency: int) -> subprocess.Popen:
    return subprocess.Popen(
        ["bench", "--site", SITE, "conductor", "worker",
         "--queue", "default", "--concurrency", str(concurrency), "--grace", "5"],
        cwd=str(BENCH_ROOT),
        preexec_fn=os.setsid,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _wait_for_drain(job_ids: list[str], deadline_s: float) -> float:
    start = time.time()
    while time.time() - start < deadline_s:
        frappe.db.rollback()
        rows = frappe.db.sql(
            "SELECT COUNT(*) FROM `tabConductor Job` WHERE name IN %s "
            "AND status NOT IN ('SUCCEEDED','FAILED','TIMED_OUT','DLQ')",
            (tuple(job_ids),),
        )
        unfinished = int(rows[0][0]) if rows else 0
        if unfinished == 0:
            return time.time() - start
        time.sleep(0.2)
    raise AssertionError(f"jobs did not drain within {deadline_s}s; unfinished={unfinished}")


def test_rate_limit_caps_throughput(rate_limit_set):
    """50 jobs × 0.1s sleep, max_rps=10, concurrency=20 → wall time in [3.5, 8.0]."""
    job_ids = _enqueue_sleep(SITE, 50, 0.1)
    assert len(job_ids) == 50

    worker = _spawn_worker(concurrency=20)
    try:
        elapsed = _wait_for_drain(job_ids, deadline_s=15.0)
    finally:
        try:
            os.killpg(os.getpgid(worker.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        worker.wait(timeout=10)

    print(f"\nRATE-LIMIT WALL TIME: {elapsed:.2f}s (expected [3.5, 8.0])")
    assert elapsed >= 3.5, (
        f"wall time {elapsed:.2f}s — too fast, rate limit did not throttle. "
        f"Without throttling 50 × 0.1s ÷ 20 concurrency = 0.25s, so anything > 1s "
        f"proves rate-limit kicked in; we expect ~5s."
    )
    assert elapsed <= 8.0, (
        f"wall time {elapsed:.2f}s — too slow. Either delay-loop is stalling, "
        f"the throttle path is leaking jobs to DLQ, or worker concurrency is wrong."
    )

    # All jobs SUCCEEDED
    frappe.db.rollback()
    rows = frappe.db.sql(
        "SELECT status, COUNT(*) FROM `tabConductor Job` WHERE name IN %s GROUP BY status",
        (tuple(job_ids),),
    )
    by_status = {r[0]: int(r[1]) for r in rows}
    assert by_status.get("SUCCEEDED", 0) == 50, by_status
