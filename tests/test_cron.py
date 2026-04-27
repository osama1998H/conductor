"""Unit tests for conductor.cron — compute_next_run_at."""

from datetime import datetime, timezone

import pytest

from croniter import CroniterBadCronError

from conductor.cron import compute_next_run_at


def test_every_minute_utc_returns_within_60s():
    base = datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc)
    nxt = compute_next_run_at("* * * * *", "UTC", base=base)
    assert nxt.tzinfo is not None
    assert nxt > base
    assert (nxt - base).total_seconds() <= 60


def test_hourly_macro_returns_top_of_next_hour():
    base = datetime(2026, 4, 27, 12, 30, 0, tzinfo=timezone.utc)
    nxt = compute_next_run_at("@hourly", "UTC", base=base)
    assert nxt == datetime(2026, 4, 27, 13, 0, 0, tzinfo=timezone.utc)


def test_daily_at_9am_in_new_york_returns_correct_utc():
    # 9 AM Eastern in late April is EDT (UTC-4) → 13:00 UTC.
    # base = 14:00 UTC = 10:00 EDT (after 9 AM local), so next fire rolls to Apr 28.
    base = datetime(2026, 4, 27, 14, 0, 0, tzinfo=timezone.utc)
    nxt = compute_next_run_at("0 9 * * *", "America/New_York", base=base)
    assert nxt.tzinfo is not None
    assert nxt.astimezone(timezone.utc) == datetime(2026, 4, 28, 13, 0, 0, tzinfo=timezone.utc)


def test_daily_at_9am_in_new_york_during_winter():
    # In January, NY is EST (UTC-5) → 9 AM ET = 14:00 UTC.
    # base = 15:00 UTC = 10:00 EST (after 9 AM local), so next fire rolls to Jan 16.
    base = datetime(2026, 1, 15, 15, 0, 0, tzinfo=timezone.utc)
    nxt = compute_next_run_at("0 9 * * *", "America/New_York", base=base)
    assert nxt.astimezone(timezone.utc) == datetime(2026, 1, 16, 14, 0, 0, tzinfo=timezone.utc)


def test_naive_base_is_treated_as_utc():
    base = datetime(2026, 4, 27, 12, 0, 0)  # naive
    nxt = compute_next_run_at("@hourly", "UTC", base=base)
    assert nxt.tzinfo is not None
    assert nxt.astimezone(timezone.utc) == datetime(2026, 4, 27, 13, 0, 0, tzinfo=timezone.utc)


def test_unknown_timezone_falls_back_to_utc():
    base = datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc)
    nxt = compute_next_run_at("@hourly", "Mars/Olympus_Mons", base=base)
    assert nxt.astimezone(timezone.utc) == datetime(2026, 4, 27, 13, 0, 0, tzinfo=timezone.utc)


def test_malformed_expression_raises():
    with pytest.raises(CroniterBadCronError):
        compute_next_run_at("not a cron", "UTC")


def test_default_base_is_now_utc():
    nxt = compute_next_run_at("* * * * *", "UTC")
    assert nxt.tzinfo is not None
    # Should be within next 60s of "now"
    delta = (nxt - datetime.now(timezone.utc)).total_seconds()
    assert -1 <= delta <= 61
