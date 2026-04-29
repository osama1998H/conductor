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


# Phase 6: stream-key → site routing for pool worker.
from conductor.streams import parse_site_from_stream_key


def test_parse_site_from_stream_key_round_trip():
    skey = stream_key("frappe.localhost", "default")
    assert parse_site_from_stream_key(skey) == "frappe.localhost"


def test_parse_site_handles_dotted_site_names():
    skey = stream_key("alpha.tenant.example.com", "long")
    assert parse_site_from_stream_key(skey) == "alpha.tenant.example.com"


def test_parse_site_handles_queue_named_with_colons_unlikely_but_robust():
    # We don't allow colons in queue names by convention, but the parser is
    # written to take everything BEFORE :stream: as site.
    skey = "conductor:site.example:stream:default"
    assert parse_site_from_stream_key(skey) == "site.example"


def test_parse_site_raises_on_bytes_input():
    with pytest.raises(TypeError):
        parse_site_from_stream_key(b"conductor:s:stream:q")


def test_parse_site_raises_on_malformed_key():
    with pytest.raises(ValueError, match="not a conductor stream key"):
        parse_site_from_stream_key("conductor:foo:bar")
    with pytest.raises(ValueError, match="not a conductor stream key"):
        parse_site_from_stream_key("conductor:site:dlq:default")  # DLQ, not stream
    with pytest.raises(ValueError, match="not a conductor stream key"):
        parse_site_from_stream_key("redis:other:stream:foo")
