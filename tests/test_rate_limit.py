"""Unit tests for the take_token rate-limit script.

Uses fakeredis, which supports Lua scripting against its in-memory state.
Time is controlled by passing now_ms explicitly into take_token() — no real
sleeps in the unit tests.
"""

import pytest

from conductor.rate_limit import rate_key, take_token


def test_rate_key_format():
    assert rate_key("alpha.test", "default") == "conductor:alpha.test:rate:default"


def test_first_call_allowed_with_full_bucket(fake_redis):
    allowed, retry_ms = take_token(
        fake_redis, "alpha.test", "q1",
        max_tokens=10, refill_per_sec=10, now_ms=1_000_000_000_000,
    )
    assert allowed is True
    assert retry_ms == 0


def test_exhaust_bucket_then_deny(fake_redis):
    now = 1_000_000_000_000
    for _ in range(10):
        allowed, _ = take_token(fake_redis, "s", "q", max_tokens=10,
                                 refill_per_sec=10, now_ms=now)
        assert allowed is True
    allowed, retry_ms = take_token(fake_redis, "s", "q", max_tokens=10,
                                    refill_per_sec=10, now_ms=now)
    assert allowed is False
    assert retry_ms > 0


def test_refill_after_elapsed_time(fake_redis):
    now = 1_000_000_000_000
    # Drain 10 tokens
    for _ in range(10):
        take_token(fake_redis, "s", "q", max_tokens=10, refill_per_sec=10, now_ms=now)
    # Advance simulated clock 1 full second → 10 tokens refill
    later = now + 1000
    allowed, retry_ms = take_token(fake_redis, "s", "q", max_tokens=10,
                                    refill_per_sec=10, now_ms=later)
    assert allowed is True
    assert retry_ms == 0


def test_partial_refill_yields_partial_capacity(fake_redis):
    now = 1_000_000_000_000
    for _ in range(10):
        take_token(fake_redis, "s", "q", max_tokens=10, refill_per_sec=10, now_ms=now)
    # 500ms later → 5 tokens
    mid = now + 500
    granted = 0
    for _ in range(10):
        allowed, _ = take_token(fake_redis, "s", "q", max_tokens=10,
                                 refill_per_sec=10, now_ms=mid)
        if allowed:
            granted += 1
        else:
            break
    assert granted == 5


def test_retry_after_ms_proportional_to_missing_tokens(fake_redis):
    now = 1_000_000_000_000
    for _ in range(10):
        take_token(fake_redis, "s", "q", max_tokens=10, refill_per_sec=10, now_ms=now)
    allowed, retry_ms = take_token(fake_redis, "s", "q", max_tokens=10,
                                    refill_per_sec=10, now_ms=now)
    # Need 1 token at 10 per sec → 100 ms
    assert allowed is False
    assert 90 <= retry_ms <= 110


def test_keys_isolated_per_site_and_queue(fake_redis):
    now = 1_000_000_000_000
    # Drain (s1,q1)
    for _ in range(10):
        take_token(fake_redis, "s1", "q1", max_tokens=10, refill_per_sec=10, now_ms=now)
    # (s1,q2) and (s2,q1) untouched — should still allow
    allowed_other_q, _ = take_token(fake_redis, "s1", "q2",
                                      max_tokens=10, refill_per_sec=10, now_ms=now)
    allowed_other_s, _ = take_token(fake_redis, "s2", "q1",
                                      max_tokens=10, refill_per_sec=10, now_ms=now)
    assert allowed_other_q is True
    assert allowed_other_s is True


def test_take_token_with_n_greater_than_one(fake_redis):
    now = 1_000_000_000_000
    allowed, _ = take_token(fake_redis, "s", "q", max_tokens=10,
                             refill_per_sec=10, now_ms=now, n=5)
    assert allowed is True
    allowed, _ = take_token(fake_redis, "s", "q", max_tokens=10,
                             refill_per_sec=10, now_ms=now, n=5)
    assert allowed is True
    allowed, retry_ms = take_token(fake_redis, "s", "q", max_tokens=10,
                                    refill_per_sec=10, now_ms=now, n=1)
    assert allowed is False
    assert retry_ms > 0
