"""Workload functions used by the Conductor-vs-RQ KPI suite.

These live inside the `conductor` package so both engines can import them
through their normal worker bootstrap (Conductor's `frappe.get_attr` and
RQ's pickle path).

The `tests/comparative/workload.py` shim imports from here so the harness
side keeps working too.
"""

from __future__ import annotations

import os
import time

import frappe
from conductor.client import get_redis
from conductor.config import load_config


def _redis():
    cfg = load_config(frappe.local.conf)
    return get_redis(cfg.redis_url)


COUNTER_KEY = "kpi:counter:{name}"


def reset_counter(name: str) -> None:
    _redis().delete(COUNTER_KEY.format(name=name))


def get_counter(name: str) -> int:
    raw = _redis().get(COUNTER_KEY.format(name=name))
    return int(raw) if raw else 0


def slow_then_count(*, counter_name: str, sleep_seconds: float = 5.0, **_kwargs) -> str:
    """Sleep, then INCR a Redis counter. Used for KPI 1 (crash-survival)
    and KPI 6 (throughput at 500ms / 50ms)."""
    time.sleep(sleep_seconds)
    _redis().incr(COUNTER_KEY.format(name=counter_name))
    return f"ok:{os.getpid()}"


def echo(**_kwargs) -> int:
    """1ms job for KPI 6."""
    return 1


def transient_failure(*, attempt_key: str, fail_attempts: int = 2, **_kwargs) -> str:
    """Fail the first N attempts via Redis-backed attempt counter keyed by
    `attempt_key`, then succeed. The attempt counter is shared across retries
    so the same logical job "learns" across attempts.
    Used for KPI 1 (transient-recovery rate)."""
    r = _redis()
    counter_key = f"kpi:attempts:{attempt_key}"
    attempt = r.incr(counter_key)
    r.expire(counter_key, 600)
    if attempt <= fail_attempts:
        raise ConnectionError(f"flaky attempt {attempt}/{fail_attempts}")
    return f"ok-after-{attempt}"


def always_fail(*, counter_name: str, **_kwargs) -> str:
    """Always raise. Used for KPI 3 (audit) and KPI 4 (DLQ visibility)."""
    _redis().incr(COUNTER_KEY.format(name=counter_name))
    raise RuntimeError("always_fail")


def increment_only(*, counter_name: str, **_kwargs) -> int:
    """For KPI 5 (idempotency under concurrent producers)."""
    return _redis().incr(COUNTER_KEY.format(name=counter_name))
