"""Tests for `bench conductor depth` table builder."""

from unittest.mock import MagicMock, patch

import pytest


def test_collect_depth_for_site_returns_one_row_per_queue(fake_redis):
    fake_redis.xadd("conductor:s1:stream:default", {"x": "1"})
    fake_redis.xadd("conductor:s1:stream:default", {"x": "2"})
    fake_redis.xadd("conductor:s1:dlq:default", {"x": "1"})
    fake_redis.zadd("conductor:s1:scheduled", {"a": 100.0, "b": 200.0})

    fake_queues = [
        type("Q", (), {"name": "default", "max_rps": 0, "max_concurrent": 0})(),
        type("Q", (), {"name": "long",    "max_rps": 0, "max_concurrent": 0})(),
    ]

    with patch("conductor.commands.depth._all_queues", return_value=fake_queues):
        from conductor.commands.depth import collect_depth_for_site
        rows = collect_depth_for_site(fake_redis, "s1")

    by_queue = {r["queue"]: r for r in rows}
    assert by_queue["default"]["stream_xlen"] == 2
    assert by_queue["default"]["dlq_xlen"] == 1
    assert by_queue["default"]["scheduled_zcard"] == 2  # site-level, repeated
    assert by_queue["default"]["inflight"] == 0
    assert by_queue["default"]["max_rps"] == 0
    assert by_queue["default"]["max_concurrent"] == 0
    assert by_queue["long"]["stream_xlen"] == 0


def test_collect_depth_for_site_reads_inflight_counter(fake_redis):
    fake_redis.set("conductor:s1:inflight:default", "3")
    fake_queues = [type("Q", (), {"name": "default", "max_rps": 0, "max_concurrent": 0})()]
    with patch("conductor.commands.depth._all_queues", return_value=fake_queues):
        from conductor.commands.depth import collect_depth_for_site
        rows = collect_depth_for_site(fake_redis, "s1")
    assert rows[0]["inflight"] == 3


def test_format_depth_table_renders_columns():
    from conductor.commands.depth import format_depth_table
    rows = [
        {"queue": "default", "stream_xlen": 5, "dlq_xlen": 0,
         "scheduled_zcard": 2, "inflight": 1, "max_rps": 0, "max_concurrent": 0},
    ]
    out = format_depth_table("alpha.test", rows)
    assert "alpha.test" in out
    assert "default" in out
    assert "5" in out
