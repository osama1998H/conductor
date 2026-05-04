"""Exercise every `bench conductor` subcommand and record observed output.

This is a fixture-driven harness: scenarios is a list of (label, args, expectation),
where args is appended to `bench --site frappe.localhost conductor`. expectation
is a dict with optional 'exit', 'stdout_contains', 'stderr_contains'.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

BENCH_DIR = "/Users/osamamuhammed/frappe_15"
SITE = "frappe.localhost"
OUTPUT = Path(
    "/Users/osamamuhammed/frappe_15/apps/conductor/"
    "docs/roadmap/v2-certification/cli.json"
)

SCENARIOS: list[dict[str, Any]] = [
    {
        "label": "doctor",
        "args": ["doctor"],
        "expect": {"exit": 0, "stdout_contains": ["OK"]},
    },
    {
        "label": "doctor --demo",
        "args": ["doctor", "--demo"],
        "expect": {"exit": 0, "stdout_contains": ["demo"]},
    },
    {
        "label": "depth",
        "args": ["depth"],
        "expect": {"exit": 0},
    },
    {
        "label": "schedule list",
        "args": ["schedule", "list"],
        "expect": {"exit": 0},
    },
    {
        "label": "dlq list",
        "args": ["dlq", "list"],
        "expect": {"exit": 0},
    },
    {
        "label": "workflow list",
        "args": ["workflow", "list"],
        "expect": {"exit": 0},
    },
    {
        "label": "migrate-from-rq dry-run",
        "args": ["migrate-from-rq", "--site", SITE],
        "expect": {"exit": 0, "stdout_contains": ["plan rows"]},
    },
    # `worker` and `scheduler` are long-lived; we skip them here — the live
    # processes from M1 already exercise both surfaces.
    # `cancel` and `schedule run-now` are exercised in scenario expansions
    # below using ids captured from the running site.
]


def _run(label: str, args: list[str]) -> dict[str, Any]:
    cmd = ["bench", "--site", SITE, "conductor", *args]
    proc = subprocess.run(
        cmd, cwd=BENCH_DIR, capture_output=True, text=True, timeout=120,
    )
    return {
        "label": label,
        "argv": cmd,
        "exit": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _evaluate(observed: dict[str, Any], expected: dict[str, Any]) -> tuple[bool, str]:
    if "exit" in expected and observed["exit"] != expected["exit"]:
        return False, f"exit {observed['exit']} != {expected['exit']}"
    for fragment in expected.get("stdout_contains", []):
        if fragment.lower() not in (observed["stdout"] or "").lower():
            return False, f"stdout missing {fragment!r}"
    for fragment in expected.get("stderr_contains", []):
        if fragment.lower() not in (observed["stderr"] or "").lower():
            return False, f"stderr missing {fragment!r}"
    return True, ""


import time as _time


def _connect_frappe():
    """Initialize a Frappe context for ORM access from inside cli_runner.

    cli_runner is run via `python -m tests.v2_certification.cli_runner` from
    the conductor app dir; we need to point it at the bench's sites/apps."""
    import os, sys
    os.chdir("/Users/osamamuhammed/frappe_15/sites")
    for p in (
        "/Users/osamamuhammed/frappe_15/sites",
        "/Users/osamamuhammed/frappe_15/apps/frappe",
        "/Users/osamamuhammed/frappe_15/apps/conductor",
    ):
        if p not in sys.path:
            sys.path.insert(0, p)
    import frappe
    frappe.init(site=SITE, sites_path="/Users/osamamuhammed/frappe_15/sites")
    frappe.connect()
    return frappe


def _scenario_cancel_live() -> dict[str, Any]:
    """Enqueue a long-running sleep job, run `bench conductor cancel <id>`,
    wait up to 10s for the job's status to flip to CANCELLED. The cap
    (max_concurrent etc.) does not matter here — we are exercising the
    CLI surface, not the worker."""
    label = "cancel"
    frappe = _connect_frappe()
    try:
        import conductor
        job_id = conductor.enqueue("conductor.demo.sleep", queue="default", seconds=30)
    finally:
        frappe.destroy()

    run = _run(label, ["cancel", job_id])

    # Wait briefly for the worker to observe cancellation. Don't hold a
    # frappe connection across the sleep loop — re-init each poll.
    final_status = None
    deadline = _time.time() + 10
    while _time.time() < deadline:
        frappe = _connect_frappe()
        try:
            frappe.db.rollback()
            final_status = frappe.db.get_value("Conductor Job", job_id, "status")
        finally:
            frappe.destroy()
        if final_status in ("CANCELLED", "TIMED_OUT", "SUCCEEDED", "FAILED"):
            break
        _time.sleep(0.5)

    ok = (run["exit"] == 0) and (final_status == "CANCELLED")
    why = ""
    if run["exit"] != 0:
        why = f"exit {run['exit']} != 0"
    elif final_status != "CANCELLED":
        why = f"final status {final_status!r} != 'CANCELLED'"
    run["pass"] = ok
    run["fail_reason"] = why
    run["final_status"] = final_status
    return run


SCHEDULE_RUN_NOW_NAME = "v2cert-schedule-run-now"


def _scenario_schedule_run_now_live() -> dict[str, Any]:
    """Insert a temp `Conductor Schedule` on conductor.demo.echo, run
    `bench conductor schedule run-now <name>`, assert a Conductor Job
    with that method appears within 10s. Idempotent: deletes the temp
    row at the end so re-runs work."""
    label = "schedule run-now"
    frappe = _connect_frappe()
    seed_failed = None
    try:
        if not frappe.db.exists("Conductor Schedule", SCHEDULE_RUN_NOW_NAME):
            try:
                frappe.get_doc({
                    "doctype": "Conductor Schedule",
                    "schedule_name": SCHEDULE_RUN_NOW_NAME,
                    "method": "conductor.demo.echo",
                    "queue": "default",
                    "cron_expression": "* * * * *",
                    "enabled": 1,
                }).insert(ignore_permissions=True)
                frappe.db.commit()
            except Exception as e:
                seed_failed = f"seed failed: {type(e).__name__}: {e}"
        # Capture creation cutoff so we only count jobs created by THIS run.
        from datetime import datetime, timezone
        cutoff_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    finally:
        frappe.destroy()

    if seed_failed:
        return {
            "label": label,
            "argv": ["bench", "--site", SITE, "conductor", "schedule", "run-now", SCHEDULE_RUN_NOW_NAME],
            "exit": -1, "stdout": "", "stderr": seed_failed,
            "pass": False, "fail_reason": seed_failed,
        }

    run = _run(label, ["schedule", "run-now", SCHEDULE_RUN_NOW_NAME])

    # Wait up to 10s for a fresh Conductor Job on conductor.demo.echo.
    found_job = None
    deadline = _time.time() + 10
    while _time.time() < deadline:
        frappe = _connect_frappe()
        try:
            frappe.db.rollback()
            rows = frappe.get_all(
                "Conductor Job",
                filters={
                    "method": "conductor.demo.echo",
                    "creation": [">=", cutoff_naive],
                },
                fields=["name", "status"],
                order_by="creation desc",
                limit=1,
            )
        finally:
            frappe.destroy()
        if rows:
            found_job = rows[0]
            break
        _time.sleep(0.5)

    # Teardown — delete the temp Schedule row whether or not the assertion passed.
    try:
        frappe = _connect_frappe()
        try:
            if frappe.db.exists("Conductor Schedule", SCHEDULE_RUN_NOW_NAME):
                frappe.delete_doc("Conductor Schedule", SCHEDULE_RUN_NOW_NAME, force=True)
                frappe.db.commit()
        finally:
            frappe.destroy()
    except Exception:
        pass  # Don't mask the scenario's own pass/fail with a teardown error.

    ok = (run["exit"] == 0) and (found_job is not None)
    why = ""
    if run["exit"] != 0:
        why = f"exit {run['exit']} != 0"
    elif found_job is None:
        why = "no Conductor Job appeared within 10s"
    run["pass"] = ok
    run["fail_reason"] = why
    run["found_job"] = found_job
    return run


def run_all() -> list[dict[str, Any]]:
    results = []
    for sc in SCENARIOS:
        run = _run(sc["label"], sc["args"])
        ok, why = _evaluate(run, sc["expect"])
        run["pass"] = ok
        run["fail_reason"] = why
        results.append(run)
    # Live-bench scenarios — Plan-2 / Task 9. These need real ORM seed +
    # assert and so cannot be expressed in the declarative SCENARIOS list.
    results.append(_scenario_cancel_live())
    results.append(_scenario_schedule_run_now_live())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(results, indent=2, default=str))
    return results


if __name__ == "__main__":
    import sys
    res = run_all()
    failed = [r for r in res if not r["pass"]]
    print(f"{len(res)} scenarios, {len(failed)} failed")
    sys.exit(1 if failed else 0)
