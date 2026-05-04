"""Whitelisted API surface for the dashboard's Workflows tab.

Permissions: Conductor Operator can read everything and cancel runs;
System Manager retains full access.
"""

from __future__ import annotations

from typing import Any, Optional

import frappe


_NULLISH_STRINGS = frozenset(("null", "undefined", "none", ""))


def _is_nullish(v: object) -> bool:
    """True when a query parameter is JS-null-ish — None, empty string,
    or one of the sentinel strings JS serializers commonly emit."""
    if v is None:
        return True
    if isinstance(v, str) and v.strip().lower() in _NULLISH_STRINGS:
        return True
    return False


def _require_read() -> None:
    if not (
        frappe.has_permission("Conductor Workflow", "read")
        or "Conductor Operator" in frappe.get_roles()
    ):
        raise frappe.PermissionError("Not permitted")


def _require_operator_or_sysmgr() -> None:
    roles = set(frappe.get_roles())
    if not (roles & {"Conductor Operator", "System Manager"}):
        raise frappe.PermissionError("Conductor Operator or System Manager required")


@frappe.whitelist()
def list_workflows() -> list[dict[str, Any]]:
    _require_read()
    rows = frappe.get_all(
        "Conductor Workflow",
        fields=["workflow_name", "version", "enabled", "last_version_bumped_at"],
        order_by="workflow_name asc",
    )
    for r in rows:
        r["active_runs"] = frappe.db.count(
            "Conductor Workflow Run",
            filters={"workflow": r["workflow_name"], "status": ["in", ["PENDING", "RUNNING", "COMPENSATING"]]},
        )
        r["recent_runs_24h"] = frappe.db.count(
            "Conductor Workflow Run",
            filters={
                "workflow": r["workflow_name"],
                "creation": [">", frappe.utils.add_to_date(None, hours=-24)],
            },
        )
    return rows


@frappe.whitelist()
def list_runs(
    workflow: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    _require_read()
    filters: dict[str, Any] = {}
    if not _is_nullish(workflow):
        filters["workflow"] = workflow
    if not _is_nullish(status):
        filters["status"] = status
    rows = frappe.get_all(
        "Conductor Workflow Run",
        filters=filters,
        fields=["name", "workflow", "definition_version", "status",
                "started_at", "finished_at", "idempotency_key", "creation"],
        order_by="creation desc",
        limit=int(limit),
        start=int(offset),
    )
    return rows


@frappe.whitelist()
def get_run(run_id: str) -> dict[str, Any]:
    _require_read()
    if not frappe.db.exists("Conductor Workflow Run", run_id):
        raise frappe.DoesNotExistError(run_id)
    run = frappe.get_doc("Conductor Workflow Run", run_id).as_dict()
    steps = frappe.get_all(
        "Conductor Workflow Step Run",
        filters={"workflow_run": run_id},
        fields=["name", "step_id", "is_compensation", "status",
                "started_at", "finished_at", "job", "depends_on",
                "error_type", "error_message"],
        order_by="creation asc",
    )
    snapshot = frappe.db.get_value(
        "Conductor Workflow", run["workflow"], "definition_snapshot"
    ) or ""
    return {"run": run, "steps": steps, "snapshot": snapshot}


@frappe.whitelist()
def cancel_run(run_id: str) -> dict[str, str]:
    _require_operator_or_sysmgr()
    from conductor.workflow import cancel_workflow_run
    cancel_workflow_run(run_id)
    return {"name": run_id, "status": "CANCELLED"}
