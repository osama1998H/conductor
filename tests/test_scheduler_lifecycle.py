"""Unit tests for the scheduler lifecycle: lock acquire, renewer, lost-lock fence.

These tests exercise the scheduler's plumbing in isolation — no Frappe init
required (the loops are skipped via the `loops_disabled=True` test hook)."""

import threading
import time

import fakeredis
import pytest

from conductor.scheduler import run_scheduler_lifecycle
from conductor.scheduler_lock import lock_redis_key


@pytest.fixture
def r():
    return fakeredis.FakeStrictRedis()


def test_acquires_lock_and_holds_it(r):
    stop = threading.Event()
    started = threading.Event()
    t = threading.Thread(
        target=run_scheduler_lifecycle,
        kwargs=dict(
            redis_client=r, site="site1", instance_id="A",
            lock_ttl_seconds=2, renew_interval_seconds=1, poll_interval_seconds=1,
            stop_event=stop, started_event=started, loops_disabled=True,
        ),
        daemon=True,
    )
    t.start()
    assert started.wait(timeout=5)
    # We are now the lock holder.
    assert r.get(lock_redis_key("site1")) == b"A"
    # Hold it across a renewal.
    time.sleep(1.5)
    assert r.get(lock_redis_key("site1")) == b"A"
    stop.set()
    t.join(timeout=5)
    # Released cleanly on shutdown.
    assert r.get(lock_redis_key("site1")) is None


def test_loser_polls_until_holder_releases(r):
    # Pre-populate lock as if held by another instance.
    r.set(lock_redis_key("site1"), "X", ex=2)
    stop = threading.Event()
    started = threading.Event()
    t = threading.Thread(
        target=run_scheduler_lifecycle,
        kwargs=dict(
            redis_client=r, site="site1", instance_id="B",
            lock_ttl_seconds=2, renew_interval_seconds=1, poll_interval_seconds=1,
            stop_event=stop, started_event=started, loops_disabled=True,
        ),
        daemon=True,
    )
    t.start()
    # Should not have acquired yet.
    time.sleep(0.5)
    assert r.get(lock_redis_key("site1")) == b"X"
    # Wait for X's TTL to expire and B to take over.
    assert started.wait(timeout=5)
    assert r.get(lock_redis_key("site1")) == b"B"
    stop.set()
    t.join(timeout=5)


def test_lost_lock_causes_exit(r):
    stop = threading.Event()
    started = threading.Event()
    lost = threading.Event()
    t = threading.Thread(
        target=run_scheduler_lifecycle,
        kwargs=dict(
            redis_client=r, site="site1", instance_id="A",
            lock_ttl_seconds=2, renew_interval_seconds=1, poll_interval_seconds=1,
            stop_event=stop, started_event=started, loops_disabled=True,
            lost_lock_event_for_test=lost,
        ),
        daemon=True,
    )
    t.start()
    assert started.wait(timeout=5)
    # Steal the lock.
    r.set(lock_redis_key("site1"), "X")
    # Renewer should detect within 1s of next renewal tick (≤ 2s wall clock).
    assert lost.wait(timeout=4)
    # The thread should self-terminate.
    t.join(timeout=5)
    assert not t.is_alive()
