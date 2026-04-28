"""Dashboard whitelisted API surface — Phase 3.

Reference: docs/superpowers/specs/2026-04-28-conductor-phase3-dashboard-design.md §7.

Permission model (spec §6):
  - System Manager: full access.
  - Conductor Operator: read everything + safe-mutating actions
    (retry / cancel / schedule run-now).
  - Destructive actions (DLQ discard, edit-and-retry, schedule enable/disable)
    are System-Manager-only.

The server is the source of truth for permission enforcement. The frontend
hides destructive controls for non-SysMgr users as UX polish only.
"""

from __future__ import annotations

import time
from typing import Any

import frappe

from conductor.client import get_redis
from conductor.config import load_config
from conductor.streams import stream_key
from conductor.scheduled import scheduled_redis_key


def _require_read() -> None:
    if not (
        frappe.has_permission("Conductor Job", "read")
        or "Conductor Operator" in frappe.get_roles()
    ):
        raise frappe.PermissionError("Not permitted")


def _require_destructive() -> None:
    if "System Manager" not in frappe.get_roles():
        raise frappe.PermissionError("System Manager only")


def _redis_queue_depth(site: str, queue: str) -> int:
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    try:
        return int(r.xlen(stream_key(site, queue)))
    except Exception:
        return 0


def _redis_scheduled_count(site: str) -> int:
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    try:
        return int(r.zcard(scheduled_redis_key(site)))
    except Exception:
        return 0


def _poll_interval_ms() -> int:
    return int(
        (frappe.local.conf.get("conductor") or {}).get(
            "dashboard_poll_interval_ms", 2000
        )
    )


@frappe.whitelist()
def get_state() -> dict[str, Any]:
    _require_read()
    site = frappe.local.site

    queues = []
    for q in frappe.get_all("Conductor Queue", fields=["name", "enabled"]):
        depth = _redis_queue_depth(site, q.name)
        dlq_count = frappe.db.count("Conductor DLQ Entry",
                                    {"queue": q.name, "status": "PENDING_REVIEW"})
        queues.append({
            "name": q.name,
            "enabled": bool(q.enabled),
            "depth_redis": depth,
            "scheduled_count": 0,
            "dlq_count": dlq_count,
            "throughput_1h": 0,
            "error_rate_1h": 0.0,
        })

    worker_summary = {
        "alive": frappe.db.count("Conductor Worker", {"status": "ALIVE"}),
        "stale": frappe.db.count("Conductor Worker", {"status": "STALE"}),
        "gone": frappe.db.count("Conductor Worker", {"status": "GONE"}),
        "total": frappe.db.count("Conductor Worker"),
    }

    dlq_summary = {
        "pending_review": frappe.db.count("Conductor DLQ Entry", {"status": "PENDING_REVIEW"}),
        "retried": frappe.db.count("Conductor DLQ Entry", {"status": "RETRIED"}),
        "discarded": frappe.db.count("Conductor DLQ Entry", {"status": "DISCARDED"}),
    }

    schedule_summary = {
        "enabled_count": frappe.db.count("Conductor Schedule", {"enabled": 1}),
        "next_5": frappe.get_all(
            "Conductor Schedule",
            filters={"enabled": 1},
            fields=["name", "cron_expression", "next_run_at"],
            order_by="next_run_at asc",
            limit=5,
        ),
    }

    feed_recent = frappe.get_all(
        "Conductor Job",
        fields=["job_id", "method", "queue", "status", "attempt", "enqueued_at"],
        order_by="enqueued_at desc",
        limit=50,
    )

    return {
        "queues": queues,
        "worker_summary": worker_summary,
        "dlq_summary": dlq_summary,
        "schedule_summary": schedule_summary,
        "feed_recent": feed_recent,
        "config": {"poll_interval_ms": _poll_interval_ms()},
        "ts": int(time.time()),
    }
