"""Tests for `bench conductor doctor`'s takeover queue-coverage check.

The check fires only when `conductor_take_over_frappe_scheduler` is set.
It computes the set of queues the takeover loop's queue-map produces,
introspects heartbeat-fresh `Conductor Worker` rows, and warns when any
queue from the takeover set is not covered by an active worker."""

from __future__ import annotations

import json
from unittest.mock import patch


def test_takeover_queue_coverage_passes_when_workers_cover_every_queue():
    """The default queue-map produces {default, long}. Two heartbeat-fresh
    workers between them covering both queues → check passes."""
    from conductor.doctor import check_takeover_queue_coverage

    workers = [
        {"name": "w1", "queues": json.dumps(["default"]), "stale": False},
        {"name": "w2", "queues": json.dumps(["long"]),    "stale": False},
    ]

    with patch("conductor.doctor._fetch_fresh_workers", return_value=workers):
        result = check_takeover_queue_coverage(
            takeover_enabled=True,
            queue_map={
                "All": "default", "Cron": "default", "Hourly": "default",
                "Daily": "long",  "Weekly": "long", "Monthly": "long",
            },
        )

    assert result.ok is True
    assert "default" in result.detail
    assert "long" in result.detail


def test_takeover_queue_coverage_fails_when_long_queue_uncovered():
    """One worker covers only `default`. The map produces `long` too →
    check fails and names the missing queue."""
    from conductor.doctor import check_takeover_queue_coverage

    workers = [
        {"name": "w1", "queues": json.dumps(["default"]), "stale": False},
    ]

    with patch("conductor.doctor._fetch_fresh_workers", return_value=workers):
        result = check_takeover_queue_coverage(
            takeover_enabled=True,
            queue_map={"Daily": "long", "Hourly": "default"},
        )

    assert result.ok is False
    assert "long" in result.detail
    assert "uncovered" in result.detail.lower() or "missing" in result.detail.lower()


def test_takeover_queue_coverage_skipped_when_takeover_disabled():
    """When the takeover flag is unset, the check is a no-op → ok=True with
    a "skipped" detail string. Doctor must not fail on benches that have
    not opted in."""
    from conductor.doctor import check_takeover_queue_coverage

    result = check_takeover_queue_coverage(
        takeover_enabled=False,
        queue_map={"Daily": "long"},
    )

    assert result.ok is True
    assert "skipped" in result.detail.lower() or "disabled" in result.detail.lower()


def test_takeover_queue_coverage_ignores_stale_workers():
    """A worker whose last heartbeat is older than the freshness threshold
    must NOT count toward queue coverage."""
    from conductor.doctor import check_takeover_queue_coverage

    workers = [
        {"name": "stale-w", "queues": json.dumps(["default", "long"]), "stale": True},
        {"name": "fresh-w", "queues": json.dumps(["default"]),         "stale": False},
    ]

    with patch("conductor.doctor._fetch_fresh_workers", return_value=workers):
        result = check_takeover_queue_coverage(
            takeover_enabled=True,
            queue_map={"Daily": "long", "Hourly": "default"},
        )

    assert result.ok is False
    assert "long" in result.detail
