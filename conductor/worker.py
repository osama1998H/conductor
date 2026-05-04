"""Conductor worker loop: XREADGROUP → execute → status update → XACK.

Per attempt the worker:
- Acquires/releases the execution lock around job execution.
- On retryable failure: ZADD to scheduled set, status=SCHEDULED_RETRY.
- On exhausted retries: XADD to DLQ stream + Conductor DLQ Entry row, status=DLQ.
- Writes a Conductor Job Run row at terminal of each attempt.
- Reclaims stalled messages via XAUTOCLAIM (idle ≥ 60s) once per iteration.

The scheduler process owns the DelayDrainer and OrphanSweeper loops; the worker
only runs the CancelPoller + XAUTOCLAIM loop + heartbeat.
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
from conductor.inflight import acquire as inflight_acquire, release as inflight_release
from conductor.logging import get_logger, setup_logging
from conductor.messages import JobMessage, decode, emit_job_event, encode
from conductor.rate_limit import take_token
from conductor.retry import RetryPolicy
from conductor.scheduled import schedule_message
from conductor.streams import CONSUMER_GROUP, dlq_key, ensure_consumer_group, stream_key

# Import demo workflows so they're registered at worker startup.
# Workflows are registered at module import time via @workflow decorator.
import conductor.demo  # noqa: F401

log = get_logger("conductor.worker")

_HEARTBEAT_SECS = 5
_PREVIEW_MAX = 4096
_AUTOCLAIM_IDLE_MS = int(os.environ.get("CONDUCTOR_TEST_AUTOCLAIM_IDLE_MS", "60000"))
# In tests, override the exec-lock TTL so that a killed worker's lock expires
# quickly and a reclaiming peer can proceed. Production default: timeout + 30s.
_EXEC_LOCK_TTL_OVERRIDE = int(os.environ.get("CONDUCTOR_TEST_EXEC_LOCK_TTL_SECONDS", "0"))
_RECLAIM_BATCH = 32
_INFLIGHT_RETRY_BACKOFF_MS_DEFAULT = 1000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def now_naive() -> datetime:
    """UTC-naive timestamp matching MariaDB DATETIME storage.

    All Conductor reads/writes of `last_heartbeat`, `last_execution`,
    `reviewed_at`, etc. compare against this value. Using a local-naive
    `datetime.now()` would introduce the host's UTC offset as a phantom
    age delta — see Plan-2's M7 doctor fix for the reasoning.
    """
    return _now().replace(tzinfo=None)


# Back-compat alias for any in-tree caller still using the underscore name.
# Drop in v2.1 once external imports settle.
_now_naive = now_naive


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
        "started_at": now_naive(),
        "last_heartbeat": now_naive(),
    }).insert(ignore_permissions=True)
    frappe.db.commit()


def _heartbeat(worker_id: str) -> None:
    """Heartbeat both writes last_heartbeat AND resets status to ALIVE.

    Without the status reset, a worker that the reaper marked STALE during a
    long GC pause would stay STALE forever in Desk even after it resumed.
    """
    frappe.db.set_value(
        "Conductor Worker",
        worker_id,
        {"last_heartbeat": now_naive(), "status": "ALIVE"},
        update_modified=False,
    )
    frappe.db.commit()


def _mark_worker_gone(worker_id: str) -> None:
    if frappe.db.exists("Conductor Worker", worker_id):
        frappe.db.set_value("Conductor Worker", worker_id, "status", "GONE", update_modified=False)
        frappe.db.commit()


def _register_worker_pool(
    worker_id: str,
    *,
    queues: list[str],
    sites: list[str],
    sites_path: str,
    primary_site: str,
) -> None:
    """Insert one Conductor Worker row per site so each site's reaper sees us.

    Each per-site init/connect/destroy cycle tears down frappe.local; the
    trailing init+connect on primary_site restores the outer CLI context that
    the worker loop, CancelPoller, and _handle_one all depend on.
    """
    for site in sites:
        frappe.init(site=site, sites_path=sites_path)
        try:
            frappe.connect()
            if not frappe.db.exists("Conductor Worker", worker_id):
                frappe.get_doc({
                    "doctype": "Conductor Worker",
                    "worker_id": worker_id,
                    "host": socket.gethostname(),
                    "pid": os.getpid(),
                    "queues": json.dumps(queues),
                    "site": site,
                    "status": "ALIVE",
                    "started_at": now_naive(),
                    "last_heartbeat": now_naive(),
                }).insert(ignore_permissions=True)
                frappe.db.commit()
        finally:
            frappe.destroy()
    frappe.init(site=primary_site, sites_path=sites_path)
    frappe.connect()


def _heartbeat_pool(
    worker_id: str,
    *,
    sites: list[str],
    sites_path: str,
    primary_site: str,
) -> None:
    """Fanout heartbeat across every site this worker serves. Restores the
    primary-site frappe.local context after the per-site fanout so the outer
    CLI init context remains valid."""
    for site in sites:
        frappe.init(site=site, sites_path=sites_path)
        try:
            frappe.connect()
            frappe.db.set_value(
                "Conductor Worker",
                worker_id,
                {"last_heartbeat": now_naive(), "status": "ALIVE"},
                update_modified=False,
            )
            frappe.db.commit()
        finally:
            frappe.destroy()
    frappe.init(site=primary_site, sites_path=sites_path)
    frappe.connect()


def _mark_worker_gone_pool(
    worker_id: str,
    *,
    sites: list[str],
    sites_path: str,
    primary_site: str,
) -> None:
    """Best-effort GONE status across every site, even if individual sites
    fail. The trailing init+connect is best-effort because the process is
    shutting down."""
    for site in sites:
        try:
            frappe.init(site=site, sites_path=sites_path)
            try:
                frappe.connect()
                if frappe.db.exists("Conductor Worker", worker_id):
                    frappe.db.set_value(
                        "Conductor Worker", worker_id, "status", "GONE",
                        update_modified=False,
                    )
                    frappe.db.commit()
            finally:
                frappe.destroy()
        except Exception as e:
            log.warning("mark_gone_failed_for_site", site=site, error=str(e))
    try:
        frappe.init(site=primary_site, sites_path=sites_path)
        frappe.connect()
    except Exception:
        pass


def _set_job_running(job_id: str, worker_id: str) -> None:
    frappe.db.set_value(
        "Conductor Job",
        job_id,
        {"status": "RUNNING", "started_at": now_naive(), "worker_id": worker_id},
        update_modified=False,
    )
    frappe.db.commit()
    emit_job_event(job_id, "RUNNING")


def _set_job_succeeded(job_id: str, result) -> None:
    frappe.db.set_value(
        "Conductor Job",
        job_id,
        {"status": "SUCCEEDED", "finished_at": now_naive(), "result_preview": _preview(result)},
        update_modified=False,
    )
    frappe.db.commit()
    emit_job_event(job_id, "SUCCEEDED")


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
    emit_job_event(
        msg.job_id,
        "SCHEDULED_RETRY",
        attempt=new_msg.attempt,
        max_attempts=msg.max_attempts,
        next_run_at=next_run.replace(tzinfo=None).isoformat(),
    )


def _move_to_dlq(msg: JobMessage, exc: BaseException, redis_client, site: str, *, tb_str: str | None = None) -> None:
    encoded = encode(msg)
    redis_client.xadd(dlq_key(site, msg.queue), encoded, maxlen=10000, approximate=True)
    frappe.get_doc({
        "doctype": "Conductor DLQ Entry",
        "job": msg.job_id,
        "queue": msg.queue,
        "moved_at": now_naive(),
        "attempts": msg.attempt,
        "status": "PENDING_REVIEW",
        "last_error_type": type(exc).__name__,
        "last_error_message": str(exc)[:140],
        "last_traceback": tb_str or traceback.format_exc(),
        "payload": json.dumps(encoded),
    }).insert(ignore_permissions=True)
    frappe.db.set_value("Conductor Job", msg.job_id, "status", "DLQ", update_modified=False)
    frappe.db.commit()
    emit_job_event(
        msg.job_id,
        "DLQ",
        attempt=msg.attempt,
        max_attempts=msg.max_attempts,
        queue=msg.queue,
        method=msg.method,
        last_error_type=type(exc).__name__,
        last_error_message=str(exc)[:140],
    )


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


def _build_streams_dict(redis_client, sites: list[str], queues: list[str]) -> dict[str, str]:
    """For each (site, queue) pair, ensure the consumer group exists and
    return a streams dict suitable for XREADGROUP."""
    streams: dict[str, str] = {}
    for site in sites:
        for queue in queues:
            skey = stream_key(site, queue)
            ensure_consumer_group(redis_client, skey)
            streams[skey] = ">"
    return streams


class CancelPoller:
    """Polls Conductor Job for status=CANCELLED rows belonging to this worker
    and flips matching cancel_event entries in the shared map (§12.4)."""

    def __init__(
        self,
        worker_id: str,
        site: str,
        sites_path: str,
        cancel_events: dict[str, threading.Event],
        cancel_events_lock: threading.Lock,
        interval: float = 1.0,
    ):
        self._worker_id = worker_id
        self._site = site
        self._sites_path = sites_path
        self._cancel_events = cancel_events
        self._lock = cancel_events_lock
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="conductor-cancel-poller")

    def start(self) -> None:
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        self._thread.join(timeout=timeout)

    def _run(self) -> None:
        log.info("cancel_poller_started", worker_id=self._worker_id)
        while not self._stop.is_set():
            try:
                frappe.init(site=self._site, sites_path=self._sites_path)
                frappe.connect()
                try:
                    rows = frappe.db.sql(
                        "SELECT job_id FROM `tabConductor Job` WHERE status='CANCELLED' AND worker_id=%s",
                        (self._worker_id,),
                        as_dict=True,
                    )
                    for row in rows:
                        with self._lock:
                            ev = self._cancel_events.get(row["job_id"])
                        if ev is not None:
                            ev.set()
                finally:
                    frappe.destroy()
            except Exception as e:
                log.error("cancel_poller_iteration_failed", error=str(e))
            self._stop.wait(self._interval)
        log.info("cancel_poller_stopped", worker_id=self._worker_id)


# Process-global cancel_events map populated by _handle_one for the duration of
# each running job; CancelPoller flips entries when the DB shows CANCELLED.
_cancel_events: dict[str, threading.Event] = {}
_cancel_events_lock = threading.Lock()


def _make_pool_cancel_pollers(
    *,
    worker_id: str,
    sites: list[str],
    sites_path: str,
) -> list[CancelPoller]:
    """Construct one CancelPoller per site; all pollers share the
    process-global `_cancel_events` map and `_cancel_events_lock`."""
    return [
        CancelPoller(
            worker_id, site, sites_path,
            _cancel_events, _cancel_events_lock,
        )
        for site in sites
    ]


def _resolve_queue_limits(queue: str) -> tuple[int, int]:
    """Read (max_rps, max_concurrent) from the Conductor Queue cached doc.
    Both default to 0 (unlimited). Frappe's get_cached_doc invalidates on
    document update so dashboard edits propagate within seconds."""
    doc = frappe.get_cached_doc("Conductor Queue", queue)
    return int(getattr(doc, "max_rps", 0) or 0), int(getattr(doc, "max_concurrent", 0) or 0)


def _throttle_action(
    redis_client,
    msg: JobMessage,
    site: str,
    *,
    reason: str,
    retry_after_ms: int,
) -> None:
    """Re-ZADD the message into the delay set for `retry_after_ms` from now;
    flip the Conductor Job row to SCHEDULED_RETRY without bumping attempt;
    emit a realtime event with `reason` so the dashboard can distinguish
    throttling from real retries."""
    encoded = encode(msg)
    next_run = _now() + timedelta(milliseconds=retry_after_ms)
    run_at_ms = int(next_run.timestamp() * 1000)
    schedule_message(redis_client, site, encoded, run_at_ms)
    frappe.db.set_value(
        "Conductor Job",
        msg.job_id,
        {
            "status": "SCHEDULED_RETRY",
            "next_run_at": next_run.replace(tzinfo=None),
            "last_error_type": "Throttled",
            "last_error_message": f"{reason}",
        },
        update_modified=False,
    )
    frappe.db.commit()
    emit_job_event(
        msg.job_id,
        "SCHEDULED_RETRY",
        attempt=msg.attempt,
        max_attempts=msg.max_attempts,
        next_run_at=next_run.replace(tzinfo=None).isoformat(),
        reason=reason,
    )


def _apply_throttle_gate(
    redis_client,
    msg: JobMessage,
    *,
    site: str,
    rps: int,
    conc: int,
    now_ms: int,
) -> bool:
    """Returns True if the job is allowed to run, False if it has been
    re-scheduled. Inflight is checked first (free fail). On rate-limit
    rejection after a successful inflight acquire, inflight is released."""
    if rps <= 0 and conc <= 0:
        return True

    if conc > 0:
        acquired, _cur = inflight_acquire(redis_client, site, msg.queue, max_concurrent=conc)
        if not acquired:
            _throttle_action(
                redis_client, msg, site,
                reason="inflight_capped",
                retry_after_ms=_INFLIGHT_RETRY_BACKOFF_MS_DEFAULT,
            )
            return False

    if rps > 0:
        allowed, retry_ms = take_token(
            redis_client, site, msg.queue,
            max_tokens=rps, refill_per_sec=rps,
            now_ms=now_ms, n=1,
        )
        if not allowed:
            if conc > 0:
                inflight_release(redis_client, site, msg.queue)  # don't leak slot
            _throttle_action(
                redis_client, msg, site,
                reason="rate_limited",
                retry_after_ms=max(retry_ms, 1),
            )
            return False

    return True


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

        lock_ttl = _EXEC_LOCK_TTL_OVERRIDE if _EXEC_LOCK_TTL_OVERRIDE > 0 else msg.timeout_seconds + 30
        if not acquire_exec_lock(redis_client, site, msg.job_id, worker_id, ttl=lock_ttl):
            log.info("exec_lock_held_by_peer", job_id=msg.job_id)
            redis_client.xack(stream_name, CONSUMER_GROUP, msg_id)
            return

        # Throttle gate: rate limit + concurrency cap.
        # Resolved once per job so the success path can reference `conc`.
        rps, conc = _resolve_queue_limits(msg.queue)
        if rps > 0 or conc > 0:
            now_ms = int(time.time() * 1000)
            if not _apply_throttle_gate(redis_client, msg, site=site, rps=rps, conc=conc, now_ms=now_ms):
                release_exec_lock(redis_client, site, msg.job_id, worker_id)
                redis_client.xack(stream_name, CONSUMER_GROUP, msg_id)
                return

        cancel_event = threading.Event()
        with _cancel_events_lock:
            _cancel_events[msg.job_id] = cancel_event
        try:
            watchdog = start_watchdog(msg.deadline, cancel_event) if msg.deadline else None
            started_at = _now()

            succeeded = False
            result = None
            exc: BaseException | None = None
            exc_tb: str | None = None
            try:
                with set_context(job_id=msg.job_id, attempt=msg.attempt, deadline=msg.deadline, cancel_event=cancel_event):
                    _set_job_running(msg.job_id, worker_id)

                    if msg.workflow_run_id and msg.step_id:
                        from conductor.workflow.worker_hooks import mark_step_running
                        is_comp = bool(msg.kwargs.get("__is_compensation"))
                        mark_step_running(
                            workflow_run_id=msg.workflow_run_id,
                            step_id=msg.step_id,
                            is_compensation=is_comp,
                        )

                    # For workflow steps, instantiate the class and call the method as an instance method.
                    if msg.workflow_run_id and msg.step_id:
                        # msg.method is "package.module.ClassName.method_name"
                        # Split off the last two parts (ClassName.method_name)
                        parts = msg.method.rsplit(".", 2)
                        if len(parts) == 3:
                            module_name, class_name, method_name = parts
                            module = importlib.import_module(module_name)
                            cls = getattr(module, class_name)
                            instance = cls()  # instantiate the workflow class
                            method = getattr(instance, method_name)
                            # Clean up workflow-internal kwargs before calling the method
                            clean_kwargs = {k: v for k, v in msg.kwargs.items() if not k.startswith("__")}
                            result = method(**clean_kwargs)
                        else:
                            # Fallback to regular function lookup if method path doesn't have enough parts
                            func = frappe.get_attr(msg.method)
                            result = func(**msg.kwargs)
                    else:
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

                if msg.workflow_run_id and msg.step_id:
                    from conductor.workflow.worker_hooks import mark_step_terminal
                    from conductor.workflow.advancer import enqueue_advance
                    is_comp = bool(msg.kwargs.get("__is_compensation"))
                    mark_step_terminal(
                        workflow_run_id=msg.workflow_run_id, step_id=msg.step_id,
                        is_compensation=is_comp, success=True,
                    )
                    enqueue_advance(
                        msg.workflow_run_id,
                        completed_step=msg.step_id,
                        is_compensation=is_comp,
                    )

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
                        emit_job_event(
                            msg.job_id,
                            "TIMED_OUT",
                            attempt=msg.attempt,
                            max_attempts=msg.max_attempts,
                            last_error_type=type(exc).__name__ if exc else "TimeoutError",
                            last_error_message=str(exc)[:140] if exc else "deadline exceeded",
                        )
                elif policy.should_retry(exc, msg.attempt):
                    delay = policy.compute_next_delay(msg.attempt)
                    _schedule_retry(msg, delay, redis_client, site)
                    _write_job_run_row(msg, worker_id, status="FAILED", exc=exc, tb_str=exc_tb, started_at=started_at, finished_at=finished_at)
                else:
                    _move_to_dlq(msg, exc, redis_client, site, tb_str=exc_tb)
                    _write_job_run_row(msg, worker_id, status="FAILED", exc=exc, tb_str=exc_tb, started_at=started_at, finished_at=finished_at)

                    if msg.workflow_run_id and msg.step_id:
                        from conductor.workflow.worker_hooks import mark_step_terminal
                        from conductor.workflow.advancer import enqueue_advance
                        is_comp = bool(msg.kwargs.get("__is_compensation"))
                        mark_step_terminal(
                            workflow_run_id=msg.workflow_run_id, step_id=msg.step_id,
                            is_compensation=is_comp, success=False,
                            error_type=type(exc).__name__,
                            error_message=str(exc),
                        )
                        enqueue_advance(
                            msg.workflow_run_id,
                            completed_step=msg.step_id,
                            is_compensation=is_comp,
                        )
                log.error("job_failed", job_id=msg.job_id, attempt=msg.attempt)

            if watchdog:
                watchdog.cancel()
            with _cancel_events_lock:
                _cancel_events.pop(msg.job_id, None)
            if conc > 0:
                inflight_release(redis_client, site, msg.queue)
            release_exec_lock(redis_client, site, msg.job_id, worker_id)
            redis_client.xack(stream_name, CONSUMER_GROUP, msg_id)
        finally:
            with _cancel_events_lock:
                _cancel_events.pop(msg.job_id, None)
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


def run_worker_pool(
    *,
    sites: list[str],
    queues: list[str],
    concurrency: int,
    grace_seconds: int = 30,
) -> None:
    """Run a Conductor pool worker against N sites x M queues.

    The single-site `run_worker` is a thin wrapper that calls this with
    sites=[site].
    """
    if not sites:
        raise ValueError("run_worker_pool: sites must be non-empty")

    primary_site = sites[0]
    setup_logging(site=primary_site)

    # Cfg/Redis are bench-wide -- read from the already-inited frappe.local
    # (the CLI command sets up frappe.init/connect before calling us).
    cfg = load_config(frappe.local.conf)
    sites_path = frappe.local.sites_path
    r = get_redis(cfg.redis_url)

    worker_id = _make_worker_id()
    _register_worker_pool(
        worker_id,
        queues=queues,
        sites=sites,
        sites_path=sites_path,
        primary_site=primary_site,
    )
    _install_signal_handlers()

    log_ctx = log.bind(worker_id=worker_id, sites=sites)
    log_ctx.info("worker_pool_started", queues=queues, concurrency=concurrency)

    streams = _build_streams_dict(r, sites, queues)

    pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="conductor-")
    pollers = _make_pool_cancel_pollers(
        worker_id=worker_id, sites=sites, sites_path=sites_path,
    )
    for p in pollers:
        p.start()

    last_beat = 0.0
    try:
        while not _shutdown.is_set():
            now = time.time()
            if now - last_beat >= _HEARTBEAT_SECS:
                _heartbeat_pool(
                    worker_id,
                    sites=sites,
                    sites_path=sites_path,
                    primary_site=primary_site,
                )
                last_beat = now

            try:
                _reclaim_into_pool(r, streams, worker_id, pool, primary_site, sites_path, wait=False)
                _read_and_dispatch(r, streams, concurrency, 5000, worker_id, pool, primary_site, sites_path, wait=False)
            except redis_mod.exceptions.ConnectionError as e:
                log_ctx.warning("redis_connection_error", error=str(e))
                time.sleep(2)
            except Exception as e:
                log_ctx.error("worker_iteration_failed", error=str(e))
                time.sleep(1)
    finally:
        log_ctx.info("worker_shutting_down", grace_seconds=grace_seconds)
        for p in pollers:
            p.stop()
        pool.shutdown(wait=True)
        _mark_worker_gone_pool(
            worker_id,
            sites=sites,
            sites_path=sites_path,
            primary_site=primary_site,
        )
        log_ctx.info("worker_stopped")


def run_worker(*, queues: list[str], concurrency: int, site: str, grace_seconds: int = 30) -> None:
    """Single-site worker -- implemented as the N=1 case of pool mode."""
    return run_worker_pool(
        sites=[site], queues=queues, concurrency=concurrency, grace_seconds=grace_seconds,
    )
