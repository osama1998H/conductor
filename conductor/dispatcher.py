"""Job dispatcher: write Conductor Job row, XADD to Redis Stream, publish realtime.

Phase 1 additions: idempotency check, decorator-driven policy resolution
(per-call > decorator > queue defaults), single-transaction DISPATCH_FAILED
branch (M-2 fix).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import frappe

from conductor.client import get_redis
from conductor.config import load_config
from conductor.decorator import JobMetadata, get_metadata
from conductor.idempotency import acquire_idem_lock
from conductor.logging import get_logger
from conductor.messages import JobMessage, encode
from conductor.otel import get_tracer, inject_traceparent, setup_otel
from conductor.retry import RetryPolicy
from conductor.streams import ensure_consumer_group, stream_key

log = get_logger("conductor.dispatcher")

_PREVIEW_MAX = 4096
_DEFAULT_IDEM_TTL_SECONDS = 86_400  # 24h


def _preview(value: Any) -> str:
    try:
        return json.dumps(value, default=str)[:_PREVIEW_MAX]
    except Exception:
        return repr(value)[:_PREVIEW_MAX]


def _exception_class_path(cls: type[BaseException]) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _resolve_dispatch_config(
    method: str,
    *,
    per_call_queue: Optional[str],
    per_call_timeout: Optional[int],
    per_call_max_attempts: Optional[int],
    per_call_idempotency_key: Optional[str],
    kwargs: dict[str, Any],
) -> tuple[str, int, RetryPolicy, str, Optional[JobMetadata]]:
    """Resolve queue, timeout, RetryPolicy, idempotency_key per the precedence:
    per-call kwargs > decorator metadata > queue defaults."""
    meta: Optional[JobMetadata] = None
    try:
        func = frappe.get_attr(method)
        meta = get_metadata(func)
    except Exception:
        pass

    queue = per_call_queue or (meta.queue if meta and meta.queue else "default")
    queue_doc = frappe.get_cached_doc("Conductor Queue", queue)
    if not queue_doc.enabled:
        frappe.throw(f"Queue {queue!r} is disabled")

    timeout = per_call_timeout if per_call_timeout is not None else (
        meta.timeout if meta and meta.timeout is not None else int(queue_doc.default_timeout)
    )

    if meta is not None:
        policy = meta.policy
    else:
        policy = RetryPolicy(
            max_attempts=int(queue_doc.default_max_attempts or 3),
            backoff=str(queue_doc.default_backoff or "exponential"),
            base_delay_seconds=int(queue_doc.default_base_delay_seconds or 2),
            max_delay_seconds=int(queue_doc.default_max_delay_seconds or 600),
            jitter=str(queue_doc.default_jitter or "full"),
        )
    if per_call_max_attempts is not None:
        policy = RetryPolicy(
            max_attempts=per_call_max_attempts,
            backoff=policy.backoff,
            base_delay_seconds=policy.base_delay_seconds,
            max_delay_seconds=policy.max_delay_seconds,
            jitter=policy.jitter,
            retry_on=policy.retry_on,
            no_retry_on=policy.no_retry_on,
        )

    idem_key = per_call_idempotency_key or ""
    if not idem_key and meta and meta.idempotency_key_fn is not None:
        try:
            idem_key = meta.idempotency_key_fn(**kwargs) or ""
        except Exception as e:
            log.warning("idempotency_key_fn_failed", method=method, error=str(e))
            idem_key = ""

    return queue, timeout, policy, idem_key, meta


def enqueue(
    method: str,
    *,
    queue: Optional[str] = None,
    timeout: Optional[int] = None,
    max_attempts: Optional[int] = None,
    idempotency_key: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """Enqueue a job. Returns the new job_id (UUID str), or the existing job_id
    if the idempotency_key already mapped to an in-flight or recently-dispatched job."""
    setup_otel(service_name="conductor")
    tracer = get_tracer()

    site = frappe.local.site
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)

    resolved_queue, timeout_seconds, policy, idem_key, _meta = _resolve_dispatch_config(
        method,
        per_call_queue=queue,
        per_call_timeout=timeout,
        per_call_max_attempts=max_attempts,
        per_call_idempotency_key=idempotency_key,
        kwargs=kwargs,
    )

    enqueued_at = datetime.now(timezone.utc)
    deadline = enqueued_at + timedelta(seconds=timeout_seconds)
    job_id = str(uuid.uuid4())

    idem_ttl = int(
        (frappe.local.conf.get("conductor") or {}).get(
            "idempotency_ttl_seconds", _DEFAULT_IDEM_TTL_SECONDS
        )
    )
    existing = acquire_idem_lock(r, site, idem_key, job_id, ttl=idem_ttl)
    if existing is not None:
        log.info("dispatch_idempotency_hit", method=method, idem_key=idem_key, existing_job_id=existing)
        return existing

    with tracer.start_as_current_span("conductor.dispatch") as span:
        span.set_attribute("conductor.method", method)
        span.set_attribute("conductor.queue", resolved_queue)
        trace_parent = inject_traceparent()
        sc = span.get_span_context()
        trace_id_hex = format(sc.trace_id, "032x")
        span_id_hex = format(sc.span_id, "016x")

        msg = JobMessage(
            job_id=job_id,
            site=site,
            method=method,
            queue=resolved_queue,
            args=[],
            kwargs=kwargs,
            attempt=1,
            max_attempts=policy.max_attempts,
            timeout_seconds=timeout_seconds,
            enqueued_at=enqueued_at,
            deadline=deadline,
            trace_parent=trace_parent,
            idempotency_key=idem_key,
            workflow_run_id="",
            step_id="",
            backoff=policy.backoff,
            base_delay_seconds=policy.base_delay_seconds,
            max_delay_seconds=policy.max_delay_seconds,
            jitter=policy.jitter,
            retry_on_names=[_exception_class_path(c) for c in policy.retry_on],
            no_retry_on_names=[_exception_class_path(c) for c in policy.no_retry_on],
        )
        encoded = encode(msg)

        doc = frappe.get_doc({
            "doctype": "Conductor Job",
            "job_id": job_id,
            "queue": resolved_queue,
            "method": method,
            "status": "QUEUED",
            "site": site,
            "args": encoded["args_b64"],
            "kwargs": encoded["kwargs_b64"],
            "args_preview": _preview([]),
            "kwargs_preview": _preview(kwargs),
            "attempt": 1,
            "max_attempts": policy.max_attempts,
            "timeout_seconds": timeout_seconds,
            "enqueued_at": enqueued_at.replace(tzinfo=None),
            "deadline": deadline.replace(tzinfo=None),
            "idempotency_key": idem_key,
            "trace_id": trace_id_hex,
            "span_id": span_id_hex,
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        skey = stream_key(site, resolved_queue)
        try:
            ensure_consumer_group(r, skey)
            redis_msg_id = r.xadd(skey, encoded, maxlen=cfg.stream_max_len, approximate=True)
        except Exception as e:
            # M-2: single transaction for the failure update.
            frappe.db.set_value(
                "Conductor Job",
                doc.name,
                {
                    "status": "DISPATCH_FAILED",
                    "last_error_type": type(e).__name__,
                    "last_error_message": str(e)[:140],
                },
                update_modified=False,
            )
            frappe.db.commit()
            log.error("dispatch_failed", job_id=job_id, error=str(e))
            raise

        msg_id_str = redis_msg_id.decode() if isinstance(redis_msg_id, bytes) else str(redis_msg_id)
        frappe.db.set_value("Conductor Job", doc.name, "redis_msg_id", msg_id_str, update_modified=False)
        frappe.db.commit()

        frappe.publish_realtime(
            "conductor:job_queued",
            {"job_id": job_id, "queue": resolved_queue, "method": method},
            after_commit=False,
        )
        log.info("job_enqueued", job_id=job_id, queue=resolved_queue, method=method)

    return job_id
