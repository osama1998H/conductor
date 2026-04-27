"""Conductor worker loop: XREADGROUP → execute → status update → XACK."""

from __future__ import annotations

import json
import os
import signal
import socket
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import frappe

from conductor.client import get_redis
from conductor.config import load_config
from conductor.context import set_context, start_watchdog
from conductor.logging import get_logger, setup_logging
from conductor.messages import decode
from conductor.otel import extract_traceparent, get_tracer, setup_otel
from conductor.streams import CONSUMER_GROUP, ensure_consumer_group, stream_key

log = get_logger("conductor.worker")

_HEARTBEAT_SECS = 5
_PREVIEW_MAX = 4096


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_naive() -> datetime:
    """MariaDB DATETIME doesn't accept tz-aware strings; strip before write."""
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
    frappe.get_doc(
        {
            "doctype": "Conductor Worker",
            "worker_id": worker_id,
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "queues": json.dumps(queues),
            "site": site,
            "status": "ALIVE",
            "started_at": _now_naive(),
            "last_heartbeat": _now_naive(),
        }
    ).insert(ignore_permissions=True)
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


def _set_job_failed(job_id: str, status: str, exc: BaseException) -> None:
    frappe.db.set_value(
        "Conductor Job",
        job_id,
        {
            "status": status,
            "finished_at": _now_naive(),
            "last_error_type": type(exc).__name__,
            "last_error_message": str(exc)[:140],
            "last_traceback": traceback.format_exc(),
        },
        update_modified=False,
    )
    frappe.db.commit()


def _handle_one(stream_name: str, msg_id: bytes, fields: dict, worker_id: str, redis_client, site: str, sites_path: str) -> None:
    # Each pool thread needs its own frappe.local binding.
    frappe.init(site=site, sites_path=sites_path)
    frappe.connect()
    try:
        decoded = {k.decode(): v.decode() for k, v in fields.items()}
        msg = decode(decoded)
        parent_ctx = extract_traceparent(msg.trace_parent)
        tracer = get_tracer()
        log_ctx = log.bind(job_id=msg.job_id, queue=msg.queue, worker_id=worker_id)
        log_ctx.info("job_received")

        with tracer.start_as_current_span(f"job:{msg.method}", context=parent_ctx) as span:
            span.set_attribute("conductor.job_id", msg.job_id)
            _set_job_running(msg.job_id, worker_id)

            cancel_event = threading.Event()
            watchdog = start_watchdog(msg.deadline, cancel_event) if msg.deadline else None
            try:
                with set_context(job_id=msg.job_id, attempt=msg.attempt, deadline=msg.deadline, cancel_event=cancel_event):
                    func = frappe.get_attr(msg.method)
                    result = func(**msg.kwargs)
                _set_job_succeeded(msg.job_id, result)
                log_ctx.info("job_succeeded")
            except BaseException as e:
                status = "TIMED_OUT" if cancel_event.is_set() else "FAILED"
                _set_job_failed(msg.job_id, status, e)
                span.record_exception(e)
                log_ctx.error("job_failed", status=status, error=str(e))
            finally:
                if watchdog:
                    watchdog.cancel()
                redis_client.xack(stream_name, CONSUMER_GROUP, msg_id)
    finally:
        frappe.destroy()


def _read_and_dispatch(redis_client, streams: dict, count: int, block_ms: int, worker_id: str, pool: ThreadPoolExecutor, site: str, sites_path: str):
    msgs = redis_client.xreadgroup(CONSUMER_GROUP, worker_id, streams, count=count, block=block_ms)
    futures = []
    for stream_name, entries in (msgs or []):
        sname = stream_name.decode() if isinstance(stream_name, bytes) else stream_name
        for msg_id, fields in entries:
            futures.append(pool.submit(_handle_one, sname, msg_id, fields, worker_id, redis_client, site, sites_path))
    for f in futures:
        f.result()  # surface exceptions inside tests


def run_worker_once(*, queues: list[str], concurrency: int, site: str, block_ms: int = 5000) -> None:
    """Run a single XREADGROUP pass and execute every received message synchronously.

    Used by tests; not for production.
    """
    setup_otel(service_name="conductor")
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    worker_id = _make_worker_id()
    # Capture sites_path on the calling (test) thread before spawning pool threads.
    sites_path = frappe.local.sites_path
    _register_worker(worker_id, queues, site)
    streams = {}
    for q in queues:
        skey = stream_key(site, q)
        ensure_consumer_group(r, skey)
        streams[skey] = ">"
    pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="conductor-once-")
    try:
        _read_and_dispatch(r, streams, concurrency, block_ms, worker_id, pool, site, sites_path)
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
            # Not on the main thread (e.g., tests) — skip.
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
    last_beat = 0.0
    try:
        while not _shutdown.is_set():
            now = time.time()
            if now - last_beat >= _HEARTBEAT_SECS:
                _heartbeat(worker_id)
                last_beat = now
            try:
                _read_and_dispatch(r, streams, concurrency, 5000, worker_id, pool, site, sites_path)
            except Exception as e:
                log_ctx.error("worker_iteration_failed", error=str(e))
                time.sleep(1)
    finally:
        log_ctx.info("worker_shutting_down", grace_seconds=grace_seconds)
        pool.shutdown(wait=True)
        _mark_worker_gone(worker_id)
        log_ctx.info("worker_stopped")
