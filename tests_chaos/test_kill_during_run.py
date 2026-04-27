"""Chaos test: kill -9 a worker mid-job; a peer must reclaim and finish.

Production XAUTOCLAIM idle threshold is 60s (worker._AUTOCLAIM_IDLE_MS). For
tests we override it via CONDUCTOR_TEST_AUTOCLAIM_IDLE_MS=1500 (set in the
spawn_worker fixture's env). The dispatched slow_chaos function sleeps long
enough for the kill to happen mid-execution; the peer worker reclaims and
finishes within ~30s.

``slow_chaos`` is a top-level function in ``conductor.demo`` so subprocess
workers can import it fresh via ``frappe.get_attr("conductor.demo.slow_chaos")``.
"""

from __future__ import annotations

import os
import signal
import time

import frappe

import conductor
from tests_chaos.conftest import wait_for_status


def test_kill_during_run_reclaims_and_completes(spawn_worker):
    """Worker A picks up a slow job. We kill -9 worker A at t=2s. Worker B,
    spawned at the same time, must eventually XAUTOCLAIM and finish the job."""
    with spawn_worker() as worker_a, spawn_worker() as worker_b:
        # Dispatch the slow job. Whichever worker reads first holds it.
        job_id = conductor.enqueue("conductor.demo.slow_chaos", queue="default", timeout=20)
        time.sleep(2.0)  # let one worker start the job

        try:
            os.killpg(worker_a.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

        # Worker B must reclaim within ~30s.
        final = wait_for_status(job_id, "SUCCEEDED", timeout=60)
        assert final == "SUCCEEDED", f"expected SUCCEEDED, got {final}"

        runs = frappe.get_all(
            "Conductor Job Run", filters={"job": job_id}, fields=["name", "status"]
        )
        assert any(r.status == "SUCCEEDED" for r in runs), runs

        for r in runs:
            frappe.delete_doc("Conductor Job Run", r.name, force=True)
        frappe.delete_doc("Conductor Job", job_id, force=True)
