"""Side-effect hooks the worker fires for workflow-bound jobs.

Kept out of conductor/worker.py so they can be tested without spinning up a
worker loop.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import frappe

from conductor.logging import get_logger
from conductor.messages import emit_workflow_event

log = get_logger("conductor.workflow.worker_hooks")


def _now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _step_run_name(workflow_run_id: str, step_id: str, *, is_compensation: bool) -> Optional[str]:
    rows = frappe.get_all(
        "Conductor Workflow Step Run",
        filters={
            "workflow_run": workflow_run_id,
            "step_id": step_id,
            "is_compensation": 1 if is_compensation else 0,
        },
        pluck="name",
        limit=1,
    )
    return rows[0] if rows else None


def mark_step_running(*, workflow_run_id: str, step_id: str, is_compensation: bool) -> None:
    name = _step_run_name(workflow_run_id, step_id, is_compensation=is_compensation)
    if name is None:
        log.warning("mark_running_missing_row", run_id=workflow_run_id, step_id=step_id)
        return
    frappe.db.set_value(
        "Conductor Workflow Step Run", name,
        {"status": "RUNNING", "started_at": _now_naive()},
        update_modified=False,
    )
    frappe.db.commit()


def mark_step_terminal(
    *,
    workflow_run_id: str,
    step_id: str,
    is_compensation: bool,
    success: bool,
    error_type: str = "",
    error_message: str = "",
) -> None:
    name = _step_run_name(workflow_run_id, step_id, is_compensation=is_compensation)
    if name is None:
        log.warning("mark_terminal_missing_row", run_id=workflow_run_id, step_id=step_id)
        return

    if is_compensation:
        new_status = "COMPENSATED" if success else "FAILED"
    else:
        new_status = "SUCCEEDED" if success else "FAILED"

    update = {
        "status": new_status,
        "finished_at": _now_naive(),
    }
    if not success:
        update["error_type"] = error_type[:140]
        update["error_message"] = error_message[:240]
    frappe.db.set_value(
        "Conductor Workflow Step Run", name, update, update_modified=False,
    )

    # Transition the run on forward-step terminal failure.
    if not success and not is_compensation:
        frappe.db.set_value(
            "Conductor Workflow Run", workflow_run_id, "status", "COMPENSATING",
            update_modified=False,
        )
        frappe.db.commit()
        emit_workflow_event(run_id=workflow_run_id, status="COMPENSATING")
        return

    # Halt run on compensation-step terminal failure (locked spec decision A.1).
    if not success and is_compensation:
        frappe.db.set_value(
            "Conductor Workflow Run", workflow_run_id,
            {"status": "FAILED", "finished_at": _now_naive(),
             "last_error": f"compensation failed at step {step_id}: {error_type}: {error_message}"},
            update_modified=False,
        )
        frappe.db.commit()
        emit_workflow_event(run_id=workflow_run_id, status="FAILED")
        return

    frappe.db.commit()
