"""Phase 5 chaos: diamond DAG runs to SUCCEEDED through real worker subprocesses."""

from __future__ import annotations

import time

import frappe
import pytest

# Importing demo registers DemoDiamond on _REGISTRY in this process.
import conductor.demo  # noqa: F401


def _wait_run_status(run_id: str, expected: str, *, timeout: float = 30.0) -> str:
    """Poll until run.status == expected or timeout."""
    end = time.time() + timeout
    last = None
    while time.time() < end:
        frappe.db.rollback()
        last = frappe.db.get_value("Conductor Workflow Run", run_id, "status")
        if last == expected:
            return last
        time.sleep(0.3)
    return last or ""


def test_diamond_runs_to_success_through_real_workers(site, spawn_worker):
    """Diamond DAG dispatched by run_workflow; workers on default + workflow
    queues consume steps and advancer; final state is SUCCEEDED."""
    from conductor.workflow import run_workflow

    with spawn_worker(queue="default", concurrency=2):
        with spawn_worker(queue="workflow", concurrency=1):
            run_id = run_workflow("DemoDiamond")
            status = _wait_run_status(run_id, "SUCCEEDED", timeout=60.0)

    assert status == "SUCCEEDED", f"run did not reach SUCCEEDED: status={status!r}"

    rows = frappe.get_all(
        "Conductor Workflow Step Run",
        filters={"workflow_run": run_id, "is_compensation": 0},
        fields=["step_id", "status"],
    )
    by_step = {r["step_id"]: r["status"] for r in rows}
    assert by_step == {"a": "SUCCEEDED", "b": "SUCCEEDED", "c": "SUCCEEDED", "d": "SUCCEEDED"}, \
        f"unexpected step states: {by_step}"
