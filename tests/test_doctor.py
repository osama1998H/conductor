"""Tests for `bench conductor doctor`'s takeover queue-coverage check.

The check fires only when `conductor_take_over_frappe_scheduler` is set.
It computes the set of queues the takeover loop's queue-map produces,
takes a list of heartbeat-fresh `Conductor Worker` rows from the caller,
and warns when any queue from the takeover set is not covered by an
active worker."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


def test_takeover_queue_coverage_passes_when_workers_cover_every_queue():
    """When given fresh workers covering every required queue → check passes."""
    from conductor.doctor import check_takeover_queue_coverage

    fresh_workers = [
        {"name": "w1", "queues": json.dumps(["default"])},
        {"name": "w2", "queues": json.dumps(["long"])},
    ]
    result = check_takeover_queue_coverage(
        takeover_enabled=True,
        queue_map={
            "All": "default", "Cron": "default", "Hourly": "default",
            "Daily": "long",  "Weekly": "long", "Monthly": "long",
        },
        fresh_workers=fresh_workers,
    )
    assert result.ok is True
    assert "default" in result.detail
    assert "long" in result.detail


def test_takeover_queue_coverage_fails_when_long_queue_uncovered():
    """When fresh workers miss `long`, check fails, names it, and the
    operator-facing suggestion uses repeated `--queue` flags (not a
    comma-joined value, which Click would parse as one literal queue
    name)."""
    from conductor.doctor import check_takeover_queue_coverage

    fresh_workers = [
        {"name": "w1", "queues": json.dumps(["default"])},
    ]
    result = check_takeover_queue_coverage(
        takeover_enabled=True,
        queue_map={"Daily": "long", "Hourly": "default"},
        fresh_workers=fresh_workers,
    )
    assert result.ok is False
    assert "long" in result.detail
    assert "uncovered" in result.detail.lower() or "missing" in result.detail.lower()
    # Pin the CLI syntax: `--queue long`, not `--queue long,` or comma-joined.
    assert "--queue long" in result.detail


def test_takeover_queue_coverage_skipped_when_takeover_disabled():
    """When takeover flag is unset, the check is a no-op → ok=True."""
    from conductor.doctor import check_takeover_queue_coverage

    result = check_takeover_queue_coverage(
        takeover_enabled=False,
        queue_map={"Daily": "long"},
        fresh_workers=[],
    )
    assert result.ok is True
    assert "skipped" in result.detail.lower() or "disabled" in result.detail.lower()


def test_fetch_fresh_workers_filters_by_utc_naive_threshold():
    """`_fetch_fresh_workers` builds a UTC-naive heartbeat threshold
    (matching `conductor.worker._now_naive`'s write path) and passes it
    to `frappe.get_all` as a `[">=", threshold]` filter. Staleness is
    enforced at the SQL level — `check_takeover_queue_coverage` itself
    knows nothing about staleness."""
    from conductor.doctor import _fetch_fresh_workers, WORKER_FRESHNESS_SECONDS

    captured = {}

    def fake_get_all(doctype, **kwargs):
        captured["doctype"] = doctype
        captured["filters"] = kwargs.get("filters")
        captured["fields"] = kwargs.get("fields")
        return [{"name": "w1", "queues": '["default"]', "last_heartbeat": None}]

    with patch("conductor.doctor.frappe.get_all", side_effect=fake_get_all):
        rows = _fetch_fresh_workers()

    assert captured["doctype"] == "Conductor Worker"
    assert "queues" in captured["fields"]
    op, threshold = captured["filters"]["last_heartbeat"]
    assert op == ">="
    # Threshold is UTC-naive — pins the b1ea19b TZ fix against regression.
    assert threshold.tzinfo is None
    expected = (
        datetime.now(timezone.utc).replace(tzinfo=None)
        - timedelta(seconds=WORKER_FRESHNESS_SECONDS)
    )
    # Allow a few seconds of slack for test execution time.
    assert abs((expected - threshold).total_seconds()) < 5
    # Returned rows do NOT carry a synthetic `stale` field.
    assert rows == [{"name": "w1", "queues": '["default"]'}]
    assert "stale" not in rows[0]
