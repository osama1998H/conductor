"""Job dispatcher: write Conductor Job row, XADD to Redis Stream, publish realtime."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import frappe

from conductor.client import get_redis
from conductor.config import load_config
from conductor.logging import get_logger
from conductor.messages import JobMessage, encode
from conductor.otel import get_tracer, inject_traceparent, setup_otel
from conductor.streams import CONSUMER_GROUP, ensure_consumer_group, stream_key

log = get_logger("conductor.dispatcher")

_PREVIEW_MAX = 4096


def _preview(value: Any) -> str:
    try:
        return json.dumps(value, default=str)[:_PREVIEW_MAX]
    except Exception:
        return repr(value)[:_PREVIEW_MAX]


def enqueue(method: str, *, queue: str = "default", timeout: int | None = None, **kwargs: Any) -> str:
    """Enqueue a job. Returns the new job_id (UUID str)."""
    setup_otel(service_name="conductor")
    tracer = get_tracer()

    site = frappe.local.site
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)

    queue_doc = frappe.get_cached_doc("Conductor Queue", queue)
    if not queue_doc.enabled:
        frappe.throw(f"Queue {queue!r} is disabled")

    timeout_seconds = int(timeout if timeout is not None else queue_doc.default_timeout)
    enqueued_at = datetime.now(timezone.utc)
    deadline = enqueued_at + timedelta(seconds=timeout_seconds)
    # Frappe/MySQL DATETIME columns don't accept timezone-aware datetimes;
    # store as naive UTC (the JobMessage keeps the tz-aware version for OTel).
    enqueued_at_naive = enqueued_at.replace(tzinfo=None)
    deadline_naive = deadline.replace(tzinfo=None)
    job_id = str(uuid.uuid4())

    with tracer.start_as_current_span("conductor.dispatch") as span:
        span.set_attribute("conductor.method", method)
        span.set_attribute("conductor.queue", queue)
        trace_parent = inject_traceparent()
        sc = span.get_span_context()
        trace_id_hex = format(sc.trace_id, "032x")
        span_id_hex = format(sc.span_id, "016x")

        msg = JobMessage(
            job_id=job_id,
            site=site,
            method=method,
            queue=queue,
            args=[],
            kwargs=kwargs,
            attempt=1,
            max_attempts=1,
            timeout_seconds=timeout_seconds,
            enqueued_at=enqueued_at,
            deadline=deadline,
            trace_parent=trace_parent,
            idempotency_key="",
            workflow_run_id="",
            step_id="",
        )
        encoded = encode(msg)

        # 1. Insert audit row first (status QUEUED).
        doc = frappe.get_doc(
            {
                "doctype": "Conductor Job",
                "job_id": job_id,
                "queue": queue,
                "method": method,
                "status": "QUEUED",
                "site": site,
                "args": encoded["args_b64"],
                "kwargs": encoded["kwargs_b64"],
                "args_preview": _preview([]),
                "kwargs_preview": _preview(kwargs),
                "attempt": 1,
                "max_attempts": 1,
                "timeout_seconds": timeout_seconds,
                "enqueued_at": enqueued_at_naive,
                "deadline": deadline_naive,
                "trace_id": trace_id_hex,
                "span_id": span_id_hex,
            }
        ).insert(ignore_permissions=True)
        frappe.db.commit()

        # 2. XADD to the stream. Lazy-create the consumer group on first XADD.
        skey = stream_key(site, queue)
        try:
            ensure_consumer_group(r, skey)
            redis_msg_id = r.xadd(skey, encoded, maxlen=cfg.stream_max_len, approximate=True)
        except Exception as e:
            doc.db_set("status", "DISPATCH_FAILED", commit=True)
            doc.db_set("last_error_type", type(e).__name__, commit=True)
            doc.db_set("last_error_message", str(e)[:140], commit=True)
            log.error("dispatch_failed", job_id=job_id, error=str(e))
            raise

        doc.db_set("redis_msg_id", redis_msg_id.decode() if isinstance(redis_msg_id, bytes) else str(redis_msg_id), commit=True)

        # 3. Realtime broadcast for live dashboards (Phase 3 will subscribe).
        frappe.publish_realtime(
            "conductor:job_queued", {"job_id": job_id, "queue": queue, "method": method}, after_commit=False
        )
        log.info("job_enqueued", job_id=job_id, queue=queue, method=method)

    return job_id
