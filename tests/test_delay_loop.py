"""Unit tests for the scheduler's delay loop — drains ZSET → XADDs streams."""

import json
import time

import fakeredis
import pytest

from conductor.scheduled import scheduled_redis_key
from conductor.scheduler_loops import _delay_loop_iter
from conductor.streams import stream_key


@pytest.fixture
def r():
    return fakeredis.FakeStrictRedis()


def _make_encoded(queue: str, job_id: str = "j") -> dict[str, str]:
    return {
        "job_id": job_id,
        "site": "site1",
        "name": "x.y",
        "queue": queue,
        "args_b64": "",
        "kwargs_b64": "",
        "attempt": "1",
        "max_attempts": "1",
        "timeout_seconds": "60",
        "enqueued_at": "2026-04-27T12:00:00+00:00",
        "schema_version": "1",
    }


def test_due_messages_xadded_to_stream(r):
    site = "site1"
    encoded = _make_encoded("default")
    member = json.dumps(encoded)
    score = int(time.time() * 1000) - 5000  # due 5s ago
    r.zadd(scheduled_redis_key(site), {member: score})
    _delay_loop_iter(r, site)
    # ZSET drained.
    assert r.zcard(scheduled_redis_key(site)) == 0
    # Stream got the entry.
    skey = stream_key(site, "default")
    entries = r.xrange(skey)
    assert len(entries) == 1


def test_future_messages_left_alone(r):
    site = "site1"
    encoded = _make_encoded("default")
    member = json.dumps(encoded)
    score = int(time.time() * 1000) + 60_000  # due in 60s
    r.zadd(scheduled_redis_key(site), {member: score})
    _delay_loop_iter(r, site)
    assert r.zcard(scheduled_redis_key(site)) == 1


def test_messages_for_multiple_queues_route_correctly(r):
    site = "site1"
    now_ms = int(time.time() * 1000)
    a = _make_encoded("queueA", "ja")
    b = _make_encoded("queueB", "jb")
    r.zadd(scheduled_redis_key(site), {json.dumps(a): now_ms - 1000})
    r.zadd(scheduled_redis_key(site), {json.dumps(b): now_ms - 1000})
    _delay_loop_iter(r, site)
    assert len(r.xrange(stream_key(site, "queueA"))) == 1
    assert len(r.xrange(stream_key(site, "queueB"))) == 1


def test_message_with_empty_queue_is_skipped(r):
    site = "site1"
    encoded = _make_encoded("")
    r.zadd(scheduled_redis_key(site), {json.dumps(encoded): int(time.time() * 1000) - 1000})
    _delay_loop_iter(r, site)
    # Drained from ZSET (we still ZREM bad messages so they don't pile up).
    assert r.zcard(scheduled_redis_key(site)) == 0
