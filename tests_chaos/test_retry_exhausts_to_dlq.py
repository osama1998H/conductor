"""Chaos test: a function that always raises hits max_attempts and lands in DLQ
correctly even when a worker is killed mid-retry sequence."""

import os
import signal
import time

import frappe

import conductor
from tests_chaos.conftest import wait_for_status


def test_retry_exhausts_to_dlq_under_chaos(spawn_worker):
    os.environ["CONDUCTOR_TEST_AUTOCLAIM_IDLE_MS"] = "8000"
    os.environ["CONDUCTOR_TEST_EXEC_LOCK_TTL_SECONDS"] = "5"

    with spawn_worker() as worker_a:
        # Tight retry loop: 3 attempts, base_delay=0.5s
        job_id = conductor.enqueue(
            "conductor.demo.boom",
            queue="default",
            max_attempts=3,
            timeout=10,
        )

        # Give worker A a chance to start the first attempt, then kill it.
        time.sleep(0.5)
        try:
            os.killpg(worker_a.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    # A new worker handles the rest of the retry chain. Generous timeout: the
    # full chain involves XAUTOCLAIM idle window (8s), 3 retry-delay windows
    # (each base_delay*2^attempt with full jitter, total up to ~14s), drainer
    # latency (~1s per cycle), and Frappe DB roundtrips. On a busy host this
    # can take well over a minute.
    with spawn_worker() as worker_b:
        final = wait_for_status(job_id, "DLQ", timeout=180)
        assert final == "DLQ", f"expected DLQ, got {final}"

        # Refresh DB snapshot before querying child rows (subprocess workers
        # commit Job Run / DLQ Entry in separate txns; our connection may
        # still see a stale snapshot otherwise).
        frappe.db.rollback()

        # Three Job Run rows (some may be TIMED_OUT from the reclaim race;
        # at least one will be FAILED from boom; total count == max_attempts).
        runs = frappe.get_all(
            "Conductor Job Run", filters={"job": job_id}, fields=["name", "status"]
        )
        assert len(runs) >= 3, f"expected ≥3 runs, got {len(runs)}: {[r.status for r in runs]}"
        assert all(r.status in ("FAILED", "TIMED_OUT") for r in runs), [r.status for r in runs]

        # Exactly one DLQ Entry
        dlq = frappe.get_all("Conductor DLQ Entry", filters={"job": job_id}, fields=["name"])
        assert len(dlq) == 1

        # Cleanup
        for d in dlq:
            frappe.delete_doc("Conductor DLQ Entry", d.name, force=True)
        for r in runs:
            frappe.delete_doc("Conductor Job Run", r.name, force=True)
        frappe.delete_doc("Conductor Job", job_id, force=True)

    os.environ.pop("CONDUCTOR_TEST_AUTOCLAIM_IDLE_MS", None)
    os.environ.pop("CONDUCTOR_TEST_EXEC_LOCK_TTL_SECONDS", None)
