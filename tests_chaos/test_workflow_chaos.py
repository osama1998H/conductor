"""Workflow chaos: diamond DAG runs to SUCCEEDED through real worker subprocesses."""

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

    # Debug output on timeout
    frappe.db.rollback()
    rows = frappe.get_all(
        "Conductor Workflow Step Run",
        filters={"workflow_run": run_id},
        fields=["step_id", "is_compensation", "status"],
        order_by="step_id, is_compensation",
    )
    print(f"\nDEBUG: Timeout waiting for {expected}. Run status: {last}")
    print("Step runs:")
    for row in rows:
        print(f"  {row['step_id']:2} comp={row['is_compensation']} status={row['status']}")

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




def test_diamond_c_terminal_fail_compensates_a(site, spawn_worker):
    """4-step workflow A → {B, C} → D; C fails terminally → A's compensation
    runs in reverse-topo order; run lands FAILED."""
    from conductor.workflow import run_workflow

    frappe.cache().delete_value("conductor:demo:undo_a:ran")
    frappe.cache().delete_value("conductor:demo:undo_b:ran")

    with spawn_worker(queue="default", concurrency=2):
        with spawn_worker(queue="workflow", concurrency=1):
            run_id = run_workflow("DemoCompensatingDiamond")
            status = _wait_run_status(run_id, "FAILED", timeout=300.0)

            assert status == "FAILED", f"run did not reach FAILED: status={status!r}"

    rows = frappe.get_all(
        "Conductor Workflow Step Run",
        filters={"workflow_run": run_id},
        fields=["step_id", "is_compensation", "status"],
    )
    by_key = {(r["step_id"], r["is_compensation"]): r["status"] for r in rows}

    assert by_key.get(("a", 0)) == "SUCCEEDED", f"unexpected a forward state: {by_key}"
    assert by_key.get(("c", 0)) == "FAILED", f"unexpected c forward state: {by_key}"

    assert by_key.get(("a", 1)) == "COMPENSATED", \
        f"a's compensation did not run; rows={by_key}"
    assert frappe.cache().get_value("conductor:demo:undo_a:ran") == "1", \
        "undo_a side-effect not observed"

    if by_key.get(("b", 0)) == "SUCCEEDED":
        assert by_key.get(("b", 1)) == "COMPENSATED", \
            f"b succeeded but its compensation did not run; rows={by_key}"
