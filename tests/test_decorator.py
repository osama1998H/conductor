"""Unit tests for conductor.decorator — @conductor.job + metadata extraction."""

from conductor.decorator import (
    JobMetadata,
    get_metadata,
    job,
)
from conductor.retry import RetryPolicy


def test_decorator_attaches_metadata():
    @job(queue="critical", max_attempts=5, backoff="linear", base_delay_seconds=3)
    def my_task(**kw):
        return kw

    meta = get_metadata(my_task)
    assert isinstance(meta, JobMetadata)
    assert meta.queue == "critical"
    assert meta.policy.max_attempts == 5
    assert meta.policy.backoff == "linear"
    assert meta.policy.base_delay_seconds == 3


def test_decorated_function_still_callable():
    @job(queue="default")
    def echo(**kw):
        return {"hi": kw}

    assert echo(x=1) == {"hi": {"x": 1}}


def test_undecorated_function_has_no_metadata():
    def plain():
        return None

    assert get_metadata(plain) is None


def test_decorator_default_policy_when_no_kwargs():
    @job()
    def t(): ...

    meta = get_metadata(t)
    assert meta.queue is None  # falls through to per-call > queue default
    assert meta.policy.max_attempts == 3
    assert meta.policy.backoff == "exponential"
    assert meta.idempotency_key_fn is None


def test_decorator_with_idempotency_key_callable():
    @job(idempotency_key=lambda invoice: f"invoice:{invoice}:email")
    def send(invoice: str): ...

    meta = get_metadata(send)
    assert meta.idempotency_key_fn("INV-001") == "invoice:INV-001:email"


def test_decorator_with_retry_on_no_retry_on():
    class _A(Exception): pass
    class _B(Exception): pass

    @job(retry_on=(_A,), no_retry_on=(_B,))
    def t(): ...

    meta = get_metadata(t)
    assert meta.policy.retry_on == (_A,)
    assert meta.policy.no_retry_on == (_B,)
