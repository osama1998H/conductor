"""Conductor scheduler — per-site singleton owning four background loops.

Lock holder runs delay/cron/reaper/sweeper loops as daemon threads. On lost
lock (renewal returns False), the renewer sets `lost_lock_event`; the main
function returns and the supervisor (bench/systemd) restarts the process.

This module is built incrementally:
- Task 5: skeleton (lifecycle + renewer + lost-lock fence; loops disabled).
- Task 6: cron loop.
- Task 7: delay loop.
- Task 8: reaper loop.
- Task 9: sweeper loop.
"""

from __future__ import annotations

import os
import signal
import socket
import threading
import time
import uuid

import redis as redis_mod

from conductor.logging import get_logger
from conductor.scheduler_lock import acquire, lock_redis_key, release, renew

log = get_logger("conductor.scheduler")


def _make_instance_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _renewer(
    client: redis_mod.Redis,
    site: str,
    instance_id: str,
    *,
    ttl: int,
    interval: float,
    stop_event: threading.Event,
    lost_lock_event: threading.Event,
):
    """Daemon thread: every `interval` seconds, renew the lock. If renewal
    returns False (we no longer own the key), set `lost_lock_event` and exit."""
    while not stop_event.is_set():
        ok = renew(client, site, instance_id, ttl=ttl)
        if not ok:
            log.error("scheduler_lost_lock", site=site, instance_id=instance_id)
            lost_lock_event.set()
            return
        stop_event.wait(interval)


def run_scheduler_lifecycle(
    *,
    redis_client: redis_mod.Redis,
    site: str,
    instance_id: str,
    lock_ttl_seconds: int = 15,
    renew_interval_seconds: int = 5,
    poll_interval_seconds: int = 5,
    stop_event: threading.Event | None = None,
    started_event: threading.Event | None = None,
    loops_disabled: bool = False,
    sites_path: str | None = None,
    lost_lock_event_for_test: threading.Event | None = None,
):
    """Block until we acquire the lock; then run loops until stop_event or lost lock.

    Test hooks:
      - `started_event` — set after we acquire the lock.
      - `loops_disabled` — skip starting the four loops (we're testing the
        lifecycle in isolation; loops require frappe init).
      - `lost_lock_event_for_test` — same lost-lock event used internally; the
        test asserts it gets set when the lock is stolen.
    """
    stop_event = stop_event or threading.Event()
    lost_lock_event = lost_lock_event_for_test or threading.Event()

    # Phase 1: poll for the lock.
    while not stop_event.is_set():
        if acquire(redis_client, site, instance_id, ttl=lock_ttl_seconds):
            break
        stop_event.wait(poll_interval_seconds)
    if stop_event.is_set():
        return

    log.info("scheduler_acquired_lock", site=site, instance_id=instance_id)
    if started_event:
        started_event.set()

    # Phase 2: run the renewer + (later) the four loops.
    renewer = threading.Thread(
        target=_renewer,
        kwargs=dict(
            client=redis_client, site=site, instance_id=instance_id,
            ttl=lock_ttl_seconds, interval=renew_interval_seconds,
            stop_event=stop_event, lost_lock_event=lost_lock_event,
        ),
        daemon=True, name="conductor-scheduler-renewer",
    )
    renewer.start()

    loop_threads: list[threading.Thread] = []
    if not loops_disabled:
        # Filled in by Tasks 6-9.
        from conductor.scheduler_loops import start_all_loops  # noqa: F401
        loop_threads = start_all_loops(
            redis_client=redis_client, site=site, sites_path=sites_path,
            stop_event=stop_event, lost_lock_event=lost_lock_event,
        )

    # Wait for stop or lost-lock. Either way, drain and release.
    while not stop_event.is_set() and not lost_lock_event.is_set():
        time.sleep(0.1)
    log.info("scheduler_shutting_down",
             site=site, instance_id=instance_id,
             reason="stop" if stop_event.is_set() else "lost_lock")
    stop_event.set()  # Signal everyone if it was lost-lock that woke us.
    for t in loop_threads:
        t.join(timeout=5)
    renewer.join(timeout=5)
    # Only release if we still own it (lost-lock path: don't unset a peer's lock).
    release(redis_client, site, instance_id)


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


def run_scheduler(
    *,
    site: str,
    lock_ttl_seconds: int = 15,
    renew_interval_seconds: int = 5,
    poll_interval_seconds: int = 5,
):
    """Production entry — called from bench conductor scheduler. Loops outermost
    so a lost-lock exit is followed by a fresh poll."""
    import frappe

    from conductor.client import get_redis
    from conductor.config import load_config
    from conductor.logging import setup_logging
    from conductor.otel import setup_otel

    setup_logging(site=site)
    setup_otel(service_name="conductor-scheduler")
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    sites_path = frappe.local.sites_path
    instance_id = _make_instance_id()
    _install_signal_handlers()

    log_ctx = log.bind(site=site, instance_id=instance_id)
    log_ctx.info("scheduler_started",
                 lock_ttl=lock_ttl_seconds,
                 renew_interval=renew_interval_seconds)

    while not _shutdown.is_set():
        cycle_stop = threading.Event()
        # Bridge: when the global _shutdown trips, also set this cycle's stop.
        bridge = threading.Thread(
            target=lambda: (_shutdown.wait(), cycle_stop.set()),
            daemon=True, name="conductor-scheduler-shutdown-bridge",
        )
        bridge.start()
        run_scheduler_lifecycle(
            redis_client=r, site=site, instance_id=instance_id,
            lock_ttl_seconds=lock_ttl_seconds,
            renew_interval_seconds=renew_interval_seconds,
            poll_interval_seconds=poll_interval_seconds,
            stop_event=cycle_stop, sites_path=sites_path,
        )
        if not _shutdown.is_set():
            log_ctx.warning("scheduler_lost_lock_or_exited_cleanly_recycling")
            time.sleep(1)
    log_ctx.info("scheduler_stopped")
