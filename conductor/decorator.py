"""@conductor.job decorator: declarative defaults attached to a function.

Stores a JobMetadata sidecar on the function via the `_CONDUCTOR_META_ATTR`
attribute. Dispatcher reads it via `get_metadata(func)` to resolve the
effective RetryPolicy, queue, timeout, and idempotency_key (which may be a
callable that takes the same kwargs as the dispatched function).

Per spec P1-4: metadata is stamped INTO the JobMessage at dispatch time; the
worker reads the message, not the live decorator. This lets in-flight retries
preserve their dispatch-time policy across redeploys.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from conductor.retry import RetryPolicy

_CONDUCTOR_META_ATTR = "__conductor_metadata__"


@dataclass(frozen=True)
class JobMetadata:
    queue: Optional[str]
    timeout: Optional[int]
    policy: RetryPolicy
    idempotency_key_fn: Optional[Callable[..., str]]


def job(
    *,
    queue: Optional[str] = None,
    timeout: Optional[int] = None,
    max_attempts: Optional[int] = None,
    backoff: Optional[str] = None,
    base_delay_seconds: Optional[int] = None,
    max_delay_seconds: Optional[int] = None,
    jitter: Optional[str] = None,
    idempotency_key: Optional[Callable[..., str]] = None,
    retry_on: Optional[tuple[type[BaseException], ...]] = None,
    no_retry_on: Optional[tuple[type[BaseException], ...]] = None,
) -> Callable[[Callable], Callable]:
    """Decorator that attaches a JobMetadata sidecar to the wrapped function."""
    policy_kwargs: dict[str, Any] = {}
    if max_attempts is not None: policy_kwargs["max_attempts"] = max_attempts
    if backoff is not None: policy_kwargs["backoff"] = backoff
    if base_delay_seconds is not None: policy_kwargs["base_delay_seconds"] = base_delay_seconds
    if max_delay_seconds is not None: policy_kwargs["max_delay_seconds"] = max_delay_seconds
    if jitter is not None: policy_kwargs["jitter"] = jitter
    if retry_on is not None: policy_kwargs["retry_on"] = retry_on
    if no_retry_on is not None: policy_kwargs["no_retry_on"] = no_retry_on
    policy = RetryPolicy(**policy_kwargs)

    meta = JobMetadata(
        queue=queue,
        timeout=timeout,
        policy=policy,
        idempotency_key_fn=idempotency_key,
    )

    def decorate(func: Callable) -> Callable:
        setattr(func, _CONDUCTOR_META_ATTR, meta)
        return func

    return decorate


def get_metadata(func: Callable) -> Optional[JobMetadata]:
    return getattr(func, _CONDUCTOR_META_ATTR, None)
