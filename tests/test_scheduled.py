"""Unit tests for conductor.scheduled — ZSET helpers + drainer pull loop."""

import json
import time

from conductor.messages import encode
from conductor.scheduled import (
    drain_due_messages,
    schedule_message,
    scheduled_redis_key,
)
from tests.test_messages import _sample_message  # reuse helper


def test_scheduled_redis_key():
    assert scheduled_redis_key("frappe.localhost") == "conductor:frappe.localhost:scheduled"


def test_schedule_message_zadds_with_score(fake_redis):
    msg = _sample_message()
    encoded = encode(msg)
    run_at_ms = 1735000000000  # explicit deterministic score
    schedule_message(fake_redis, "frappe.localhost", encoded, run_at_ms)
    items = fake_redis.zrange(scheduled_redis_key("frappe.localhost"), 0, -1, withscores=True)
    assert len(items) == 1
    member, score = items[0]
    assert json.loads(member.decode()) == encoded
    assert int(score) == run_at_ms


def test_drain_due_messages_pulls_only_due(fake_redis):
    msg_due = encode(_sample_message().replace(job_id="due-1"))
    msg_future = encode(_sample_message().replace(job_id="future-1"))
    now_ms = int(time.time() * 1000)
    schedule_message(fake_redis, "frappe.localhost", msg_due, now_ms - 1000)
    schedule_message(fake_redis, "frappe.localhost", msg_future, now_ms + 60_000)

    drained = drain_due_messages(fake_redis, "frappe.localhost", now_ms=now_ms)
    assert len(drained) == 1
    assert drained[0]["job_id"] == "due-1"
    # Drained items are removed from the ZSET; future ones remain.
    remaining = fake_redis.zrange(scheduled_redis_key("frappe.localhost"), 0, -1)
    assert len(remaining) == 1
    assert json.loads(remaining[0].decode())["job_id"] == "future-1"


def test_drain_with_empty_zset_returns_empty_list(fake_redis):
    drained = drain_due_messages(fake_redis, "frappe.localhost", now_ms=int(time.time() * 1000))
    assert drained == []
