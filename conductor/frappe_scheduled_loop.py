"""Daemon loop that takes over Frappe's `tabScheduled Job Type` source.

Reads `tabScheduled Job Type` rows once per tick, asks each non-stopped row's
`is_event_due()` method (Frappe's own logic — we do not reimplement it), and
dispatches each due row through `conductor.dispatcher.enqueue`. After a
successful dispatch we update `last_execution` so Frappe's logic does not
re-trigger on the next tick.

Activation: gated by `conductor_take_over_frappe_scheduler` in
`common_site_config.json`. Default is `False` — when unset, the loop runs
but exits early on every tick. Zero behavior change for users who haven't
opted in.

Pairing: when this loop is active, the user MUST pause Frappe's own
scheduler (via `pause_scheduler: true` site flag, or by removing the
`schedule:` line from the bench Procfile). Otherwise the same row fires
twice per cron event. The M8 doctor health-gate asserts this constraint.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from conductor.dispatcher import enqueue as conductor_enqueue
from conductor.logging import get_logger
from conductor.worker import now_naive

log = get_logger("conductor.frappe_scheduled_loop")

FRAPPE_SCHEDULED_LOOP_INTERVAL_SECONDS = 60.0

ACTIVATION_FLAG = "conductor_take_over_frappe_scheduler"
QUEUE_MAP_KEY = "conductor_frappe_schedule_queue_map"

DEFAULT_QUEUE_MAP: dict[str, str] = {
    "All": "default",
    "Cron": "default",
    "Hourly": "default",
    "Hourly Long": "default",
    "Hourly Maintenance": "default",
    "Daily": "long",
    "Daily Long": "long",
    "Daily Maintenance": "long",
    "Weekly": "long",
    "Weekly Long": "long",
    "Monthly": "long",
    "Monthly Long": "long",
}


def _resolve_queue(frequency: str, conf_map: dict[str, str] | None) -> str:
    """Map a Frappe frequency name to a Conductor queue.

    A site-config override (`conductor_frappe_schedule_queue_map`) wins per-key
    over the default map. Unknown frequencies fall back to `default`.
    """
    merged = dict(DEFAULT_QUEUE_MAP)
    if conf_map:
        merged.update(conf_map)
    return merged.get(frequency, "default")


def _is_takeover_enabled(frappe) -> bool:
    """True when the bench-wide takeover flag is set right now."""
    try:
        conf = getattr(frappe, "conf", None) or {}
        return bool(conf.get(ACTIVATION_FLAG, False))
    except Exception:
        return False


def _fire_one(name: str, frappe) -> None:
    """Fire a single Scheduled Job Type row through conductor.

    On dispatch success, mutates `last_execution` so Frappe's `is_event_due()`
    does not re-trigger on the next tick. On failure, leaves `last_execution`
    unchanged so the loop retries on the next tick — and logs the failure so
    operators can see persistent dispatch errors.
    """
    doc = frappe.get_doc("Scheduled Job Type", name)
    queue = _resolve_queue(
        doc.frequency,
        getattr(frappe, "conf", None) and frappe.conf.get(QUEUE_MAP_KEY) or {},
    )
    try:
        conductor_enqueue(doc.method, queue=queue, max_attempts=1)
    except Exception as e:
        log.error(
            "frappe_scheduled_dispatch_failed",
            scheduled_job=name, method=doc.method, error=str(e),
        )
        return

    doc.db_set("last_execution", now_naive(), update_modified=False)


def _frappe_scheduled_loop_iter(frappe) -> int:
    """One pass: enumerate active Scheduled Job Types, fire those due. Returns fired count.

    Returns 0 immediately when the activation flag is unset — keeping the loop
    a no-op for users who haven't opted in.
    """
    if not _is_takeover_enabled(frappe):
        return 0

    rows = frappe.get_all(
        "Scheduled Job Type",
        fields=["name"],
        filters={"stopped": 0},
        order_by="method",
    )
    fired = 0
    for r in rows:
        try:
            doc = frappe.get_doc("Scheduled Job Type", r["name"])
            if not doc.is_event_due():
                continue
            _fire_one(r["name"], frappe)
            fired += 1
        except Exception as e:
            log.error(
                "frappe_scheduled_iter_row_failed",
                scheduled_job=r.get("name"), error=str(e),
            )
    return fired


def _frappe_scheduled_loop(
    stop_event: threading.Event,
    lost_lock_event: threading.Event,
    site: str,
    sites_path: str | None,
) -> None:
    log.info("frappe_scheduled_loop_started", site=site)
    import frappe
    while not (stop_event.is_set() or lost_lock_event.is_set()):
        try:
            frappe.init(site=site, sites_path=sites_path)
            frappe.connect()
            try:
                fired = _frappe_scheduled_loop_iter(frappe)
                if fired:
                    log.info("frappe_scheduled_loop_fired", site=site, count=fired)
                frappe.db.commit()
            finally:
                frappe.destroy()
        except Exception as e:
            log.error("frappe_scheduled_loop_iteration_failed", error=str(e))
        stop_event.wait(FRAPPE_SCHEDULED_LOOP_INTERVAL_SECONDS)
    log.info("frappe_scheduled_loop_stopped", site=site)
