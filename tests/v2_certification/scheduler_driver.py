"""Force-trigger every Scheduled Job Type and record the Conductor Job outcome.

Usage (under bench):
    bench --site frappe.localhost execute conductor.tests.v2_certification.scheduler_driver.run_all
or, programmatically from a pytest:
    from tests.v2_certification.scheduler_driver import run_all
    results = run_all()

Output:
    A list of result dicts, one per Scheduled Job Type row, with keys:
        id, method, frequency, conductor_job_id, status, attempt,
        duration_ms, error, notes.
    Status values are uppercase per the Conductor Job DocType options:
    QUEUED / RUNNING / SUCCEEDED / FAILED / TIMED_OUT / SCHEDULED_RETRY /
    DLQ / CANCELLED / DISPATCH_FAILED. Terminal statuses (the harness
    waits for one of these): SUCCEEDED, FAILED, TIMED_OUT, DLQ,
    CANCELLED, DISPATCH_FAILED.
    Also serializes the list to docs/roadmap/v2-certification/scheduled-jobs.json.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import frappe

OUTPUT_PATH = Path(
    "/Users/osamamuhammed/frappe_15/apps/conductor/"
    "docs/roadmap/v2-certification/scheduled-jobs.json"
)

POLL_TIMEOUT_SEC = 60
POLL_INTERVAL_SEC = 0.5


def _list_scheduled_job_types() -> list[dict[str, Any]]:
    return frappe.get_all(
        "Scheduled Job Type",
        fields=["name", "method", "frequency", "stopped"],
        filters={"stopped": 0},
        order_by="method",
    )


def _newest_conductor_job_for(method: str, since_unix: float) -> dict[str, Any] | None:
    rows = frappe.get_all(
        "Conductor Job",
        fields=["name", "status", "attempt", "creation", "modified"],
        filters={"method": method},
        order_by="creation desc",
        limit=1,
    )
    if not rows:
        return None
    return rows[0]


def _wait_for_terminal(job_name: str) -> dict[str, Any]:
    deadline = time.time() + POLL_TIMEOUT_SEC
    while time.time() < deadline:
        row = frappe.db.get_value(
            "Conductor Job",
            job_name,
            ["status", "attempt", "modified"],
            as_dict=True,
        )
        if not row:
            time.sleep(POLL_INTERVAL_SEC)
            continue
        if row["status"] in ("SUCCEEDED", "FAILED", "TIMED_OUT", "DLQ", "CANCELLED", "DISPATCH_FAILED"):
            return row
        time.sleep(POLL_INTERVAL_SEC)
    return frappe.db.get_value("Conductor Job", job_name, ["status", "attempt", "modified"], as_dict=True) or {}


def trigger_one(sjt: dict[str, Any]) -> dict[str, Any]:
    """Trigger a single Scheduled Job Type via Run Now."""
    method = sjt["method"]
    started = time.time()
    result: dict[str, Any] = {
        "id": sjt["name"],
        "method": method,
        "frequency": sjt["frequency"],
        "conductor_job_id": None,
        "status": None,
        "attempt": None,
        "duration_ms": None,
        "error": None,
        "notes": "",
    }
    try:
        # Path B: dispatch via the same code path the takeover loop uses.
        # We do NOT use sjt.enqueue(force=True) — that calls Frappe's `enqueue`
        # imported directly from frappe.utils.background_jobs, which goes to RQ
        # not Conductor regardless of the in-process patch. The takeover loop's
        # _fire_one dispatches via conductor.dispatcher.enqueue and updates
        # `last_execution`, exactly what we want for force-trigger.
        from conductor.frappe_scheduled_loop import _fire_one
        _fire_one(sjt["name"], frappe)
        frappe.db.commit()
    except Exception as exc:
        result["error"] = f"trigger raised: {exc!r}"
        return result

    job = _newest_conductor_job_for(method, since_unix=started)
    if not job:
        result["error"] = "no Conductor Job row created within trigger call"
        return result

    result["conductor_job_id"] = job["name"]
    final = _wait_for_terminal(job["name"])
    result["status"] = final.get("status")
    result["attempt"] = final.get("attempt")
    result["duration_ms"] = int((time.time() - started) * 1000)
    if result["status"] is None:
        result["error"] = f"poll timed out after {POLL_TIMEOUT_SEC}s"
    return result


def run_all() -> list[dict[str, Any]]:
    """Run every active Scheduled Job Type and write the result list."""
    rows = _list_scheduled_job_types()
    results = [trigger_one(row) for row in rows]
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(results, indent=2, default=str))
    return results
