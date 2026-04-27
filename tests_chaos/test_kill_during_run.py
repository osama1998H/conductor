"""Chaos test: kill -9 a worker mid-job; a peer must reclaim and finish.

Deterministic structure: spawn worker A first and let it claim the slow job,
THEN kill -9 worker A, THEN spawn worker B. This guarantees A held the message
when killed; B comes up to a stale pending-entries-list and XAUTOCLAIMs.

Production XAUTOCLAIM idle threshold is 60s (worker._AUTOCLAIM_IDLE_MS). For
tests we override it via CONDUCTOR_TEST_AUTOCLAIM_IDLE_MS=8000 plus
CONDUCTOR_TEST_EXEC_LOCK_TTL_SECONDS=5 (both set in spawn_worker fixture env).
The 8s autoclaim idle must EXCEED 5s exec-lock TTL so by the time B reclaims
the message, A's lock has already expired and B can re-acquire it.

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
    """Worker A spawns alone, claims the slow job, dies. Worker B then comes up
    and must XAUTOCLAIM the orphaned message and complete it."""
    # Phase 1: worker A alone. It will claim the job because it's the only
    # consumer in the group with `>` outstanding.
    with spawn_worker() as worker_a:
        job_id = conductor.enqueue("conductor.demo.slow_chaos", queue="default", timeout=20)
        # Give A enough time to XREADGROUP and start executing slow_chaos
        # (which sleeps 8s in its body).
        time.sleep(3.0)

        try:
            os.killpg(worker_a.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    # Phase 2: worker B comes up and must reclaim A's orphaned pending entry.
    # Lock TTL = 5s (already expired since kill happened ≥3s ago + B startup);
    # autoclaim idle = 8s, so B's first iteration after spawn-warmup may
    # need to wait until t ~= 8s after A claimed. We give 90s total to be safe.
    with spawn_worker() as worker_b:
        final = wait_for_status(job_id, "SUCCEEDED", timeout=90)
        assert final == "SUCCEEDED", f"expected SUCCEEDED, got {final}"

        runs = frappe.get_all(
            "Conductor Job Run", filters={"job": job_id}, fields=["name", "status"]
        )
        assert any(r.status == "SUCCEEDED" for r in runs), runs

        for r in runs:
            frappe.delete_doc("Conductor Job Run", r.name, force=True)
        frappe.delete_doc("Conductor Job", job_id, force=True)
