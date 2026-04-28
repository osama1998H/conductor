"""Public cancellation API. Cooperative model — see Phase 1 spec §12.3.

cancel(job_id):
  - terminal status → return False
  - QUEUED → status=CANCELLED, best-effort XDEL from queue stream
  - SCHEDULED_RETRY → status=CANCELLED, ZREM matching member from scheduled set
  - RUNNING → status=CANCELLED, the cancel-poller thread will flip the
    worker's cancel_event within 1s; user code observes via should_cancel()
"""

from __future__ import annotations

import json

import frappe

from conductor.client import get_redis
from conductor.config import load_config
from conductor.logging import get_logger
from conductor.messages import emit_job_event
from conductor.scheduled import scheduled_redis_key
from conductor.streams import stream_key

log = get_logger("conductor.cancellation")

_TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "DLQ", "CANCELLED", "DISPATCH_FAILED"}


@frappe.whitelist()
def cancel(job_id: str) -> bool:
    """Mark `job_id` as CANCELLED. Returns True iff the cancellation transitioned
    state; False if the job was already terminal or unknown."""
    if not frappe.db.exists("Conductor Job", job_id):
        return False
    current = frappe.db.get_value("Conductor Job", job_id, "status")
    if current in _TERMINAL_STATUSES:
        return False

    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    site = frappe.local.site

    frappe.db.set_value("Conductor Job", job_id, "status", "CANCELLED", update_modified=False)
    frappe.db.commit()

    if current == "QUEUED":
        msg_id = frappe.db.get_value("Conductor Job", job_id, "redis_msg_id")
        queue = frappe.db.get_value("Conductor Job", job_id, "queue")
        if msg_id and queue:
            try:
                r.xdel(stream_key(site, queue), msg_id)
            except Exception as e:
                log.warning("cancel_xdel_failed", job_id=job_id, error=str(e))

    elif current == "SCHEDULED_RETRY":
        skey = scheduled_redis_key(site)
        for member in r.zrange(skey, 0, -1):
            try:
                encoded = json.loads(member.decode("utf-8") if isinstance(member, bytes) else member)
                if encoded.get("job_id") == job_id:
                    r.zrem(skey, member)
                    break
            except Exception:
                continue

    emit_job_event(job_id, "CANCELLED")
    log.info("job_cancelled", job_id=job_id, prior_status=current)
    return True
