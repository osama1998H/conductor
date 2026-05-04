"""Orphan-row sweeper for the dispatch dual-write crash window (master §3 #12 option C).

Periodically queries Conductor Job for rows that:
  - status = QUEUED
  - redis_msg_id IS NULL
  - enqueued_at < now - 30s (longer than any normal commit-then-XADD round trip)

For each orphan, reconstruct a JobMessage from the row + queue defaults and
re-XADD. Update redis_msg_id; if XADD still fails, mark DISPATCH_FAILED.

NOTE: retry-policy fields are NOT stored on the Conductor Job row in v1, so
sweeper-recovered messages fall back to QUEUE defaults for backoff/jitter/etc.
For most workloads this is a graceful degradation; users with custom retry
policies are encouraged to keep dispatch reliable enough to never need the
sweeper (e.g., monitoring DISPATCH_FAILED rates).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import frappe
import redis as redis_mod

from conductor.logging import get_logger
from conductor.messages import JobMessage, encode
from conductor.streams import ensure_consumer_group, stream_key
from conductor.worker import now_naive

log = get_logger("conductor.sweeper")

DEFAULT_THRESHOLD_SECONDS = 30
SWEEP_BATCH = 100


def _row_to_jobmessage(row: dict, site: str, queue_doc: Any) -> JobMessage:
    """Reconstruct a JobMessage from the persisted Conductor Job row.
    Retry-policy fields fall back to queue defaults (see module docstring)."""
    return JobMessage(
        job_id=row["job_id"],
        site=site,
        method=row["method"],
        queue=row["queue"],
        args=[],
        kwargs={},
        attempt=int(row.get("attempt") or 1),
        max_attempts=int(row.get("max_attempts") or queue_doc.default_max_attempts or 3),
        timeout_seconds=int(row.get("timeout_seconds") or queue_doc.default_timeout or 300),
        enqueued_at=row["enqueued_at"].replace(tzinfo=timezone.utc) if row.get("enqueued_at") else datetime.now(timezone.utc),
        deadline=row["deadline"].replace(tzinfo=timezone.utc) if row.get("deadline") else None,
        idempotency_key=row.get("idempotency_key") or "",
        backoff=str(queue_doc.default_backoff or "exponential"),
        base_delay_seconds=int(queue_doc.default_base_delay_seconds or 2),
        max_delay_seconds=int(queue_doc.default_max_delay_seconds or 600),
        jitter=str(queue_doc.default_jitter or "full"),
    )


def sweep_orphans(
    redis_client: redis_mod.Redis,
    site: str,
    *,
    threshold_seconds: int = DEFAULT_THRESHOLD_SECONDS,
    batch: int = SWEEP_BATCH,
) -> int:
    """One-pass sweep. Returns the number of orphans recovered."""
    threshold = now_naive() - timedelta(seconds=threshold_seconds)
    rows = frappe.db.sql(
        """
        SELECT job_id, queue, method, status, site, attempt, max_attempts, timeout_seconds,
               enqueued_at, deadline, idempotency_key, args, kwargs
        FROM `tabConductor Job`
        WHERE status = 'QUEUED'
          AND (redis_msg_id IS NULL OR redis_msg_id = '')
          AND enqueued_at < %(threshold)s
        ORDER BY enqueued_at ASC
        LIMIT %(batch)s
        """,
        {"threshold": threshold, "batch": batch},
        as_dict=True,
    )

    recovered = 0
    for row in rows:
        try:
            queue_doc = frappe.get_cached_doc("Conductor Queue", row["queue"])
            msg = _row_to_jobmessage(row, site, queue_doc)
            encoded = encode(msg)
            encoded["args_b64"] = row.get("args") or ""
            encoded["kwargs_b64"] = row.get("kwargs") or ""

            target = stream_key(site, row["queue"])
            ensure_consumer_group(redis_client, target)
            try:
                msg_id = redis_client.xadd(target, encoded, maxlen=10000, approximate=True)
                msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
                frappe.db.set_value("Conductor Job", row["job_id"], "redis_msg_id", msg_id_str, update_modified=False)
                frappe.db.commit()
                recovered += 1
                log.info("sweeper_recovered_orphan", job_id=row["job_id"], queue=row["queue"])
            except Exception as e:
                frappe.db.set_value(
                    "Conductor Job", row["job_id"],
                    {"status": "DISPATCH_FAILED",
                     "last_error_type": type(e).__name__,
                     "last_error_message": f"sweeper re-XADD failed: {str(e)[:120]}"},
                    update_modified=False,
                )
                frappe.db.commit()
                log.error("sweeper_re_xadd_failed", job_id=row["job_id"], error=str(e))
        except Exception as e:
            log.error("sweeper_row_failed", job_id=row.get("job_id"), error=str(e))

    return recovered
