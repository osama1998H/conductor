"""Unit tests for conductor.retry — RetryPolicy, delays, retry decisions."""

import pytest

from conductor.retry import RetryPolicy


class _RetryableError(Exception):
    pass


class _UserError(Exception):
    pass


def test_default_policy_values():
    p = RetryPolicy()
    assert p.max_attempts == 3
    assert p.backoff == "exponential"
    assert p.base_delay_seconds == 2
    assert p.max_delay_seconds == 600
    assert p.jitter == "full"


def test_exponential_backoff_no_jitter():
    p = RetryPolicy(backoff="exponential", base_delay_seconds=2, max_delay_seconds=1000, jitter="none")
    assert p.compute_next_delay(1) == 2
    assert p.compute_next_delay(2) == 4
    assert p.compute_next_delay(3) == 8
    assert p.compute_next_delay(4) == 16


def test_linear_backoff_no_jitter():
    p = RetryPolicy(backoff="linear", base_delay_seconds=3, max_delay_seconds=100, jitter="none")
    assert p.compute_next_delay(1) == 3
    assert p.compute_next_delay(2) == 6
    assert p.compute_next_delay(3) == 9


def test_fixed_backoff_no_jitter():
    p = RetryPolicy(backoff="fixed", base_delay_seconds=5, jitter="none")
    assert p.compute_next_delay(1) == 5
    assert p.compute_next_delay(7) == 5


def test_max_delay_clamps():
    p = RetryPolicy(backoff="exponential", base_delay_seconds=10, max_delay_seconds=50, jitter="none")
    assert p.compute_next_delay(10) == 50  # clamped


def test_full_jitter_bounds():
    p = RetryPolicy(backoff="exponential", base_delay_seconds=4, max_delay_seconds=100, jitter="full")
    for _ in range(50):
        d = p.compute_next_delay(2)  # base * 2^1 = 8 → jitter to [0, 8]
        assert 0 <= d <= 8


def test_equal_jitter_bounds():
    p = RetryPolicy(backoff="exponential", base_delay_seconds=4, max_delay_seconds=100, jitter="equal")
    for _ in range(50):
        d = p.compute_next_delay(2)  # base = 8 → jitter to [4, 8]
        assert 4 <= d <= 8


def test_should_retry_default_retries_any_exception():
    p = RetryPolicy(max_attempts=3)
    assert p.should_retry(RuntimeError("x"), attempt=1) is True
    assert p.should_retry(RuntimeError("x"), attempt=2) is True
    assert p.should_retry(RuntimeError("x"), attempt=3) is False  # exhausted


def test_should_retry_respects_no_retry_on():
    p = RetryPolicy(max_attempts=10, no_retry_on=(_UserError,))
    assert p.should_retry(_UserError("bad input"), attempt=1) is False
    assert p.should_retry(_RetryableError("blip"), attempt=1) is True


def test_no_retry_on_wins_over_retry_on():
    """If a class matches both, no_retry_on wins — user errors are never retried."""
    class Both(_RetryableError, _UserError):
        pass

    p = RetryPolicy(retry_on=(_RetryableError,), no_retry_on=(_UserError,))
    assert p.should_retry(Both("x"), attempt=1) is False


def test_should_retry_respects_retry_on_filter():
    p = RetryPolicy(retry_on=(_RetryableError,))
    assert p.should_retry(_RetryableError("x"), attempt=1) is True
    assert p.should_retry(RuntimeError("x"), attempt=1) is False


def test_max_attempts_zero_means_no_retries():
    p = RetryPolicy(max_attempts=1)
    assert p.should_retry(RuntimeError("x"), attempt=1) is False
