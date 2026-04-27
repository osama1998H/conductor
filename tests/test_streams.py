"""Unit tests for conductor.streams — Redis key builders and group helpers."""

import pytest
import redis as redis_mod

from conductor.streams import (
    CONSUMER_GROUP,
    dlq_key,
    ensure_consumer_group,
    scheduled_key,
    stream_key,
    workers_key,
)


def test_stream_key_builds_namespaced_key():
    assert stream_key("frappe.localhost", "default") == "conductor:frappe.localhost:stream:default"


def test_dlq_key_builds_namespaced_key():
    assert dlq_key("frappe.localhost", "critical") == "conductor:frappe.localhost:dlq:critical"


def test_scheduled_key_builds_namespaced_key():
    assert scheduled_key("aau.local") == "conductor:aau.local:scheduled"


def test_workers_key_builds_namespaced_key():
    assert workers_key("aau.local") == "conductor:aau.local:workers"


def test_consumer_group_is_constant():
    assert CONSUMER_GROUP == "conductor"


def test_ensure_consumer_group_creates_when_missing(fake_redis):
    key = stream_key("test.local", "default")
    ensure_consumer_group(fake_redis, key)
    groups = fake_redis.xinfo_groups(key)
    assert any(g["name"] == CONSUMER_GROUP.encode() for g in groups)


def test_ensure_consumer_group_idempotent(fake_redis):
    key = stream_key("test.local", "default")
    ensure_consumer_group(fake_redis, key)
    ensure_consumer_group(fake_redis, key)  # must not raise
    groups = fake_redis.xinfo_groups(key)
    assert sum(1 for g in groups if g["name"] == CONSUMER_GROUP.encode()) == 1


def test_ensure_consumer_group_propagates_other_errors(monkeypatch, fake_redis):
    def boom(*a, **kw):
        raise redis_mod.exceptions.ResponseError("ERR something else")

    monkeypatch.setattr(fake_redis, "xgroup_create", boom)
    with pytest.raises(redis_mod.exceptions.ResponseError, match="something else"):
        ensure_consumer_group(fake_redis, stream_key("test.local", "default"))
