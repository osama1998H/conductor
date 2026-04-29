"""cancel_workflow_run — best-effort interrupt without compensation.

Spec §5.4 + §6.3.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import frappe

import conductor.cancellation
from conductor.client import get_redis
from conductor.config import load_config
from conductor.logging import get_logger
from conductor.messages import emit_workflow_event
from conductor.workflow.keys import wfdeps_key

log = get_logger("conductor.workflow.cancellation")


def _now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def cancel_workflow_run(run_id: str, *, user: Optional[str] = None) -> None:
    """Mark the run CANCELLED, skip un-dispatched steps, cancel running step jobs.

    Idempotent — calling on an already-terminal run is a no-op."""
    run = frappe.get_doc("Conductor Workflow Run", run_id)
    if run.status in ("SUCCEEDED", "FAILED", "CANCELLED"):
        return

    user = user or frappe.session.user

    # Skip un-started forward steps
    skip_targets = frappe.get_all(
        "Conductor Workflow Step Run",
        filters={
            "workflow_run": run_id,
            "is_compensation": 0,
            "status": ["in", ["PENDING", "READY"]],
        },
        pluck="name",
    )
    for n in skip_targets:
        frappe.db.set_value("Conductor Workflow Step Run", n, "status", "SKIPPED",
                            update_modified=False)

    # Cancel any in-flight step jobs (Phase-1 cancel_job path).
    running = frappe.get_all(
        "Conductor Workflow Step Run",
        filters={"workflow_run": run_id, "status": "RUNNING"},
        fields=["name", "job"],
    )
    for row in running:
        if row["job"]:
            try:
                conductor.cancellation.cancel_job(row["job"])
            except Exception as e:
                log.warning("cancel_job_failed", run_id=run_id, job=row["job"], error=str(e))

    frappe.db.set_value(
        "Conductor Workflow Run", run_id,
        {
            "status": "CANCELLED",
            "cancelled_at": _now_naive(),
            "cancelled_by": user,
            "finished_at": _now_naive(),
        },
        update_modified=False,
    )
    frappe.db.commit()
    emit_workflow_event(run_id=run_id, status="CANCELLED")

    # Drop the deps hash; Lua scripts no longer need it.
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    r.delete(wfdeps_key(frappe.local.site, run_id))
