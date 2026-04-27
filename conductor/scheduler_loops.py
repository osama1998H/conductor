"""Aggregator for the four scheduler loops.

Each loop is a daemon thread that catches per-iteration exceptions and logs
them, so a transient DB or Redis failure never kills the scheduler. Each
iteration opens its own frappe.init/connect → … → frappe.db.commit() →
frappe.destroy() cycle (the Werkzeug-Local rule from Phase 1 hand-off §5).
"""

from __future__ import annotations

import base64
import threading
from datetime import datetime, timezone
from typing import Any

import redis as redis_mod

try:
    import frappe
except ImportError:  # pragma: no cover — only missing in pure-unit-test env
    frappe = None  # type: ignore[assignment]

from conductor.cron import compute_next_run_at
from conductor.dispatcher import enqueue as conductor_enqueue
from conductor.logging import get_logger
from conductor.scheduled import drain_due_messages
from conductor.serialization import loads as msgpack_loads
from conductor.streams import ensure_consumer_group, stream_key

log = get_logger("conductor.scheduler_loops")

CRON_LOOP_INTERVAL_SECONDS = 1.0
DELAY_LOOP_INTERVAL_SECONDS = 1.0


def _decode_kwargs(kwargs_b64: str) -> dict[str, Any]:
    """Reverse the schedule's stored kwargs (msgpack→base64). Empty → {}."""
    if not kwargs_b64:
        return {}
    return msgpack_loads(base64.b64decode(kwargs_b64.encode("ascii")))


def _fire_schedule_once(name: str, now_utc: datetime, frappe) -> None:
    """Fire one schedule: enqueue, update last_status/last_job/last_run_at,
    recompute next_run_at. Catches enqueue failures and records DISPATCH_FAILED."""
    doc = frappe.get_doc("Conductor Schedule", name)
    try:
        kwargs = _decode_kwargs(doc.kwargs) if doc.kwargs else {}
        max_attempts = doc.max_attempts or None
        job_id = conductor_enqueue(
            doc.method, queue=doc.queue, max_attempts=max_attempts, **kwargs,
        )
        doc.db_set("last_status", "DISPATCHED", update_modified=False)
        doc.db_set("last_job", job_id, update_modified=False)
    except Exception as e:
        doc.db_set("last_status", "DISPATCH_FAILED", update_modified=False)
        log.error("cron_fire_failed", schedule=name, error=str(e))

    doc.db_set("last_run_at", now_utc.replace(tzinfo=None), update_modified=False)

    # Recompute next_run_at from the just-fired moment so consecutive loops
    # don't pick the same row again.
    try:
        next_at = compute_next_run_at(doc.cron_expression, doc.timezone or "UTC", base=now_utc)
        doc.db_set("next_run_at", next_at.replace(tzinfo=None), update_modified=False)
    except Exception as e:
        log.error("cron_recompute_failed", schedule=name, error=str(e))


def _cron_loop_iter(now_utc: datetime, frappe) -> None:
    """One pass: SELECT due rows, fire each."""
    rows = frappe.db.sql(
        "SELECT name FROM `tabConductor Schedule` "
        "WHERE enabled=1 AND next_run_at IS NOT NULL AND next_run_at <= %s",
        (now_utc.replace(tzinfo=None),),
        as_dict=True,
    )
    for r in rows:
        try:
            _fire_schedule_once(r["name"], now_utc, frappe)
        except Exception as e:
            log.error("cron_fire_outer_failed", schedule=r["name"], error=str(e))


def _cron_loop(stop_event: threading.Event, lost_lock_event: threading.Event,
               site: str, sites_path: str | None) -> None:
    log.info("cron_loop_started", site=site)
    import frappe
    while not (stop_event.is_set() or lost_lock_event.is_set()):
        try:
            frappe.init(site=site, sites_path=sites_path)
            frappe.connect()
            try:
                now = datetime.now(timezone.utc)
                _cron_loop_iter(now, frappe)
                frappe.db.commit()
            finally:
                frappe.destroy()
        except Exception as e:
            log.error("cron_loop_iteration_failed", error=str(e))
        stop_event.wait(CRON_LOOP_INTERVAL_SECONDS)
    log.info("cron_loop_stopped", site=site)


# --- delay --------------------------------------------------------------------


def _delay_loop_iter(redis_client: redis_mod.Redis, site: str) -> int:
    """Drain due ZSET messages → XADD their target streams. Returns drained count."""
    due = drain_due_messages(redis_client, site)
    drained = 0
    for encoded in due:
        queue = encoded.get("queue") or ""
        if not queue:
            log.warning("delay_loop_skipped_empty_queue", encoded=encoded)
            continue
        target = stream_key(site, queue)
        ensure_consumer_group(redis_client, target)
        redis_client.xadd(target, encoded, maxlen=10000, approximate=True)
        drained += 1
    return drained


def _delay_loop(redis_client: redis_mod.Redis, site: str,
                stop_event: threading.Event, lost_lock_event: threading.Event) -> None:
    log.info("delay_loop_started", site=site)
    while not (stop_event.is_set() or lost_lock_event.is_set()):
        try:
            _delay_loop_iter(redis_client, site)
        except Exception as e:
            log.error("delay_loop_iteration_failed", error=str(e))
        stop_event.wait(DELAY_LOOP_INTERVAL_SECONDS)
    log.info("delay_loop_stopped", site=site)


def start_all_loops(
    *,
    redis_client: redis_mod.Redis,
    site: str,
    sites_path: str | None,
    stop_event: threading.Event,
    lost_lock_event: threading.Event,
) -> list[threading.Thread]:
    threads: list[threading.Thread] = []
    threads.append(threading.Thread(
        target=_cron_loop,
        args=(stop_event, lost_lock_event, site, sites_path),
        daemon=True, name="conductor-scheduler-cron",
    ))
    threads.append(threading.Thread(
        target=_delay_loop,
        args=(redis_client, site, stop_event, lost_lock_event),
        daemon=True, name="conductor-scheduler-delay",
    ))
    # Tasks 8, 9 will append reaper, sweeper here.
    for t in threads:
        t.start()
    return threads
