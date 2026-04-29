"""Unified advancer for Conductor workflow runs.

Spec §3 + §6.1 + §6.2. Single entry-point branches on run.status:
  - PENDING / RUNNING : forward path (this module, this task)
  - COMPENSATING       : compensation path (added in Task 14)

The advancer is itself a Conductor job decorated with @conductor.job(queue="workflow")
so it inherits Phase-1 retry/timeout semantics. If it dies mid-run, Phase-1
reclamation re-runs it; the body is idempotent.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

import frappe

import conductor as _conductor
from conductor.client import get_redis
from conductor.config import load_config
from conductor.decorator import job as conductor_job
from conductor.logging import get_logger
from conductor.messages import emit_workflow_event
from conductor.serialization import loads as msgpack_loads
from conductor.workflow.decorator import get_registered
from conductor.workflow.keys import wfdeps_key
from conductor.workflow.lua import FANIN_DECREMENT

log = get_logger("conductor.workflow.advancer")


def _decode_kwargs(b64: str) -> dict[str, Any]:
    if not b64:
        return {}
    import base64
    return msgpack_loads(base64.b64decode(b64.encode("ascii")))


def _now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _downstreams_of(cls, completed_step_id: str) -> list[str]:
    return sorted(
        s.name for s in cls.__conductor_workflow_steps__
        if completed_step_id in s.depends_on
    )


def _step_run(workflow_run_id: str, step_id: str, *, is_compensation: int = 0):
    return frappe.get_doc(
        "Conductor Workflow Step Run",
        {
            "workflow_run": workflow_run_id,
            "step_id": step_id,
            "is_compensation": is_compensation,
        },
    )


def _enqueue_step_job(*, run_id: str, step_id: str, cls, run_kwargs: dict[str, Any], is_compensation: bool = False) -> str:
    """Enqueue a single step's underlying Conductor Job.

    The full method path is the workflow class's dotted path + the step
    method name (or compensation method for compensation steps).
    The worker resolves this via frappe.get_attr.
    """
    if is_compensation:
        # For compensation, find the step and use its compensation method name.
        step_def = next(s for s in cls.__conductor_workflow_steps__ if s.name == step_id)
        method_name = step_def.compensation
        idempotency_key = f"wf:{run_id}:{step_id}:compensate"
    else:
        method_name = step_id
        idempotency_key = f"wf:{run_id}:{step_id}:dispatch"

    method_path = f"{cls.__module__}.{cls.__qualname__}.{method_name}"
    return _conductor.enqueue(
        method=method_path,
        queue=cls.__conductor_workflow_queue__,
        idempotency_key=idempotency_key,
        __workflow_run_id=run_id,
        __step_id=step_id,
        __is_compensation=is_compensation,
        **run_kwargs,
    )


def _all_forward_terminal(run_id: str) -> bool:
    pending = frappe.db.count(
        "Conductor Workflow Step Run",
        filters={
            "workflow_run": run_id,
            "is_compensation": 0,
            "status": ["in", ["PENDING", "READY", "RUNNING"]],
        },
    )
    return pending == 0


def _all_forward_succeeded(run_id: str) -> bool:
    rows = frappe.get_all(
        "Conductor Workflow Step Run",
        filters={"workflow_run": run_id, "is_compensation": 0},
        fields=["status"],
    )
    return rows and all(r["status"] == "SUCCEEDED" for r in rows)


@conductor_job(queue="workflow", max_attempts=5, timeout=120)
def advance(*, workflow_run_id: str, completed_step: Optional[str] = None) -> None:
    """Re-evaluate a run and dispatch any newly-ready forward or compensation steps."""
    run = frappe.get_doc("Conductor Workflow Run", workflow_run_id)

    if run.status in ("PENDING", "RUNNING"):
        _advance_forward(run, completed_step)
        return

    if run.status == "COMPENSATING":
        _advance_compensation(run, completed_step)
        return

    log.debug("advance_noop_terminal_status", run_id=workflow_run_id, status=run.status)


def _advance_forward(run, completed_step: Optional[str]) -> None:
    """Forward-path logic: dispatch newly-ready steps."""
    workflow_run_id = run.name
    cls = get_registered(run.workflow)
    if cls is None:
        log.error("advance_unknown_workflow", run_id=workflow_run_id, workflow=run.workflow)
        return

    site = frappe.local.site
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)

    if completed_step is None:
        downstreams_argv: list[str] = []
        completed_argv = ""
    else:
        downstreams_argv = _downstreams_of(cls, completed_step)
        completed_argv = completed_step

    ready_raw = r.eval(
        FANIN_DECREMENT, 1, wfdeps_key(site, workflow_run_id),
        completed_argv, json.dumps(downstreams_argv),
    )
    ready = sorted(s.decode() if isinstance(s, bytes) else s for s in ready_raw)

    if run.status == "PENDING" and ready:
        run.status = "RUNNING"
        run.started_at = _now_naive()
        run.save(ignore_permissions=True)
        frappe.db.commit()
        emit_workflow_event(run_id=run.name, status="RUNNING")

    run_kwargs = _decode_kwargs(run.input_kwargs or "")

    for step_id in ready:
        try:
            sr = _step_run(workflow_run_id, step_id)
        except frappe.DoesNotExistError:
            log.warning("advance_missing_step_run", run_id=workflow_run_id, step_id=step_id)
            continue
        if sr.status != "PENDING":
            # Already dispatched by a concurrent advancer; skip.
            continue
        sr.status = "READY"
        sr.save(ignore_permissions=True)
        frappe.db.commit()

        job_id = _enqueue_step_job(
            run_id=workflow_run_id, step_id=step_id, cls=cls, run_kwargs=run_kwargs,
        )
        frappe.db.set_value(
            "Conductor Workflow Step Run", sr.name, "job", job_id,
            update_modified=False,
        )
        frappe.db.commit()

    if _all_forward_terminal(workflow_run_id) and _all_forward_succeeded(workflow_run_id):
        frappe.db.set_value(
            "Conductor Workflow Run", workflow_run_id,
            {"status": "SUCCEEDED", "finished_at": _now_naive()},
            update_modified=False,
        )
        frappe.db.commit()
        emit_workflow_event(run_id=workflow_run_id, status="SUCCEEDED")


def _advance_compensation(run, just_completed: Optional[str]) -> None:
    """Compensation-path logic: dispatch compensation steps in reverse-topo order."""
    workflow_run_id = run.name
    cls = get_registered(run.workflow)
    if cls is None:
        return

    # Skip not-yet-dispatched forward steps so they don't block in-flight
    # forever (e.g., D depending on B+C is still PENDING because C failed;
    # advancer no-ops on COMPENSATING so D would sit PENDING indefinitely).
    # Only PENDING is safe to skip — READY rows have a job already on the
    # stream and a worker will pick them up, complete them, and re-fire
    # the advancer via the worker hook.
    skip_targets = frappe.get_all(
        "Conductor Workflow Step Run",
        filters={
            "workflow_run": workflow_run_id,
            "is_compensation": 0,
            "status": "PENDING",
        },
        pluck="name",
    )
    for n in skip_targets:
        frappe.db.set_value("Conductor Workflow Step Run", n, "status", "SKIPPED",
                            update_modified=False)

    # Wait for any forward step in flight (READY or RUNNING) to terminate.
    in_flight = frappe.db.count(
        "Conductor Workflow Step Run",
        filters={
            "workflow_run": workflow_run_id,
            "is_compensation": 0,
            "status": ["in", ["READY", "RUNNING"]],
        },
    )
    if in_flight:
        frappe.db.commit()
        return
    frappe.db.commit()

    completed_forward = {
        r["step_id"] for r in frappe.get_all(
            "Conductor Workflow Step Run",
            filters={"workflow_run": workflow_run_id, "is_compensation": 0, "status": "SUCCEEDED"},
            fields=["step_id"],
        )
    }
    already_compensated = {
        r["step_id"] for r in frappe.get_all(
            "Conductor Workflow Step Run",
            filters={"workflow_run": workflow_run_id, "is_compensation": 1},
            fields=["step_id"],
        )
    }
    pending = completed_forward - already_compensated

    if not pending:
        frappe.db.set_value(
            "Conductor Workflow Run", workflow_run_id,
            {"status": "FAILED", "finished_at": _now_naive()},
            update_modified=False,
        )
        frappe.db.commit()
        emit_workflow_event(run_id=workflow_run_id, status="FAILED")
        return

    from conductor.workflow.topo import reverse_topo_order
    sequence = reverse_topo_order(cls.__conductor_workflow_steps__, only=pending)
    next_step_id = sequence[0]
    step_def = next(s for s in cls.__conductor_workflow_steps__ if s.name == next_step_id)

    if step_def.compensation is None:
        # No-op compensation row, then recurse via re-enqueue.
        frappe.get_doc({
            "doctype": "Conductor Workflow Step Run",
            "workflow_run": workflow_run_id, "step_id": next_step_id,
            "is_compensation": 1, "status": "COMPENSATED",
            "started_at": _now_naive(), "finished_at": _now_naive(),
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        enqueue_advance(workflow_run_id, completed_step=next_step_id)
        return

    # Insert compensation row READY; dispatcher will mark RUNNING then enqueue.
    sr = frappe.get_doc({
        "doctype": "Conductor Workflow Step Run",
        "workflow_run": workflow_run_id, "step_id": next_step_id,
        "is_compensation": 1, "status": "READY",
    }).insert(ignore_permissions=True)
    frappe.db.commit()

    run_kwargs = _decode_kwargs(run.input_kwargs or "")
    job_id = _enqueue_step_job(
        run_id=workflow_run_id, step_id=next_step_id, cls=cls, run_kwargs=run_kwargs,
        is_compensation=True,
    )
    frappe.db.set_value(
        "Conductor Workflow Step Run", sr.name, "job", job_id, update_modified=False,
    )
    frappe.db.commit()


def enqueue_advance(workflow_run_id: str, completed_step: Optional[str]) -> None:
    """Enqueue an advancer job for this run. Idempotent on (run_id, completed_step)."""
    completed_or_start = completed_step or "start"
    _conductor.enqueue(
        method="conductor.workflow.advancer.advance",
        queue="workflow",
        idempotency_key=f"wf:{workflow_run_id}:advance:{completed_or_start}",
        workflow_run_id=workflow_run_id,
        completed_step=completed_step,
    )
