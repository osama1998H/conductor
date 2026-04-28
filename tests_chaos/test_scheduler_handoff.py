"""Chaos: kill the scheduler holding the singleton lock; verify a peer takes
over within ~5s (test-time intervals) and resumes the delay loop."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

BENCH_ROOT = Path("/Users/osamamuhammed/frappe_15")


@pytest.fixture
def spawn_scheduler(site):
    """Override the autouse scheduler — this test manages two scheduler
    subprocesses by hand."""
    procs: list[subprocess.Popen] = []

    def _spawn():
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
        procs.append(proc)
        return proc

    yield _spawn

    for p in procs:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _read_lock(site: str) -> str | None:
    import frappe
    from conductor.client import get_redis
    from conductor.config import load_config
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    val = r.get(f"conductor:{site}:scheduler:lock")
    return val.decode() if val else None


def test_scheduler_handoff_takes_over_within_5s(site, spawn_scheduler):
    # Spawn A.
    proc_a = spawn_scheduler()

    # Wait until A holds the lock.
    deadline = time.time() + 8
    holder_a = None
    while time.time() < deadline:
        v = _read_lock(site)
        if v:
            holder_a = v
            break
        time.sleep(0.2)
    assert holder_a is not None, "scheduler-A never acquired lock"

    # Kill -9 A.
    os.killpg(proc_a.pid, signal.SIGKILL)

    # Spawn B.
    proc_b = spawn_scheduler()

    # Wait for the lock value to flip to a different instance_id (≤ 8s with
    # TTL=3 + poll=1 = ≤ 4s; allow margin for OS / Frappe init).
    deadline = time.time() + 8
    holder_b = None
    while time.time() < deadline:
        v = _read_lock(site)
        if v and v != holder_a:
            holder_b = v
            break
        time.sleep(0.2)
    assert holder_b is not None, f"scheduler-B never took over from {holder_a!r}"
    assert holder_b != holder_a


def test_scheduler_handoff_drains_zset_after_takeover(site, spawn_scheduler):
    """After takeover, scheduler-B's delay loop drains a due ZSET entry."""
    import frappe
    from conductor.client import get_redis
    from conductor.config import load_config
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)

    # Ensure 'default' queue exists.
    if not frappe.db.exists("Conductor Queue", "default"):
        frappe.get_doc({
            "doctype": "Conductor Queue",
            "queue_name": "default",
            "enabled": 1,
        }).insert(ignore_permissions=True)
        frappe.db.commit()

    # Spawn A, wait for lock, kill it, spawn B.
    proc_a = spawn_scheduler()
    deadline = time.time() + 8
    while time.time() < deadline:
        if _read_lock(site):
            break
        time.sleep(0.2)
    os.killpg(proc_a.pid, signal.SIGKILL)
    proc_b = spawn_scheduler()

    # Wait for B to acquire.
    deadline = time.time() + 8
    while time.time() < deadline:
        v = _read_lock(site)
        if v:
            break
        time.sleep(0.2)

    # Inject a due ZSET entry.
    encoded = {
        "job_id": "handoff-test-job",
        "site": site,
        "name": "frappe.utils.now",
        "queue": "default",
        "args_b64": "",
        "kwargs_b64": "",
        "attempt": "1",
        "max_attempts": "1",
        "timeout_seconds": "60",
        "enqueued_at": "2026-04-27T12:00:00+00:00",
        "schema_version": "1",
    }
    member = json.dumps(encoded)
    score = int(time.time() * 1000) - 1000
    r.zadd(f"conductor:{site}:scheduled", {member: score})

    # Wait for delay loop to drain it (≤ 2s with 1s tick).
    deadline = time.time() + 5
    drained = False
    while time.time() < deadline:
        if r.zcard(f"conductor:{site}:scheduled") == 0:
            drained = True
            break
        time.sleep(0.2)
    assert drained, "scheduler-B did not drain the due ZSET entry within 5s"

    # And the entry landed on the queue stream.
    entries = r.xrange(f"conductor:{site}:stream:default")
    assert len(entries) >= 1
