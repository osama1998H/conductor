"""Unit tests for conductor.inflight — concurrency-cap counter scripts.

acquire     INCRs only when current < cap; returns (acquired, current).
release     DECRs floored at 0.
correct_drift   subtract N atomically, floor at 0 — used by reaper after
                marking workers GONE.
"""

import pytest

from conductor.inflight import (
    acquire,
    correct_drift,
    get_count,
    inflight_key,
    release,
)


def test_inflight_key_format():
    assert inflight_key("alpha.test", "default") == "conductor:alpha.test:inflight:default"


def test_acquire_under_cap_increments_and_returns_acquired(fake_redis):
    acquired, cur = acquire(fake_redis, "s", "q", max_concurrent=3)
    assert acquired is True
    assert cur == 1
    acquired, cur = acquire(fake_redis, "s", "q", max_concurrent=3)
    assert acquired is True
    assert cur == 2


def test_acquire_at_cap_rejects_without_modifying_state(fake_redis):
    for _ in range(3):
        acquire(fake_redis, "s", "q", max_concurrent=3)
    acquired, cur = acquire(fake_redis, "s", "q", max_concurrent=3)
    assert acquired is False
    assert cur == 3
    # Counter not bumped above cap
    assert get_count(fake_redis, "s", "q") == 3


def test_release_decrements(fake_redis):
    for _ in range(3):
        acquire(fake_redis, "s", "q", max_concurrent=3)
    new = release(fake_redis, "s", "q")
    assert new == 2


def test_release_floors_at_zero(fake_redis):
    # Release without prior acquire — should floor at 0, not go negative
    new = release(fake_redis, "s", "q")
    assert new == 0
    new = release(fake_redis, "s", "q")
    assert new == 0


def test_correct_drift_subtracts_and_floors(fake_redis):
    for _ in range(5):
        acquire(fake_redis, "s", "q", max_concurrent=10)
    new = correct_drift(fake_redis, "s", "q", decrement_by=2)
    assert new == 3
    new = correct_drift(fake_redis, "s", "q", decrement_by=10)
    assert new == 0  # floored, not -7


def test_correct_drift_on_missing_key(fake_redis):
    new = correct_drift(fake_redis, "s", "q", decrement_by=5)
    assert new == 0


def test_isolation_per_site_and_queue(fake_redis):
    for _ in range(3):
        acquire(fake_redis, "s1", "q1", max_concurrent=3)
    acquired_other, cur = acquire(fake_redis, "s1", "q2", max_concurrent=3)
    assert acquired_other is True
    assert cur == 1
    acquired_other, cur = acquire(fake_redis, "s2", "q1", max_concurrent=3)
    assert acquired_other is True
    assert cur == 1


def test_get_count_returns_zero_for_missing_key(fake_redis):
    assert get_count(fake_redis, "s", "q") == 0
