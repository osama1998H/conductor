"""Conductor worker loop: XREADGROUP → execute → status update → XACK.

Phase 1 additions:
- Acquire/release execution lock around job execution.
- On retryable failure: ZADD to scheduled set, status=SCHEDULED_RETRY.
- On exhausted retries: XADD to DLQ stream + Conductor DLQ Entry row, status=DLQ.
- Per-attempt Conductor Job Run row at terminal of each attempt.
- XAUTOCLAIM stalled-message reclamation per iteration (idle ≥ 60s).
- Spawn DelayDrainer thread (Phase 2 lifts to scheduler process).
"""

from __future__ import annotations

import importlib
import json
import os
import signal
import socket
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import frappe
import redis as redis_mod

from conductor.client import get_redis
from conductor.config import load_config
from conductor.context import set_context, start_watchdog
from conductor.execution_lock import acquire_exec_lock, release_exec_lock
from conductor.logging import get_logger, setup_logging
from conductor.messages import JobMessage, decode, encode
from conductor.otel import setup_otel
from conductor.retry import RetryPolicy
from conductor.scheduled import DelayDrainer, schedule_message
from conductor.sweeper import OrphanSweeper
from conductor.streams import CONSUMER_GROUP, dlq_key, ensure_consumer_group, stream_key

log = get_logger("conductor.worker")

_HEARTBEAT_SECS = 5
_PREVIEW_MAX = 4096
_AUTOCLAIM_IDLE_MS = int(os.environ.get("CONDUCTOR_TEST_AUTOCLAIM_IDLE_MS", "60000"))
_RECLAIM_BATCH = 32


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_naive() -> datetime:
    """MariaDB DATETIME doesn't accept tz-aware strings."""
    return _now().replace(tzinfo=None)


def _preview(value) -> str:
    try:
        return json.dumps(value, default=str)[:_PREVIEW_MAX]
    except Exception:
        return repr(value)[:_PREVIEW_MAX]


def _make_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _register_worker(worker_id: str, queues: list[str], site: str) -> None:
    if frappe.db.exists("Conductor Worker", worker_id):
        return
    frappe.get_doc({
        "doctype": "Conductor Worker",
        "worker_id": worker_id,
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "queues": json.dumps(queues),
        "site": site,
        "status": "ALIVE",
        "started_at": _now_naive(),
        "last_heartbeat": _now_naive(),
    }).insert(ignore_permissions=True)
    frappe.db.commit()


def _heartbeat(worker_id: str) -> None:
    frappe.db.set_value("Conductor Worker", worker_id, "last_heartbeat", _now_naive(), update_modified=False)
    frappe.db.commit()


def _mark_worker_gone(worker_id: str) -> None:
    if frappe.db.exists("Conductor Worker", worker_id):
        frappe.db.set_value("Conductor Worker", worker_id, "status", "GONE", update_modified=False)
        frappe.db.commit()


def _set_job_running(job_id: str, worker_id: str) -> None:
    frappe.db.set_value(
        "Conductor Job",
        job_id,
        {"status": "RUNNING", "started_at": _now_naive(), "worker_id": worker_id},
        update_modified=False,
    )
    frappe.db.commit()


def _set_job_succeeded(job_id: str, result) -> None:
    frappe.db.set_value(
        "Conductor Job",
        job_id,
        {"status": "SUCCEEDED", "finished_at": _now_naive(), "result_preview": _preview(result)},
        update_modified=False,
    )
    frappe.db.commit()


def _resolve_policy_from_msg(msg: JobMessage) -> RetryPolicy:
    """Reconstruct a RetryPolicy from JobMessage stamped fields, importing
    exception classes by fully-qualified name. Import failures fall back to
    Exception for retry_on (conservative-DLQ rather than retry-on-wrong-class)
    and the empty tuple for no_retry_on."""
    def _import_classes(names: list[str]) -> tuple[type[BaseException], ...]:
        out = []
        for n in names:
            try:
                module_name, _, qualname = n.rpartition(".")
                if not module_name:
                    continue
                mod = importlib.import_module(module_name)
                cls = getattr(mod, qualname, None)
                if cls and isinstance(cls, type) and issubclass(cls, BaseException):
                    out.append(cls)
            except Exception as e:
                log.warning("retry_on_class_import_failed", name=n, error=str(e))
        return tuple(out)

    return RetryPolicy(
        max_attempts=msg.max_attempts,
        backoff=msg.backoff or "exponential",
        base_delay_seconds=msg.base_delay_seconds or 2,
        max_delay_seconds=msg.max_delay_seconds or 600,
        jitter=msg.jitter or "full",
        retry_on=_import_classes(msg.retry_on_names) or (Exception,),
        no_retry_on=_import_classes(msg.no_retry_on_names),
    )


def _schedule_retry(msg: JobMessage, delay_seconds: float, redis_client, site: str) -> None:
    new_msg = msg.replace(attempt=msg.attempt + 1)
    encoded = encode(new_msg)
    next_run = _now() + timedelta(seconds=delay_seconds)
    run_at_ms = int(next_run.timestamp() * 1000)
    schedule_message(redis_client, site, encoded, run_at_ms)
    frappe.db.set_value(
        "Conductor Job",
        msg.job_id,
        {
            "status": "SCHEDULED_RETRY",
            "attempt": new_msg.attempt,
            "next_run_at": next_run.replace(tzinfo=None),
        },
        update_modified=False,
    )
    frappe.db.commit()


def _move_to_dlq(msg: JobMessage, exc: BaseException, redis_client, site: str, *, tb_str: str | None = None) -> None:
    encoded = encode(msg)
    redis_client.xadd(dlq_key(site, msg.queue), encoded, maxlen=10000, approximate=True)
    frappe.get_doc({
        "doctype": "Conductor DLQ Entry",
        "job": msg.job_id,
        "queue": msg.queue,
        "moved_at": _now_naive(),
        "attempts": msg.attempt,
        "status": "PENDING_REVIEW",
        "last_error_type": type(exc).__name__,
        "last_error_message": str(exc)[:140],
        "last_traceback": tb_str or traceback.format_exc(),
        "payload": json.dumps(encoded),
        "trace_id": msg.trace_parent or "",
    }).insert(ignore_permissions=True)
    frappe.db.set_value("Conductor Job", msg.job_id, "status", "DLQ", update_modified=False)
    frappe.db.commit()


def _write_job_run_row(
    msg: JobMessage,
    worker_id: str,
    *,
    status: str,
    exc: BaseException | None = None,
    tb_str: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> None:
    finished_at = finished_at or _now()
    started_at = started_at or finished_at
    duration_ms = int((finished_at - started_at).total_seconds() * 1000) if started_at and finished_at else 0
    payload = {
        "doctype": "Conductor Job Run",
        "job": msg.job_id,
        "attempt_number": msg.attempt,
        "status": status,
        "worker_id": worker_id,
        "started_at": started_at.replace(tzinfo=None) if started_at else None,
        "finished_at": finished_at.replace(tzinfo=None) if finished_at else None,
        "duration_ms": duration_ms,
        "trace_id": msg.trace_parent or "",
    }
    if exc is not None:
        payload.update({
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:140],
            "traceback": tb_str or traceback.format_exc(),
        })
    frappe.get_doc(payload).insert(ignore_permissions=True)
    frappe.db.commit()


def _xautoclaim_pending(redis_client, stream: str, worker_id: str) -> list[tuple[bytes, dict]]:
    """Return reclaimed (msg_id, fields) tuples. Bounded to _RECLAIM_BATCH."""
    try:
        result = redis_client.xautoclaim(
            stream, CONSUMER_GROUP, worker_id, min_idle_time=_AUTOCLAIM_IDLE_MS, count=_RECLAIM_BATCH
        )
    except redis_mod.exceptions.ResponseError as e:
        if "NOGROUP" in str(e):
            return []
        raise
    if len(result) >= 2:
        return result[1] or []
    return []


def _handle_one(
    stream_name: str,
    msg_id: bytes,
    fields: dict,
    worker_id: str,
    redis_client,
    site: str,
    sites_path: str,
) -> None:
    frappe.init(site=site, sites_path=sites_path)
    frappe.connect()
    try:
        decoded = {k.decode(): v.decode() for k, v in fields.items()}
        msg = decode(decoded)

        if frappe.db.get_value("Conductor Job", msg.job_id, "status") == "CANCELLED":
            redis_client.xack(stream_name, CONSUMER_GROUP, msg_id)
            return

        if not acquire_exec_lock(redis_client, site, msg.job_id, worker_id, ttl=msg.timeout_seconds + 30):
            log.info("exec_lock_held_by_peer", job_id=msg.job_id)
            redis_client.xack(stream_name, CONSUMER_GROUP, msg_id)
            return

        cancel_event = threading.Event()
        watchdog = start_watchdog(msg.deadline, cancel_event) if msg.deadline else None
        started_at = _now()

        succeeded = False
        result = None
        exc: BaseException | None = None
        exc_tb: str | None = None
        try:
            with set_context(job_id=msg.job_id, attempt=msg.attempt, deadline=msg.deadline, cancel_event=cancel_event):
                _set_job_running(msg.job_id, worker_id)
                func = frappe.get_attr(msg.method)
                result = func(**msg.kwargs)
            succeeded = True
        except BaseException as e:
            exc = e
            exc_tb = traceback.format_exc()

        finished_at = _now()
        current_status = frappe.db.get_value("Conductor Job", msg.job_id, "status")

        if current_status == "CANCELLED":
            _write_job_run_row(
                msg, worker_id,
                status="SUCCEEDED" if succeeded else "FAILED",
                exc=exc, tb_str=exc_tb, started_at=started_at, finished_at=finished_at,
            )
            log.info("job_cancelled", job_id=msg.job_id, completed_anyway=succeeded)

        elif succeeded:
            _set_job_succeeded(msg.job_id, result)
            _write_job_run_row(msg, worker_id, status="SUCCEEDED", started_at=started_at, finished_at=finished_at)
            log.info("job_succeeded", job_id=msg.job_id)

        else:
            policy = _resolve_policy_from_msg(msg)
            if cancel_event.is_set():
                _write_job_run_row(msg, worker_id, status="TIMED_OUT", exc=exc, tb_str=exc_tb, started_at=started_at, finished_at=finished_at)
                if policy.should_retry(exc, msg.attempt):
                    delay = policy.compute_next_delay(msg.attempt)
                    _schedule_retry(msg, delay, redis_client, site)
                else:
                    _move_to_dlq(msg, exc, redis_client, site, tb_str=exc_tb)
                    frappe.db.set_value("Conductor Job", msg.job_id, "status", "TIMED_OUT", update_modified=False)
                    frappe.db.commit()
            elif policy.should_retry(exc, msg.attempt):
                delay = policy.compute_next_delay(msg.attempt)
                _schedule_retry(msg, delay, redis_client, site)
                _write_job_run_row(msg, worker_id, status="FAILED", exc=exc, tb_str=exc_tb, started_at=started_at, finished_at=finished_at)
            else:
                _move_to_dlq(msg, exc, redis_client, site, tb_str=exc_tb)
                _write_job_run_row(msg, worker_id, status="FAILED", exc=exc, tb_str=exc_tb, started_at=started_at, finished_at=finished_at)
            log.error("job_failed", job_id=msg.job_id, attempt=msg.attempt)

        if watchdog:
            watchdog.cancel()
        release_exec_lock(redis_client, site, msg.job_id, worker_id)
        redis_client.xack(stream_name, CONSUMER_GROUP, msg_id)
    finally:
        frappe.destroy()


def _read_and_dispatch(
    redis_client, streams: dict, count: int, block_ms: int, worker_id: str,
    pool: ThreadPoolExecutor, site: str, sites_path: str, *, wait: bool,
):
    """Read up to `count` messages and submit each to the pool.

    `wait=True`: block until every submitted future completes (used by tests so
    pytest sees per-job exceptions).
    `wait=False`: fire-and-forget for production.
    """
    msgs = redis_client.xreadgroup(CONSUMER_GROUP, worker_id, streams, count=count, block=block_ms)
    futures = []
    for stream_name, entries in (msgs or []):
        sname = stream_name.decode() if isinstance(stream_name, bytes) else stream_name
        for msg_id, fields in entries:
            futures.append(pool.submit(_handle_one, sname, msg_id, fields, worker_id, redis_client, site, sites_path))
    if wait:
        for f in futures:
            f.result()


def _reclaim_into_pool(
    redis_client, streams: dict, worker_id: str, pool: ThreadPoolExecutor,
    site: str, sites_path: str, *, wait: bool,
):
    """XAUTOCLAIM all watched streams; submit reclaimed entries to the pool."""
    futures = []
    for stream in streams:
        for msg_id, fields in _xautoclaim_pending(redis_client, stream, worker_id):
            futures.append(pool.submit(_handle_one, stream, msg_id, fields, worker_id, redis_client, site, sites_path))
    if wait:
        for f in futures:
            f.result()


def run_worker_once(*, queues: list[str], concurrency: int, site: str, block_ms: int = 5000) -> None:
    """Test-only single iteration. Reclaim + read + execute synchronously."""
    setup_otel(service_name="conductor")
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    worker_id = _make_worker_id()
    sites_path = frappe.local.sites_path
    _register_worker(worker_id, queues, site)
    streams = {}
    for q in queues:
        skey = stream_key(site, q)
        ensure_consumer_group(r, skey)
        streams[skey] = ">"
    pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="conductor-once-")
    try:
        _reclaim_into_pool(r, streams, worker_id, pool, site, sites_path, wait=True)
        _read_and_dispatch(r, streams, concurrency, block_ms, worker_id, pool, site, sites_path, wait=True)
    finally:
        pool.shutdown(wait=True)
        _mark_worker_gone(worker_id)


_shutdown = threading.Event()


def _install_signal_handlers():
    def handler(signum, frame):
        log.info("signal_received", signum=signum)
        _shutdown.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, handler)
        except ValueError:
            pass


def run_worker(*, queues: list[str], concurrency: int, site: str, grace_seconds: int = 30) -> None:
    setup_logging(site=site)
    setup_otel(service_name="conductor")
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    worker_id = _make_worker_id()
    sites_path = frappe.local.sites_path
    _register_worker(worker_id, queues, site)
    _install_signal_handlers()

    log_ctx = log.bind(worker_id=worker_id, site=site)
    log_ctx.info("worker_started", queues=queues, concurrency=concurrency)

    streams = {}
    for q in queues:
        skey = stream_key(site, q)
        ensure_consumer_group(r, skey)
        streams[skey] = ">"

    pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="conductor-")
    drainer = DelayDrainer(r, site)
    sweeper = OrphanSweeper(r, site, sites_path)
    drainer.start()
    sweeper.start()

    last_beat = 0.0
    try:
        while not _shutdown.is_set():
            now = time.time()
            if now - last_beat >= _HEARTBEAT_SECS:
                _heartbeat(worker_id)
                last_beat = now

            try:
                _reclaim_into_pool(r, streams, worker_id, pool, site, sites_path, wait=False)
                _read_and_dispatch(r, streams, concurrency, 5000, worker_id, pool, site, sites_path, wait=False)
            except redis_mod.exceptions.ConnectionError as e:
                log_ctx.warning("redis_connection_error", error=str(e))
                time.sleep(2)
            except Exception as e:
                log_ctx.error("worker_iteration_failed", error=str(e))
                time.sleep(1)
    finally:
        log_ctx.info("worker_shutting_down", grace_seconds=grace_seconds)
        drainer.stop()
        sweeper.stop()
        pool.shutdown(wait=True)
        _mark_worker_gone(worker_id)
        log_ctx.info("worker_stopped")
