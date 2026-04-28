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

import json as _json

from conductor.api.json_safety import is_json_safe
from conductor.client import get_redis
from conductor.config import load_config
from conductor.streams import stream_key
from conductor.scheduled import scheduled_redis_key
from conductor import cancellation as _cancellation
from conductor.serialization import loads as _msgpack_loads


def _require_read() -> None:
    if not (
        frappe.has_permission("Conductor Job", "read")
        or "Conductor Operator" in frappe.get_roles()
    ):
        raise frappe.PermissionError("Not permitted")


def _require_destructive() -> None:
    if "System Manager" not in frappe.get_roles():
        raise frappe.PermissionError("System Manager only")


@frappe.whitelist()
def get_user_roles() -> dict[str, Any]:
    """User identity + roles for the logged-in user. The dashboard SPA uses
    this to gate destructive UI buttons. The www/ route doesn't expose
    Frappe's bootinfo, so the SPA can't read window.frappe.boot directly.

    Returned shape: {"user": "<email-or-Administrator>", "roles": [...]}.
    The literal "Administrator" user is treated as full-access by the SPA.
    """
    _require_read()
    return {"user": frappe.session.user, "roles": frappe.get_roles()}


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


def _decode_b64_msgpack(b64: str) -> Any:
    if not b64:
        return None
    import base64
    return _msgpack_loads(base64.b64decode(b64.encode("ascii")))


@frappe.whitelist()
def get_job(job_id: str) -> dict[str, Any]:
    _require_read()
    if not frappe.db.exists("Conductor Job", job_id):
        raise frappe.DoesNotExistError("Job not found")

    job = frappe.get_doc("Conductor Job", job_id).as_dict()
    job["args_decoded"] = _decode_b64_msgpack(job.get("args"))
    job["kwargs_decoded"] = _decode_b64_msgpack(job.get("kwargs"))
    job["runs"] = frappe.get_all(
        "Conductor Job Run",
        filters={"job": job_id},
        fields=["attempt_number", "worker_id", "started_at", "finished_at",
                "duration_ms", "status", "error_type", "error_message",
                "traceback"],
        order_by="attempt_number asc",
    )
    return job


def _enqueue_for_retry(method: str, **kwargs):
    """Indirection so tests can monkeypatch."""
    from conductor.dispatcher import enqueue
    return enqueue(method, **kwargs)


@frappe.whitelist()
def retry_job(job_id: str) -> str:
    _require_read()
    if not (frappe.has_permission("Conductor Job", "write")
            or "Conductor Operator" in frappe.get_roles()):
        raise frappe.PermissionError("Not permitted")
    if not frappe.db.exists("Conductor Job", job_id):
        raise frappe.DoesNotExistError("Job not found")

    job = frappe.get_doc("Conductor Job", job_id)
    job_kwargs = _decode_b64_msgpack(job.kwargs) or {}
    return _enqueue_for_retry(job.method, queue=job.queue, **job_kwargs)


@frappe.whitelist()
def cancel_job(job_id: str) -> bool:
    _require_read()
    if not (frappe.has_permission("Conductor Job", "write")
            or "Conductor Operator" in frappe.get_roles()):
        raise frappe.PermissionError("Not permitted")
    return _cancellation.cancel(job_id)


def _dlq_payload_decoded(payload_str: str) -> dict[str, Any]:
    """Decode the JSON-stringified stream payload stored in the DLQ row."""
    raw = _json.loads(payload_str or "{}")
    args = _decode_b64_msgpack(raw.get("args_b64", "")) or []
    kwargs = _decode_b64_msgpack(raw.get("kwargs_b64", "")) or {}
    return {
        "args": args,
        "kwargs": kwargs,
        "method": raw.get("name") or raw.get("method"),
        "queue": raw.get("queue", "default"),
    }


@frappe.whitelist()
def get_dlq_entry(name: str) -> dict[str, Any]:
    _require_read()
    if not frappe.db.exists("Conductor DLQ Entry", name):
        raise frappe.DoesNotExistError("DLQ entry not found")
    entry = frappe.get_doc("Conductor DLQ Entry", name).as_dict()
    decoded = _dlq_payload_decoded(entry.get("payload", ""))
    entry["payload_decoded"] = decoded
    entry["is_json_safe"] = is_json_safe(decoded["args"]) and is_json_safe(decoded["kwargs"])
    return entry


@frappe.whitelist()
def dlq_retry(entry_names: list[str] | str) -> dict[str, Any]:
    _require_read()
    if not (frappe.has_permission("Conductor DLQ Entry", "write")
            or "Conductor Operator" in frappe.get_roles()):
        raise frappe.PermissionError("Not permitted")

    if isinstance(entry_names, str):
        entry_names = _json.loads(entry_names)

    retried = 0
    for name in entry_names:
        entry = frappe.get_doc("Conductor DLQ Entry", name)
        decoded = _dlq_payload_decoded(entry.payload)
        _enqueue_for_retry(
            decoded["method"],
            queue=decoded["queue"],
            **decoded["kwargs"],
        )
        frappe.db.set_value("Conductor DLQ Entry", name, {
            "status": "RETRIED",
            "reviewed_by": frappe.session.user,
            "reviewed_at": frappe.utils.now_datetime(),
        })
        retried += 1

    frappe.db.commit()
    return {"retried": retried}


@frappe.whitelist()
def dlq_discard(entry_names: list[str] | str) -> dict[str, Any]:
    _require_destructive()
    if isinstance(entry_names, str):
        entry_names = _json.loads(entry_names)
    discarded = 0
    for name in entry_names:
        frappe.db.set_value("Conductor DLQ Entry", name, {
            "status": "DISCARDED",
            "reviewed_by": frappe.session.user,
            "reviewed_at": frappe.utils.now_datetime(),
        })
        discarded += 1
    frappe.db.commit()
    return {"discarded": discarded}


@frappe.whitelist()
def dlq_edit_and_retry(name: str, args_json: str, kwargs_json: str) -> str:
    _require_destructive()
    entry = frappe.get_doc("Conductor DLQ Entry", name)
    decoded = _dlq_payload_decoded(entry.payload)
    if not (is_json_safe(decoded["args"]) and is_json_safe(decoded["kwargs"])):
        raise frappe.ValidationError(
            "Original payload contains non-JSON-native types; "
            "edit-and-retry not available."
        )

    new_args = _json.loads(args_json)
    new_kwargs = _json.loads(kwargs_json)
    if not (is_json_safe(new_args) and is_json_safe(new_kwargs)):
        raise frappe.ValidationError("Edited payload contains non-JSON-native types")

    new_id = _enqueue_for_retry(
        decoded["method"],
        queue=decoded["queue"],
        **new_kwargs,
    )
    frappe.db.set_value("Conductor DLQ Entry", name, {
        "status": "RETRIED",
        "reviewed_by": frappe.session.user,
        "reviewed_at": frappe.utils.now_datetime(),
    })
    frappe.db.commit()
    return new_id


# ---------------------------------------------------------------------------
# Schedule endpoints
# ---------------------------------------------------------------------------

from croniter import croniter  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore


@frappe.whitelist()
def schedule_run_now(name: str) -> str:
    _require_read()
    if not (frappe.has_permission("Conductor Schedule", "write")
            or "Conductor Operator" in frappe.get_roles()):
        raise frappe.PermissionError("Not permitted")
    sch = frappe.get_doc("Conductor Schedule", name)
    kwargs = _decode_b64_msgpack(sch.kwargs) or {}
    return _enqueue_for_retry(sch.method, queue=sch.queue, **kwargs)


@frappe.whitelist()
def schedule_set_enabled(name: str, enabled: bool) -> None:
    _require_destructive()
    enabled_int = 1 if (enabled is True or str(enabled).lower() in {"1", "true"}) else 0
    frappe.db.set_value("Conductor Schedule", name, "enabled", enabled_int)
    frappe.db.commit()


@frappe.whitelist()
def get_schedule_next_fires(name: str, count: int = 10) -> list[str]:
    _require_read()
    sch = frappe.db.get_value(
        "Conductor Schedule", name,
        ["cron_expression", "timezone"], as_dict=True,
    )
    if not sch:
        raise frappe.DoesNotExistError("Schedule not found")

    tz_name = sch.timezone or "UTC"
    if ZoneInfo:
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")
    else:
        tz = timezone.utc

    base = datetime.now(tz)
    it = croniter(sch.cron_expression, base)
    return [it.get_next(datetime).isoformat() for _ in range(int(count))]


# ---------------------------------------------------------------------------
# Worker endpoint
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_worker(worker_id: str) -> dict[str, Any]:
    _require_read()
    if not frappe.db.exists("Conductor Worker", worker_id):
        raise frappe.DoesNotExistError("Worker not found")

    worker = frappe.get_doc("Conductor Worker", worker_id).as_dict()
    last_hb = worker.get("last_heartbeat")
    if last_hb:
        delta = (frappe.utils.now_datetime() - last_hb).total_seconds()
        worker["heartbeat_age_seconds"] = max(0, int(delta))
    else:
        worker["heartbeat_age_seconds"] = None

    worker["recent_jobs"] = frappe.get_all(
        "Conductor Job",
        filters={"worker_id": worker_id},
        fields=["job_id", "method", "queue", "status", "finished_at"],
        order_by="finished_at desc",
        limit=20,
    )
    return worker
