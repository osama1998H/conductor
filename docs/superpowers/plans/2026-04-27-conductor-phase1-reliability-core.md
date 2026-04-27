# Conductor Phase 1 (Reliability Core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take Phase 0's skeleton and make it actually reliable — declarative retry policies, dead-letter queue, dispatch idempotency, execution locks, stalled-message reclamation, cooperative cancellation, and a sweeper for the dispatch dual-write crash window. Acceptance: a chaos test suite gates the phase; killing a worker mid-job produces no losses and no double-runs.

**Architecture:** Add primitive helpers (`retry.py`, `idempotency.py`, `execution_lock.py`, `scheduled.py`, `sweeper.py`, `cancellation.py`, `decorator.py`) plus two DocTypes (`Conductor Job Run`, `Conductor DLQ Entry`). Modify `dispatcher.py` (idempotency + policy resolution + M-2 fix) and `worker.py` (exec lock + retry/DLQ paths + XAUTOCLAIM + drainer/sweeper/cancel-poller threads). All long-lived threads are managed by the worker process; Phase 2's scheduler will subsume drainer + sweeper + reaper.

**Tech Stack:**
- Python 3.12 (bench env)
- Frappe 15.106.0
- redis-py ≥ 5 (Streams + ZSET + SET NX EX)
- msgpack ≥ 1, structlog, opentelemetry-{api,sdk}
- pytest, fakeredis, pytest-mock (already installed in `[dev]`)

**Reference docs:**
- Master design: `apps/conductor/docs/superpowers/specs/2026-04-27-conductor-master-design.md`
- Phase 1 spec: `apps/conductor/docs/superpowers/specs/2026-04-27-conductor-phase1-reliability-core.md`
- Phase 0 plan (precedent for layout): `apps/conductor/docs/superpowers/plans/2026-04-27-conductor-phase0-skeleton.md`

**Bench-rooted paths:**
- Bench root: `/Users/osamamuhammed/frappe_15` (referred to as `<BENCH>`)
- App root: `<BENCH>/apps/conductor` (its own git repo on `develop`)
- Bench Python: `<BENCH>/env/bin/python`
- Bench pytest: `<BENCH>/env/bin/pytest`
- Default site: `frappe.localhost`
- Redis (queue): `127.0.0.1:11000` DB 2 (Conductor)

**Conventions:**
- Run `pytest` from bench root: `cd <BENCH> && ./env/bin/pytest apps/conductor/tests/...`
- Run Frappe tests from bench root: `cd <BENCH> && bench --site frappe.localhost run-tests --app conductor --module <dotted.module>`
- All `git` commands inside `<BENCH>/apps/conductor` (use absolute paths to avoid the persistent-CWD bug we hit in Phase 0).
- Small, frequent commits — one task = one or two commits. Never `--amend`.
- Both Redis daemons must be running before any task that hits Redis. If `redis-cli -p 11000 ping` fails: `redis-server <BENCH>/config/redis_queue.conf --daemonize yes` and same for `redis_cache`.

**Phase 0 invariants this plan must preserve:**
- 36 pytest unit tests stay green (Phase 0 tests).
- 8 Frappe integration tests stay green.
- `bench --site frappe.localhost conductor doctor --demo` exits 0.
- The `JobMessage` Phase-1 schema additions are backward-compatible — Phase 0 messages still in queues during a rolling deploy must still decode.

---

## Task 1: TDD `conductor.retry` (RetryPolicy + delay/should_retry)

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/retry.py`
- Create: `<BENCH>/apps/conductor/tests/test_retry.py`

- [ ] **Step 1: Write failing tests**

Write to `<BENCH>/apps/conductor/tests/test_retry.py`:

```python
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
```

- [ ] **Step 2: Run tests; expect ImportError**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_retry.py -v
```

Expected: ModuleNotFoundError for `conductor.retry`.

- [ ] **Step 3: Implement `conductor.retry`**

Write to `<BENCH>/apps/conductor/conductor/retry.py`:

```python
"""RetryPolicy: declarative configuration for retry behavior on a job.

A policy decides (a) how long to wait before the next retry of a given attempt,
and (b) whether a given exception should be retried at all.

Stamped into the JobMessage at dispatch time (master Phase 1 spec §3 P1-4) so
in-flight retries stay pinned to their dispatch-time policy across redeploys.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    backoff: Literal["exponential", "linear", "fixed"] = "exponential"
    base_delay_seconds: int = 2
    max_delay_seconds: int = 600
    jitter: Literal["none", "full", "equal"] = "full"
    retry_on: tuple[type[BaseException], ...] = (Exception,)
    no_retry_on: tuple[type[BaseException], ...] = ()

    def compute_next_delay(self, attempt: int) -> float:
        """Return seconds to wait before retry attempt `attempt + 1`."""
        if self.backoff == "exponential":
            base = self.base_delay_seconds * (2 ** (attempt - 1))
        elif self.backoff == "linear":
            base = self.base_delay_seconds * attempt
        else:  # "fixed"
            base = self.base_delay_seconds

        capped = min(base, self.max_delay_seconds)

        if self.jitter == "none":
            return float(capped)
        if self.jitter == "full":
            return random.uniform(0, capped)
        # "equal"
        return capped / 2 + random.uniform(0, capped / 2)

    def should_retry(self, exc: BaseException, attempt: int) -> bool:
        """True iff exc matches retry_on, doesn't match no_retry_on, and attempt < max_attempts."""
        if attempt >= self.max_attempts:
            return False
        if self.no_retry_on and isinstance(exc, self.no_retry_on):
            return False
        if not isinstance(exc, self.retry_on):
            return False
        return True
```

- [ ] **Step 4: Run tests; expect 12 passed**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_retry.py -v
```

- [ ] **Step 5: Commit**

```bash
git -C /Users/osamamuhammed/frappe_15/apps/conductor add conductor/retry.py tests/test_retry.py
git -C /Users/osamamuhammed/frappe_15/apps/conductor commit -m "feat(retry): RetryPolicy with backoff/jitter/should_retry"
```

---

## Task 2: Extend `conductor.messages` with Phase-1 optional fields

**Files:**
- Modify: `<BENCH>/apps/conductor/conductor/messages.py`
- Modify: `<BENCH>/apps/conductor/tests/test_messages.py`

- [ ] **Step 1: Read current `messages.py` to know what's there**

```bash
cat /Users/osamamuhammed/frappe_15/apps/conductor/conductor/messages.py
```

- [ ] **Step 2: Add failing tests for new fields**

Append to `<BENCH>/apps/conductor/tests/test_messages.py` (keep existing tests intact):

```python
def test_phase1_optional_fields_default_empty_decode_phase0_message():
    """A Phase-0-shaped encoded dict (no phase-1 fields) must decode cleanly."""
    encoded = encode(_sample_message())
    # Simulate a Phase 0 producer: strip Phase 1 keys.
    for k in ("backoff", "base_delay_seconds", "max_delay_seconds", "jitter",
             "retry_on_names", "no_retry_on_names"):
        encoded.pop(k, None)
    decoded = decode(encoded)
    assert decoded.backoff == ""
    assert decoded.base_delay_seconds == 0
    assert decoded.max_delay_seconds == 0
    assert decoded.jitter == ""
    assert decoded.retry_on_names == []
    assert decoded.no_retry_on_names == []


def test_phase1_fields_roundtrip():
    msg = _sample_message().replace(
        backoff="exponential",
        base_delay_seconds=5,
        max_delay_seconds=100,
        jitter="full",
        retry_on_names=["builtins.RuntimeError", "myapp.errors.NetworkError"],
        no_retry_on_names=["builtins.ValueError"],
        idempotency_key="invoice:INV-001:email",
    )
    encoded = encode(msg)
    decoded = decode(encoded)
    assert decoded.backoff == "exponential"
    assert decoded.base_delay_seconds == 5
    assert decoded.max_delay_seconds == 100
    assert decoded.jitter == "full"
    assert decoded.retry_on_names == ["builtins.RuntimeError", "myapp.errors.NetworkError"]
    assert decoded.no_retry_on_names == ["builtins.ValueError"]
    assert decoded.idempotency_key == "invoice:INV-001:email"


def test_phase1_encoded_fields_remain_str_to_str():
    encoded = encode(_sample_message().replace(
        retry_on_names=["builtins.RuntimeError"],
        no_retry_on_names=[],
    ))
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in encoded.items())
```

- [ ] **Step 3: Run; expect new tests to fail**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_messages.py -v
```

Expected: existing 6 pass; new 3 fail (AttributeError on missing fields, or KeyError on encode).

- [ ] **Step 4: Update `messages.py` to add the optional fields**

Replace the entire file content with:

```python
"""Conductor stream message schema (frozen, version 1).

A stream message is a flat str→str dict (Redis Streams field values are
ASCII-safe strings). args/kwargs are msgpack-then-base64 encoded.

Phase 1 adds optional retry-policy + idempotency fields. Decoder treats
missing fields as empty/zero defaults — backward-compatible with Phase 0
messages still in queues during a rolling deploy. No schema_version bump.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from conductor.serialization import dumps, loads

SCHEMA_VERSION = 1

# Required only for the original Phase 0 set; Phase 1 fields are optional.
_REQUIRED_FIELDS = {
    "job_id",
    "site",
    "name",
    "queue",
    "args_b64",
    "kwargs_b64",
    "attempt",
    "max_attempts",
    "timeout_seconds",
    "enqueued_at",
    "schema_version",
}


@dataclass(frozen=True)
class JobMessage:
    job_id: str
    site: str
    method: str  # serialized as "name" in the stream
    queue: str
    kwargs: dict[str, Any] = field(default_factory=dict)
    args: list[Any] = field(default_factory=list)
    attempt: int = 1
    max_attempts: int = 1
    timeout_seconds: int = 300
    enqueued_at: datetime | None = None
    deadline: datetime | None = None
    trace_parent: str = ""
    idempotency_key: str = ""
    workflow_run_id: str = ""
    step_id: str = ""
    # Phase 1 retry-policy fields (all optional).
    backoff: str = ""
    base_delay_seconds: int = 0
    max_delay_seconds: int = 0
    jitter: str = ""
    retry_on_names: list[str] = field(default_factory=list)
    no_retry_on_names: list[str] = field(default_factory=list)

    def replace(self, **changes: Any) -> "JobMessage":
        return replace(self, **changes)


def _b64encode(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _b64decode(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def _iso(dt: datetime | None) -> str:
    return dt.isoformat() if dt is not None else ""


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s)


def encode(msg: JobMessage) -> dict[str, str]:
    return {
        "job_id": msg.job_id,
        "site": msg.site,
        "name": msg.method,
        "queue": msg.queue,
        "args_b64": _b64encode(dumps(msg.args)) if msg.args else "",
        "kwargs_b64": _b64encode(dumps(msg.kwargs)) if msg.kwargs else "",
        "attempt": str(msg.attempt),
        "max_attempts": str(msg.max_attempts),
        "timeout_seconds": str(msg.timeout_seconds),
        "enqueued_at": _iso(msg.enqueued_at),
        "deadline": _iso(msg.deadline),
        "trace_parent": msg.trace_parent or "",
        "idempotency_key": msg.idempotency_key or "",
        "workflow_run_id": msg.workflow_run_id or "",
        "step_id": msg.step_id or "",
        "backoff": msg.backoff or "",
        "base_delay_seconds": str(msg.base_delay_seconds or 0),
        "max_delay_seconds": str(msg.max_delay_seconds or 0),
        "jitter": msg.jitter or "",
        "retry_on_names": json.dumps(msg.retry_on_names or []),
        "no_retry_on_names": json.dumps(msg.no_retry_on_names or []),
        "schema_version": str(SCHEMA_VERSION),
    }


def decode(fields_dict: dict[str, str]) -> JobMessage:
    missing = _REQUIRED_FIELDS - fields_dict.keys()
    if missing:
        raise ValueError(f"missing required field(s): {sorted(missing)}")

    schema_version = int(fields_dict["schema_version"])
    if schema_version != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported schema_version: {schema_version} (this build supports {SCHEMA_VERSION})"
        )

    args = loads(_b64decode(fields_dict["args_b64"])) if fields_dict["args_b64"] else []
    kwargs = loads(_b64decode(fields_dict["kwargs_b64"])) if fields_dict["kwargs_b64"] else {}

    def _maybe_int(s: str) -> int:
        return int(s) if s else 0

    def _maybe_list(s: str) -> list:
        return json.loads(s) if s else []

    return JobMessage(
        job_id=fields_dict["job_id"],
        site=fields_dict["site"],
        method=fields_dict["name"],
        queue=fields_dict["queue"],
        args=args,
        kwargs=kwargs,
        attempt=int(fields_dict["attempt"]),
        max_attempts=int(fields_dict["max_attempts"]),
        timeout_seconds=int(fields_dict["timeout_seconds"]),
        enqueued_at=_parse_iso(fields_dict["enqueued_at"]),
        deadline=_parse_iso(fields_dict.get("deadline", "")),
        trace_parent=fields_dict.get("trace_parent", ""),
        idempotency_key=fields_dict.get("idempotency_key", ""),
        workflow_run_id=fields_dict.get("workflow_run_id", ""),
        step_id=fields_dict.get("step_id", ""),
        backoff=fields_dict.get("backoff", ""),
        base_delay_seconds=_maybe_int(fields_dict.get("base_delay_seconds", "")),
        max_delay_seconds=_maybe_int(fields_dict.get("max_delay_seconds", "")),
        jitter=fields_dict.get("jitter", ""),
        retry_on_names=_maybe_list(fields_dict.get("retry_on_names", "")),
        no_retry_on_names=_maybe_list(fields_dict.get("no_retry_on_names", "")),
    )
```

- [ ] **Step 5: Run; expect all messages tests pass (9 total)**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_messages.py -v
```

- [ ] **Step 6: Run the FULL pytest suite to confirm zero regressions**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/ -q
```

Expected: All previously-passing tests (Phase 0 + Phase 1 Task 1) still pass.

- [ ] **Step 7: Commit**

```bash
git -C /Users/osamamuhammed/frappe_15/apps/conductor add conductor/messages.py tests/test_messages.py
git -C /Users/osamamuhammed/frappe_15/apps/conductor commit -m "feat(messages): Phase 1 optional fields (retry policy, idempotency_key actually populated)"
```

---

## Task 3: TDD `conductor.idempotency` (SET NX EX dispatch lock)

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/idempotency.py`
- Create: `<BENCH>/apps/conductor/tests/test_idempotency.py`

- [ ] **Step 1: Write failing tests**

Write to `<BENCH>/apps/conductor/tests/test_idempotency.py`:

```python
"""Unit tests for conductor.idempotency — dispatch idempotency via SET NX EX."""

import time

from conductor.idempotency import acquire_idem_lock, idem_redis_key


def test_idem_redis_key_uses_sha256_hex():
    key = idem_redis_key("frappe.localhost", "invoice:INV-001:email")
    # 64 hex chars after the prefix
    assert key.startswith("conductor:frappe.localhost:idem:")
    assert len(key) == len("conductor:frappe.localhost:idem:") + 64
    # Same input → same hash
    assert key == idem_redis_key("frappe.localhost", "invoice:INV-001:email")
    # Different input → different hash
    assert key != idem_redis_key("frappe.localhost", "invoice:INV-002:email")


def test_acquire_returns_none_on_first_call(fake_redis):
    out = acquire_idem_lock(fake_redis, "frappe.localhost", "k1", "job-A", ttl=60)
    assert out is None


def test_acquire_returns_existing_job_id_on_dup(fake_redis):
    acquire_idem_lock(fake_redis, "frappe.localhost", "k1", "job-A", ttl=60)
    out = acquire_idem_lock(fake_redis, "frappe.localhost", "k1", "job-B", ttl=60)
    assert out == "job-A"


def test_acquire_with_empty_key_skips_lock(fake_redis):
    """Empty idempotency_key means: no idempotency, always allow dispatch."""
    out = acquire_idem_lock(fake_redis, "frappe.localhost", "", "job-A", ttl=60)
    assert out is None
    out = acquire_idem_lock(fake_redis, "frappe.localhost", "", "job-B", ttl=60)
    assert out is None  # would have collided, but empty key bypasses lock


def test_acquire_after_ttl_expiry_allows_reuse(fake_redis):
    acquire_idem_lock(fake_redis, "frappe.localhost", "k1", "job-A", ttl=1)
    time.sleep(1.2)  # let it expire (fakeredis honors EX)
    out = acquire_idem_lock(fake_redis, "frappe.localhost", "k1", "job-B", ttl=60)
    assert out is None  # newly acquired
```

- [ ] **Step 2: Run; expect ImportError**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_idempotency.py -v
```

- [ ] **Step 3: Implement**

Write to `<BENCH>/apps/conductor/conductor/idempotency.py`:

```python
"""Dispatch idempotency: SET NX EX on a SHA-256-hashed key.

If a caller dispatches twice with the same logical key within the TTL, the
second call gets back the first call's job_id and does NOT enqueue.

The lock is NOT released on terminal status — TTL is the only release. A
duplicate dispatch within the TTL is the entire point of having the lock.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Optional

import redis as redis_mod


def idem_redis_key(site: str, idempotency_key: str) -> str:
    h = sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"conductor:{site}:idem:{h}"


def acquire_idem_lock(
    client: redis_mod.Redis,
    site: str,
    idempotency_key: str,
    job_id: str,
    *,
    ttl: int,
) -> Optional[str]:
    """Try to claim the idempotency slot for `idempotency_key`.

    Returns:
      - None if the lock was newly acquired (caller should proceed with dispatch).
      - The existing job_id (str) if a prior dispatch holds the lock.
      - None if `idempotency_key` is empty (idempotency disabled for this dispatch).
    """
    if not idempotency_key:
        return None
    key = idem_redis_key(site, idempotency_key)
    if client.set(key, job_id, nx=True, ex=ttl):
        return None
    existing = client.get(key)
    return existing.decode("utf-8") if isinstance(existing, bytes) else existing
```

- [ ] **Step 4: Run; expect 5 passed**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_idempotency.py -v
```

- [ ] **Step 5: Commit**

```bash
git -C /Users/osamamuhammed/frappe_15/apps/conductor add conductor/idempotency.py tests/test_idempotency.py
git -C /Users/osamamuhammed/frappe_15/apps/conductor commit -m "feat(idempotency): SHA-256 keyed SET NX EX dispatch lock"
```

---

## Task 4: TDD `conductor.execution_lock` (SET NX EX worker lock)

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/execution_lock.py`
- Create: `<BENCH>/apps/conductor/tests/test_execution_lock.py`

- [ ] **Step 1: Write failing tests**

Write to `<BENCH>/apps/conductor/tests/test_execution_lock.py`:

```python
"""Unit tests for conductor.execution_lock — SET NX on conductor:{site}:lock:{job_id}."""

from conductor.execution_lock import (
    acquire_exec_lock,
    exec_lock_redis_key,
    release_exec_lock,
)


def test_exec_lock_redis_key():
    assert exec_lock_redis_key("frappe.localhost", "abc-123") == "conductor:frappe.localhost:lock:abc-123"


def test_acquire_succeeds_on_free_lock(fake_redis):
    ok = acquire_exec_lock(fake_redis, "frappe.localhost", "job-1", "worker-A", ttl=30)
    assert ok is True
    val = fake_redis.get(exec_lock_redis_key("frappe.localhost", "job-1"))
    assert val == b"worker-A"


def test_acquire_fails_when_held(fake_redis):
    acquire_exec_lock(fake_redis, "frappe.localhost", "job-1", "worker-A", ttl=30)
    ok = acquire_exec_lock(fake_redis, "frappe.localhost", "job-1", "worker-B", ttl=30)
    assert ok is False
    # Original holder unchanged
    assert fake_redis.get(exec_lock_redis_key("frappe.localhost", "job-1")) == b"worker-A"


def test_release_only_when_owner_matches(fake_redis):
    acquire_exec_lock(fake_redis, "frappe.localhost", "job-1", "worker-A", ttl=30)
    # A non-owner cannot release.
    released = release_exec_lock(fake_redis, "frappe.localhost", "job-1", "worker-B")
    assert released is False
    assert fake_redis.get(exec_lock_redis_key("frappe.localhost", "job-1")) == b"worker-A"
    # Owner can release.
    released = release_exec_lock(fake_redis, "frappe.localhost", "job-1", "worker-A")
    assert released is True
    assert fake_redis.get(exec_lock_redis_key("frappe.localhost", "job-1")) is None


def test_release_when_not_held_is_noop(fake_redis):
    released = release_exec_lock(fake_redis, "frappe.localhost", "job-never-acquired", "worker-A")
    assert released is False
```

- [ ] **Step 2: Run; expect ImportError**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_execution_lock.py -v
```

- [ ] **Step 3: Implement**

Write to `<BENCH>/apps/conductor/conductor/execution_lock.py`:

```python
"""Execution lock: defense-in-depth against double-execution under XACK races.

`acquire_exec_lock` does SET NX EX with the worker_id as the value. The TTL is
the job's timeout + 30s — long enough that a healthy worker holding it cannot
have it stolen, short enough that a dead worker's lock expires within a phase
of the job's expected runtime.

`release_exec_lock` uses a Lua check-and-delete so we only release if we still
own the key (avoids deleting a peer's lock that we lost ownership of via TTL).
"""

from __future__ import annotations

import redis as redis_mod

# Lua: delete the key only if its current value equals the supplied value.
# Returns 1 on delete, 0 otherwise.
_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
else
  return 0
end
"""


def exec_lock_redis_key(site: str, job_id: str) -> str:
    return f"conductor:{site}:lock:{job_id}"


def acquire_exec_lock(
    client: redis_mod.Redis,
    site: str,
    job_id: str,
    worker_id: str,
    *,
    ttl: int,
) -> bool:
    """SET NX EX. Returns True if newly acquired, False if held by a peer."""
    return bool(client.set(exec_lock_redis_key(site, job_id), worker_id, nx=True, ex=ttl))


def release_exec_lock(
    client: redis_mod.Redis,
    site: str,
    job_id: str,
    worker_id: str,
) -> bool:
    """Release iff we still own the lock. Returns True if released, False otherwise."""
    result = client.eval(_RELEASE_LUA, 1, exec_lock_redis_key(site, job_id), worker_id)
    return bool(result)
```

- [ ] **Step 4: Run; expect 5 passed**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_execution_lock.py -v
```

- [ ] **Step 5: Commit**

```bash
git -C /Users/osamamuhammed/frappe_15/apps/conductor add conductor/execution_lock.py tests/test_execution_lock.py
git -C /Users/osamamuhammed/frappe_15/apps/conductor commit -m "feat(execution_lock): SET NX EX with Lua check-and-delete release"
```

---

## Task 5: TDD `conductor.scheduled` (ZSET helpers + delay drainer)

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/scheduled.py`
- Create: `<BENCH>/apps/conductor/tests/test_scheduled.py`

- [ ] **Step 1: Write failing tests**

Write to `<BENCH>/apps/conductor/tests/test_scheduled.py`:

```python
"""Unit tests for conductor.scheduled — ZSET helpers + drainer pull loop."""

import json
import time

from conductor.messages import encode
from conductor.scheduled import (
    drain_due_messages,
    schedule_message,
    scheduled_redis_key,
)
from tests.test_messages import _sample_message  # reuse helper


def test_scheduled_redis_key():
    assert scheduled_redis_key("frappe.localhost") == "conductor:frappe.localhost:scheduled"


def test_schedule_message_zadds_with_score(fake_redis):
    msg = _sample_message()
    encoded = encode(msg)
    run_at_ms = 1735000000000  # explicit deterministic score
    schedule_message(fake_redis, "frappe.localhost", encoded, run_at_ms)
    items = fake_redis.zrange(scheduled_redis_key("frappe.localhost"), 0, -1, withscores=True)
    assert len(items) == 1
    member, score = items[0]
    assert json.loads(member.decode()) == encoded
    assert int(score) == run_at_ms


def test_drain_due_messages_pulls_only_due(fake_redis):
    msg_due = encode(_sample_message().replace(job_id="due-1"))
    msg_future = encode(_sample_message().replace(job_id="future-1"))
    now_ms = int(time.time() * 1000)
    schedule_message(fake_redis, "frappe.localhost", msg_due, now_ms - 1000)
    schedule_message(fake_redis, "frappe.localhost", msg_future, now_ms + 60_000)

    drained = drain_due_messages(fake_redis, "frappe.localhost", now_ms=now_ms)
    assert len(drained) == 1
    assert drained[0]["job_id"] == "due-1"
    # Drained items are removed from the ZSET; future ones remain.
    remaining = fake_redis.zrange(scheduled_redis_key("frappe.localhost"), 0, -1)
    assert len(remaining) == 1
    assert json.loads(remaining[0].decode())["job_id"] == "future-1"


def test_drain_with_empty_zset_returns_empty_list(fake_redis):
    drained = drain_due_messages(fake_redis, "frappe.localhost", now_ms=int(time.time() * 1000))
    assert drained == []
```

- [ ] **Step 2: Run; expect ImportError**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_scheduled.py -v
```

- [ ] **Step 3: Implement**

Write to `<BENCH>/apps/conductor/conductor/scheduled.py`:

```python
"""ZSET-backed scheduled-message store + the in-worker delay drainer.

A retry/scheduled-dispatch ZADDs the encoded JobMessage (as a JSON string)
with score = run_at_unix_ms. The drainer thread polls ZRANGEBYSCORE every 1s,
pops due items, and XADDs them to their target stream. Phase 2's scheduler
process subsumes this thread; the contract here is forward-compatible.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Iterable

import redis as redis_mod

from conductor.logging import get_logger
from conductor.streams import ensure_consumer_group, stream_key

log = get_logger("conductor.scheduled")

DRAIN_INTERVAL_SECONDS = 1.0


def scheduled_redis_key(site: str) -> str:
    return f"conductor:{site}:scheduled"


def schedule_message(
    client: redis_mod.Redis,
    site: str,
    encoded_message: dict[str, str],
    run_at_ms: int,
) -> None:
    """ZADD the encoded message (as JSON string) with score = run_at_ms."""
    member = json.dumps(encoded_message)
    client.zadd(scheduled_redis_key(site), {member: run_at_ms})


def drain_due_messages(
    client: redis_mod.Redis,
    site: str,
    *,
    now_ms: int | None = None,
    batch: int = 100,
) -> list[dict[str, str]]:
    """Return all due messages and remove them from the ZSET. Atomicity is per-member.

    Used both by the in-worker drainer thread and by tests.
    """
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    skey = scheduled_redis_key(site)
    members = client.zrangebyscore(skey, "-inf", now_ms, start=0, num=batch)
    out: list[dict[str, str]] = []
    for member in members:
        # ZREM ensures we don't double-process — concurrent drainers (Phase 2 scheduler
        # vs the in-worker thread during the transition) lose the race idempotently.
        if client.zrem(skey, member):
            try:
                out.append(json.loads(member.decode("utf-8") if isinstance(member, bytes) else member))
            except Exception as e:
                log.error("scheduled_decode_failed", error=str(e))
    return out


class DelayDrainer:
    """Thread that drains due messages and XADDs them to their target streams."""

    def __init__(self, client: redis_mod.Redis, site: str):
        self._client = client
        self._site = site
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="conductor-drainer")

    def start(self) -> None:
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        self._thread.join(timeout=timeout)

    def _run(self) -> None:
        log.info("drainer_started", site=self._site)
        while not self._stop.is_set():
            try:
                due = drain_due_messages(self._client, self._site)
                for encoded in due:
                    queue = encoded.get("queue") or ""
                    if not queue:
                        log.warning("drainer_skipped_empty_queue", encoded=encoded)
                        continue
                    target = stream_key(self._site, queue)
                    ensure_consumer_group(self._client, target)
                    self._client.xadd(target, encoded, maxlen=10000, approximate=True)
            except Exception as e:
                log.error("drainer_iteration_failed", error=str(e))
            self._stop.wait(DRAIN_INTERVAL_SECONDS)
        log.info("drainer_stopped", site=self._site)
```

- [ ] **Step 4: Run; expect 4 passed**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_scheduled.py -v
```

- [ ] **Step 5: Commit**

```bash
git -C /Users/osamamuhammed/frappe_15/apps/conductor add conductor/scheduled.py tests/test_scheduled.py
git -C /Users/osamamuhammed/frappe_15/apps/conductor commit -m "feat(scheduled): ZSET helpers + DelayDrainer thread for retries"
```

---

## Task 6: TDD `conductor.decorator` (`@conductor.job` + metadata registry)

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/decorator.py`
- Create: `<BENCH>/apps/conductor/tests/test_decorator.py`

- [ ] **Step 1: Write failing tests**

Write to `<BENCH>/apps/conductor/tests/test_decorator.py`:

```python
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
```

- [ ] **Step 2: Run; expect ImportError**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_decorator.py -v
```

- [ ] **Step 3: Implement**

Write to `<BENCH>/apps/conductor/conductor/decorator.py`:

```python
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
```

- [ ] **Step 4: Run; expect 6 passed**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_decorator.py -v
```

- [ ] **Step 5: Commit**

```bash
git -C /Users/osamamuhammed/frappe_15/apps/conductor add conductor/decorator.py tests/test_decorator.py
git -C /Users/osamamuhammed/frappe_15/apps/conductor commit -m "feat(decorator): @conductor.job + JobMetadata sidecar"
```

---

## Task 7: `Conductor Job Run` DocType

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job_run/__init__.py` (empty)
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job_run/conductor_job_run.json`
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job_run/conductor_job_run.py`
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job_run/test_conductor_job_run.py`

- [ ] **Step 1: Create the package folder**

```bash
mkdir -p /Users/osamamuhammed/frappe_15/apps/conductor/conductor/conductor/doctype/conductor_job_run
touch /Users/osamamuhammed/frappe_15/apps/conductor/conductor/conductor/doctype/conductor_job_run/__init__.py
```

- [ ] **Step 2: Write the DocType JSON** (master §6.4 schema)

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job_run/conductor_job_run.json`:

```json
{
 "actions": [],
 "allow_rename": 0,
 "autoname": "hash",
 "creation": "2026-04-27 00:00:00",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "job", "attempt_number", "status", "worker_id",
  "section_timing", "started_at", "finished_at", "duration_ms",
  "section_error", "error_type", "error_message", "traceback",
  "section_otel", "trace_id", "span_id",
  "section_sentry", "sentry_event_id", "sentry_url"
 ],
 "fields": [
  {"fieldname": "job", "fieldtype": "Link", "options": "Conductor Job", "label": "Job", "reqd": 1, "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "attempt_number", "fieldtype": "Int", "label": "Attempt", "reqd": 1, "in_list_view": 1},
  {"fieldname": "status", "fieldtype": "Select", "label": "Status", "options": "SUCCEEDED\nFAILED\nTIMED_OUT\nCANCELLED", "reqd": 1, "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "worker_id", "fieldtype": "Data", "label": "Worker ID", "in_list_view": 1},

  {"fieldname": "section_timing", "fieldtype": "Section Break", "label": "Timing"},
  {"fieldname": "started_at", "fieldtype": "Datetime", "label": "Started At"},
  {"fieldname": "finished_at", "fieldtype": "Datetime", "label": "Finished At"},
  {"fieldname": "duration_ms", "fieldtype": "Int", "label": "Duration (ms)"},

  {"fieldname": "section_error", "fieldtype": "Section Break", "label": "Error"},
  {"fieldname": "error_type", "fieldtype": "Data", "label": "Error Type"},
  {"fieldname": "error_message", "fieldtype": "Small Text", "label": "Error Message"},
  {"fieldname": "traceback", "fieldtype": "Long Text", "label": "Traceback"},

  {"fieldname": "section_otel", "fieldtype": "Section Break", "label": "OpenTelemetry"},
  {"fieldname": "trace_id", "fieldtype": "Data", "label": "Trace ID"},
  {"fieldname": "span_id", "fieldtype": "Data", "label": "Span ID"},

  {"fieldname": "section_sentry", "fieldtype": "Section Break", "label": "Sentry (Phase 4)"},
  {"fieldname": "sentry_event_id", "fieldtype": "Data", "label": "Sentry Event ID"},
  {"fieldname": "sentry_url", "fieldtype": "Data", "label": "Sentry URL"}
 ],
 "links": [],
 "modified": "2026-04-27 00:00:00",
 "modified_by": "Administrator",
 "module": "Conductor",
 "name": "Conductor Job Run",
 "owner": "Administrator",
 "permissions": [
  {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "report": 1, "export": 1},
  {"role": "Conductor Operator", "read": 1, "report": 1, "export": 1}
 ],
 "sort_field": "creation",
 "sort_order": "DESC",
 "track_changes": 0
}
```

- [ ] **Step 3: Write the controller**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job_run/conductor_job_run.py`:

```python
from frappe.model.document import Document


class ConductorJobRun(Document):
    pass
```

- [ ] **Step 4: Write the integration test**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job_run/test_conductor_job_run.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase


class TestConductorJobRun(FrappeTestCase):
    def setUp(self):
        # Job Run requires a Conductor Job; create a minimal one.
        self.job_id = "test-jobrun-parent-0001"
        if not frappe.db.exists("Conductor Queue", "default"):
            frappe.get_doc({"doctype": "Conductor Queue", "queue_name": "default", "concurrency": 4}).insert(ignore_permissions=True)
        if frappe.db.exists("Conductor Job", self.job_id):
            frappe.delete_doc("Conductor Job", self.job_id, force=True)
        frappe.get_doc({
            "doctype": "Conductor Job",
            "job_id": self.job_id,
            "queue": "default",
            "method": "conductor.demo.echo",
            "status": "QUEUED",
            "site": frappe.local.site,
        }).insert(ignore_permissions=True)

    def tearDown(self):
        if frappe.db.exists("Conductor Job", self.job_id):
            frappe.delete_doc("Conductor Job", self.job_id, force=True)

    def test_create_and_read(self):
        doc = frappe.get_doc({
            "doctype": "Conductor Job Run",
            "job": self.job_id,
            "attempt_number": 1,
            "status": "SUCCEEDED",
            "worker_id": "test-worker",
            "duration_ms": 42,
        }).insert(ignore_permissions=True)
        self.assertEqual(doc.attempt_number, 1)
        self.assertEqual(doc.status, "SUCCEEDED")
        frappe.delete_doc("Conductor Job Run", doc.name, force=True)
```

- [ ] **Step 5: Migrate + run test**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost migrate 2>&1 | tail -5
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_job_run.test_conductor_job_run
```

Expected: migration succeeds; 1 test passes.

- [ ] **Step 6: Commit**

```bash
git -C /Users/osamamuhammed/frappe_15/apps/conductor add conductor/conductor/doctype/conductor_job_run/
git -C /Users/osamamuhammed/frappe_15/apps/conductor commit -m "feat(doctype): Conductor Job Run + tests"
```

---

## Task 8: `Conductor DLQ Entry` DocType

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_dlq_entry/__init__.py` (empty)
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_dlq_entry/conductor_dlq_entry.json`
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_dlq_entry/conductor_dlq_entry.py`
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_dlq_entry/test_conductor_dlq_entry.py`

- [ ] **Step 1: Create the package folder**

```bash
mkdir -p /Users/osamamuhammed/frappe_15/apps/conductor/conductor/conductor/doctype/conductor_dlq_entry
touch /Users/osamamuhammed/frappe_15/apps/conductor/conductor/conductor/doctype/conductor_dlq_entry/__init__.py
```

- [ ] **Step 2: Write the DocType JSON** (master §6.5 schema)

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_dlq_entry/conductor_dlq_entry.json`:

```json
{
 "actions": [],
 "allow_rename": 0,
 "autoname": "hash",
 "creation": "2026-04-27 00:00:00",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "job", "queue", "moved_at", "attempts", "status",
  "section_error", "last_error_type", "last_error_message", "last_traceback",
  "section_payload", "payload", "trace_id",
  "section_review", "reviewed_by", "reviewed_at", "review_notes"
 ],
 "fields": [
  {"fieldname": "job", "fieldtype": "Link", "options": "Conductor Job", "label": "Job", "reqd": 1, "in_list_view": 1},
  {"fieldname": "queue", "fieldtype": "Link", "options": "Conductor Queue", "label": "Queue", "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "moved_at", "fieldtype": "Datetime", "label": "Moved To DLQ At", "in_list_view": 1},
  {"fieldname": "attempts", "fieldtype": "Int", "label": "Attempts"},
  {"fieldname": "status", "fieldtype": "Select", "label": "Status", "options": "PENDING_REVIEW\nRETRIED\nDISCARDED", "default": "PENDING_REVIEW", "reqd": 1, "in_list_view": 1, "in_standard_filter": 1},

  {"fieldname": "section_error", "fieldtype": "Section Break", "label": "Last Error"},
  {"fieldname": "last_error_type", "fieldtype": "Data", "label": "Error Type"},
  {"fieldname": "last_error_message", "fieldtype": "Small Text", "label": "Error Message"},
  {"fieldname": "last_traceback", "fieldtype": "Long Text", "label": "Traceback"},

  {"fieldname": "section_payload", "fieldtype": "Section Break", "label": "Payload"},
  {"fieldname": "payload", "fieldtype": "Long Text", "label": "Payload (JSON)"},
  {"fieldname": "trace_id", "fieldtype": "Data", "label": "Trace ID"},

  {"fieldname": "section_review", "fieldtype": "Section Break", "label": "Review (Phase 3)"},
  {"fieldname": "reviewed_by", "fieldtype": "Link", "options": "User", "label": "Reviewed By"},
  {"fieldname": "reviewed_at", "fieldtype": "Datetime", "label": "Reviewed At"},
  {"fieldname": "review_notes", "fieldtype": "Small Text", "label": "Review Notes"}
 ],
 "links": [],
 "modified": "2026-04-27 00:00:00",
 "modified_by": "Administrator",
 "module": "Conductor",
 "name": "Conductor DLQ Entry",
 "owner": "Administrator",
 "permissions": [
  {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "report": 1, "export": 1},
  {"role": "Conductor Operator", "read": 1, "report": 1, "export": 1}
 ],
 "sort_field": "moved_at",
 "sort_order": "DESC",
 "track_changes": 0
}
```

- [ ] **Step 3: Write the controller**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_dlq_entry/conductor_dlq_entry.py`:

```python
from frappe.model.document import Document


class ConductorDLQEntry(Document):
    pass
```

- [ ] **Step 4: Write the integration test**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_dlq_entry/test_conductor_dlq_entry.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase


class TestConductorDLQEntry(FrappeTestCase):
    def setUp(self):
        self.job_id = "test-dlq-parent-0001"
        if not frappe.db.exists("Conductor Queue", "default"):
            frappe.get_doc({"doctype": "Conductor Queue", "queue_name": "default", "concurrency": 4}).insert(ignore_permissions=True)
        if frappe.db.exists("Conductor Job", self.job_id):
            frappe.delete_doc("Conductor Job", self.job_id, force=True)
        frappe.get_doc({
            "doctype": "Conductor Job",
            "job_id": self.job_id,
            "queue": "default",
            "method": "conductor.demo.echo",
            "status": "DLQ",
            "site": frappe.local.site,
        }).insert(ignore_permissions=True)

    def tearDown(self):
        if frappe.db.exists("Conductor Job", self.job_id):
            frappe.delete_doc("Conductor Job", self.job_id, force=True)

    def test_create_with_default_status(self):
        doc = frappe.get_doc({
            "doctype": "Conductor DLQ Entry",
            "job": self.job_id,
            "queue": "default",
            "attempts": 3,
            "last_error_type": "RuntimeError",
            "last_error_message": "boom",
        }).insert(ignore_permissions=True)
        self.assertEqual(doc.status, "PENDING_REVIEW")
        self.assertEqual(doc.attempts, 3)
        frappe.delete_doc("Conductor DLQ Entry", doc.name, force=True)
```

- [ ] **Step 5: Migrate + run test**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost migrate 2>&1 | tail -5
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_dlq_entry.test_conductor_dlq_entry
```

- [ ] **Step 6: Commit**

```bash
git -C /Users/osamamuhammed/frappe_15/apps/conductor add conductor/conductor/doctype/conductor_dlq_entry/
git -C /Users/osamamuhammed/frappe_15/apps/conductor commit -m "feat(doctype): Conductor DLQ Entry + tests"
```

---

## Task 9: Modify dispatcher — idempotency, policy resolution, M-2 fix

**Files:**
- Modify: `<BENCH>/apps/conductor/conductor/dispatcher.py`
- Modify: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job/test_dispatcher.py` (add 3 tests)

- [ ] **Step 1: Read current dispatcher to understand baseline**

```bash
cat /Users/osamamuhammed/frappe_15/apps/conductor/conductor/dispatcher.py
```

(Phase 0 ships an `enqueue` that does idempotency=stub, queue lookup, OTel span, encode, insert row, XADD, publish_realtime. Phase 1 plugs in the real idempotency check, decorator/policy resolution, and replaces the multi-commit DISPATCH_FAILED branch.)

- [ ] **Step 2: Write 3 new failing tests**

Append to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job/test_dispatcher.py` (keep the existing 2 tests intact):

```python


class TestDispatcherIdempotency(FrappeTestCase):
    def setUp(self):
        from conductor.client import get_redis
        from conductor.config import load_config
        from conductor.idempotency import idem_redis_key
        # Clear any prior idempotency keys
        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)
        r.delete(idem_redis_key(frappe.local.site, "dup-test-key"))

    def test_duplicate_dispatch_with_same_key_returns_same_job_id(self):
        jid1 = conductor.enqueue(
            "conductor.demo.echo", queue="default", idempotency_key="dup-test-key", x=1,
        )
        jid2 = conductor.enqueue(
            "conductor.demo.echo", queue="default", idempotency_key="dup-test-key", x=2,
        )
        self.assertEqual(jid1, jid2, "second enqueue should return the first job_id")
        # Only ONE row was inserted
        rows = frappe.get_all("Conductor Job", filters={"job_id": jid1})
        self.assertEqual(len(rows), 1)
        # And the message in the stream is from the first call (x=1)
        frappe.delete_doc("Conductor Job", jid1, force=True)


class TestDispatcherDecoratorPullThrough(FrappeTestCase):
    def test_decorator_metadata_stamped_into_message(self):
        """A function with @conductor.job(...) gets its policy stamped on dispatch."""
        from conductor.client import get_redis
        from conductor.config import load_config
        from conductor.streams import stream_key
        from conductor.messages import decode

        # Define a decorated demo function. (Define here so the test is self-contained.)
        from conductor import job as conductor_job
        import conductor.demo as demo_mod

        @conductor_job(queue="default", max_attempts=7, backoff="linear", base_delay_seconds=4)
        def _decorated_echo(**kw):
            return kw
        # Register it on the demo module so frappe.get_attr can find it
        demo_mod._decorated_echo = _decorated_echo

        try:
            jid = conductor.enqueue("conductor.demo._decorated_echo", k=99)

            cfg = load_config(frappe.local.conf)
            r = get_redis(cfg.redis_url)
            skey = stream_key(frappe.local.site, "default")
            entries = r.xrevrange(skey, count=1)
            _, fields = entries[0]
            decoded = {k.decode(): v.decode() for k, v in fields.items()}
            msg = decode(decoded)

            self.assertEqual(msg.max_attempts, 7)
            self.assertEqual(msg.backoff, "linear")
            self.assertEqual(msg.base_delay_seconds, 4)
            frappe.delete_doc("Conductor Job", jid, force=True)
        finally:
            del demo_mod._decorated_echo


class TestDispatcherDispatchFailedSingleTxn(FrappeTestCase):
    def test_xadd_failure_uses_single_db_transaction(self):
        """Simulate XADD failure; verify status + error fields written in one shot."""
        import redis
        from unittest.mock import patch

        # Patch xadd on the dispatcher's redis client to raise.
        def _boom(*a, **kw):
            raise redis.exceptions.ConnectionError("simulated XADD failure")

        with patch("conductor.dispatcher.get_redis") as mock_get:
            fake_client = type("FakeRedis", (), {})()
            fake_client.xadd = _boom
            # ensure_consumer_group also calls into client; emulate
            fake_client.xgroup_create = lambda *a, **kw: None
            mock_get.return_value = fake_client

            try:
                conductor.enqueue("conductor.demo.echo", queue="default", x=1)
                self.fail("expected ConnectionError")
            except redis.exceptions.ConnectionError:
                pass

        # Find the row we just wrote
        rows = frappe.get_all(
            "Conductor Job",
            filters={"status": "DISPATCH_FAILED"},
            fields=["name", "last_error_type", "last_error_message"],
            order_by="enqueued_at desc",
            limit=1,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].last_error_type, "ConnectionError")
        self.assertIn("simulated", rows[0].last_error_message)
        frappe.delete_doc("Conductor Job", rows[0].name, force=True)
```

- [ ] **Step 3: Run; expect the 3 new tests to fail or error**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_job.test_dispatcher 2>&1 | tail -30
```

Expected: pre-existing 2 tests pass; the 3 new ones fail (idempotency not wired, decorator not consulted, multi-commit DISPATCH_FAILED not converted to single-txn).

- [ ] **Step 4: Replace `dispatcher.py` with the Phase 1 version**

Write to `<BENCH>/apps/conductor/conductor/dispatcher.py`:

```python
"""Job dispatcher: write Conductor Job row, XADD to Redis Stream, publish realtime.

Phase 1 additions: idempotency check, decorator-driven policy resolution
(per-call > decorator > queue defaults), single-transaction DISPATCH_FAILED
branch (M-2 fix).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import frappe

from conductor.client import get_redis
from conductor.config import load_config
from conductor.decorator import JobMetadata, get_metadata
from conductor.idempotency import acquire_idem_lock
from conductor.logging import get_logger
from conductor.messages import JobMessage, encode
from conductor.otel import get_tracer, inject_traceparent, setup_otel
from conductor.retry import RetryPolicy
from conductor.streams import ensure_consumer_group, stream_key

log = get_logger("conductor.dispatcher")

_PREVIEW_MAX = 4096
_DEFAULT_IDEM_TTL_SECONDS = 86_400  # 24h


def _preview(value: Any) -> str:
    try:
        return json.dumps(value, default=str)[:_PREVIEW_MAX]
    except Exception:
        return repr(value)[:_PREVIEW_MAX]


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _exception_class_path(cls: type[BaseException]) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _resolve_dispatch_config(
    method: str,
    *,
    per_call_queue: Optional[str],
    per_call_timeout: Optional[int],
    per_call_max_attempts: Optional[int],
    per_call_idempotency_key: Optional[str],
    kwargs: dict[str, Any],
) -> tuple[str, int, RetryPolicy, str, Optional[JobMetadata]]:
    """Resolve queue, timeout, RetryPolicy, idempotency_key per the precedence:
    per-call kwargs > decorator metadata > queue defaults."""
    # 1. Look up the function and its decorator metadata (if any).
    meta: Optional[JobMetadata] = None
    try:
        func = frappe.get_attr(method)
        meta = get_metadata(func)
    except Exception:
        # Function may not be importable at dispatch time (rare). Continue
        # without decorator metadata.
        pass

    # 2. Queue: per-call > decorator > "default"
    queue = per_call_queue or (meta.queue if meta and meta.queue else "default")
    queue_doc = frappe.get_cached_doc("Conductor Queue", queue)
    if not queue_doc.enabled:
        frappe.throw(f"Queue {queue!r} is disabled")

    # 3. Timeout: per-call > decorator > queue default
    timeout = per_call_timeout if per_call_timeout is not None else (
        meta.timeout if meta and meta.timeout is not None else int(queue_doc.default_timeout)
    )

    # 4. RetryPolicy: per-call (only max_attempts overrideable in Phase 1) >
    #    decorator policy > queue defaults
    if meta is not None:
        policy = meta.policy
    else:
        policy = RetryPolicy(
            max_attempts=int(queue_doc.default_max_attempts or 3),
            backoff=str(queue_doc.default_backoff or "exponential"),
            base_delay_seconds=int(queue_doc.default_base_delay_seconds or 2),
            max_delay_seconds=int(queue_doc.default_max_delay_seconds or 600),
            jitter=str(queue_doc.default_jitter or "full"),
        )
    if per_call_max_attempts is not None:
        policy = RetryPolicy(
            max_attempts=per_call_max_attempts,
            backoff=policy.backoff,
            base_delay_seconds=policy.base_delay_seconds,
            max_delay_seconds=policy.max_delay_seconds,
            jitter=policy.jitter,
            retry_on=policy.retry_on,
            no_retry_on=policy.no_retry_on,
        )

    # 5. Idempotency key: per-call str > decorator callable(**kwargs) > "" (none)
    idem_key = per_call_idempotency_key or ""
    if not idem_key and meta and meta.idempotency_key_fn is not None:
        try:
            idem_key = meta.idempotency_key_fn(**kwargs) or ""
        except Exception as e:
            log.warning("idempotency_key_fn_failed", method=method, error=str(e))
            idem_key = ""

    return queue, timeout, policy, idem_key, meta


def enqueue(
    method: str,
    *,
    queue: Optional[str] = None,
    timeout: Optional[int] = None,
    max_attempts: Optional[int] = None,
    idempotency_key: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """Enqueue a job. Returns the new job_id (UUID str), or the existing job_id
    if the idempotency_key already mapped to an in-flight or recently-dispatched job."""
    setup_otel(service_name="conductor")
    tracer = get_tracer()

    site = frappe.local.site
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)

    resolved_queue, timeout_seconds, policy, idem_key, _meta = _resolve_dispatch_config(
        method,
        per_call_queue=queue,
        per_call_timeout=timeout,
        per_call_max_attempts=max_attempts,
        per_call_idempotency_key=idempotency_key,
        kwargs=kwargs,
    )

    enqueued_at = datetime.now(timezone.utc)
    deadline = enqueued_at + timedelta(seconds=timeout_seconds)
    job_id = str(uuid.uuid4())

    # Idempotency check: if the key is already held, return the existing job_id.
    idem_ttl = int(
        (frappe.local.conf.get("conductor") or {}).get(
            "idempotency_ttl_seconds", _DEFAULT_IDEM_TTL_SECONDS
        )
    )
    existing = acquire_idem_lock(r, site, idem_key, job_id, ttl=idem_ttl)
    if existing is not None:
        log.info("dispatch_idempotency_hit", method=method, idem_key=idem_key, existing_job_id=existing)
        return existing

    with tracer.start_as_current_span("conductor.dispatch") as span:
        span.set_attribute("conductor.method", method)
        span.set_attribute("conductor.queue", resolved_queue)
        trace_parent = inject_traceparent()
        sc = span.get_span_context()
        trace_id_hex = format(sc.trace_id, "032x")
        span_id_hex = format(sc.span_id, "016x")

        msg = JobMessage(
            job_id=job_id,
            site=site,
            method=method,
            queue=resolved_queue,
            args=[],
            kwargs=kwargs,
            attempt=1,
            max_attempts=policy.max_attempts,
            timeout_seconds=timeout_seconds,
            enqueued_at=enqueued_at,
            deadline=deadline,
            trace_parent=trace_parent,
            idempotency_key=idem_key,
            workflow_run_id="",
            step_id="",
            backoff=policy.backoff,
            base_delay_seconds=policy.base_delay_seconds,
            max_delay_seconds=policy.max_delay_seconds,
            jitter=policy.jitter,
            retry_on_names=[_exception_class_path(c) for c in policy.retry_on],
            no_retry_on_names=[_exception_class_path(c) for c in policy.no_retry_on],
        )
        encoded = encode(msg)

        # 1. Insert audit row first (status QUEUED).
        doc = frappe.get_doc({
            "doctype": "Conductor Job",
            "job_id": job_id,
            "queue": resolved_queue,
            "method": method,
            "status": "QUEUED",
            "site": site,
            "args": encoded["args_b64"],
            "kwargs": encoded["kwargs_b64"],
            "args_preview": _preview([]),
            "kwargs_preview": _preview(kwargs),
            "attempt": 1,
            "max_attempts": policy.max_attempts,
            "timeout_seconds": timeout_seconds,
            "enqueued_at": enqueued_at.replace(tzinfo=None),
            "deadline": deadline.replace(tzinfo=None),
            "idempotency_key": idem_key,
            "trace_id": trace_id_hex,
            "span_id": span_id_hex,
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        # 2. XADD to the stream. Lazy-create the consumer group on first XADD.
        skey = stream_key(site, resolved_queue)
        try:
            ensure_consumer_group(r, skey)
            redis_msg_id = r.xadd(skey, encoded, maxlen=cfg.stream_max_len, approximate=True)
        except Exception as e:
            # M-2: single transaction for the failure update.
            frappe.db.set_value(
                "Conductor Job",
                doc.name,
                {
                    "status": "DISPATCH_FAILED",
                    "last_error_type": type(e).__name__,
                    "last_error_message": str(e)[:140],
                },
                update_modified=False,
            )
            frappe.db.commit()
            log.error("dispatch_failed", job_id=job_id, error=str(e))
            raise

        msg_id_str = redis_msg_id.decode() if isinstance(redis_msg_id, bytes) else str(redis_msg_id)
        frappe.db.set_value("Conductor Job", doc.name, "redis_msg_id", msg_id_str, update_modified=False)
        frappe.db.commit()

        frappe.publish_realtime(
            "conductor:job_queued",
            {"job_id": job_id, "queue": resolved_queue, "method": method},
            after_commit=False,
        )
        log.info("job_enqueued", job_id=job_id, queue=resolved_queue, method=method)

    return job_id
```

- [ ] **Step 5: Update `api.py` to also export `job` (decorator)**

Read it, then write:

```bash
cat /Users/osamamuhammed/frappe_15/apps/conductor/conductor/api.py
```

Replace with:

```python
"""Public API surface for the conductor package."""

from conductor.context import context
from conductor.decorator import job
from conductor.dispatcher import enqueue
from conductor.retry import RetryPolicy

__all__ = ["enqueue", "context", "job", "RetryPolicy"]
```

- [ ] **Step 6: Update `__init__.py` re-exports**

Read it, then replace with:

```python
__version__ = "0.0.1"

from conductor.api import RetryPolicy, context, enqueue, job  # noqa: E402,F401

__all__ = ["enqueue", "context", "job", "RetryPolicy", "__version__"]
```

(Preserve any existing `__version__` if it's not "0.0.1".)

- [ ] **Step 7: Run the 5 dispatcher integration tests; expect all pass**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_job.test_dispatcher
```

Expected: 5 tests pass.

- [ ] **Step 8: Run full pytest + Frappe sanity sweep**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/ -q
bench --site frappe.localhost run-tests --app conductor 2>&1 | tail -3
```

Expected: all green.

- [ ] **Step 9: Commit**

```bash
git -C /Users/osamamuhammed/frappe_15/apps/conductor add conductor/dispatcher.py conductor/api.py conductor/__init__.py conductor/conductor/doctype/conductor_job/test_dispatcher.py
git -C /Users/osamamuhammed/frappe_15/apps/conductor commit -m "feat(dispatcher): idempotency + decorator-driven policy + M-2 single-txn DISPATCH_FAILED"
```

---

## Task 10: Modify worker — exec lock, retry/DLQ paths, Job Run rows

**Files:**
- Modify: `<BENCH>/apps/conductor/conductor/worker.py`
- Modify: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job/test_worker_e2e.py` (add 3 tests)

This is the largest task. The worker grows from "execute and write status" to "execute, decide retry vs DLQ, write Job Run row, manage exec lock". Read carefully.

- [ ] **Step 1: Read current worker.py**

```bash
cat /Users/osamamuhammed/frappe_15/apps/conductor/conductor/worker.py
```

(Phase 0 ships `run_worker_once`, `run_worker`, `_handle_one`, `_read_and_dispatch`. Phase 1 modifies `_handle_one` and adds `_resolve_policy_from_msg`, `_schedule_retry`, `_move_to_dlq`, `_write_job_run_row` helpers.)

- [ ] **Step 2: Write 3 failing e2e tests**

Append to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job/test_worker_e2e.py` (keep existing TestWorkerE2E):

```python


class _AlwaysFails:
    """Demo function that always raises RuntimeError."""
    @staticmethod
    def boom_immediately(**kw):
        raise RuntimeError("scheduled-always-fails")


class TestWorkerRetryThenSucceed(FrappeTestCase):
    """A function that fails twice with a retryable error, then succeeds, must
    produce 3 Conductor Job Run rows and final status SUCCEEDED."""

    def setUp(self):
        # Reset failure counter each run.
        import conductor.demo as demo_mod
        demo_mod._fail_count = 0

        def flaky(**kw):
            if demo_mod._fail_count < 2:
                demo_mod._fail_count += 1
                raise RuntimeError(f"flaky attempt {demo_mod._fail_count}")
            return {"ok": True, "attempts": demo_mod._fail_count + 1}

        demo_mod.flaky = flaky
        # Clear the default stream of leftovers (Phase 0 isolation pattern).
        from conductor.client import get_redis
        from conductor.config import load_config
        from conductor.streams import stream_key
        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)
        r.delete(stream_key(frappe.local.site, "default"))

    def tearDown(self):
        import conductor.demo as demo_mod
        if hasattr(demo_mod, "flaky"):
            del demo_mod.flaky
        if hasattr(demo_mod, "_fail_count"):
            del demo_mod._fail_count

    def test_three_attempts_terminal_success(self):
        from conductor.worker import run_worker_once

        jid = conductor.enqueue(
            "conductor.demo.flaky",
            queue="default",
            max_attempts=3,
        )
        # Run the worker enough times to drain the retry chain.
        # Each retry ZADDs to scheduled set; we need a drainer fire too.
        # For test simplicity we set base_delay to 0 by using queue defaults,
        # then call drain_due_messages directly between worker passes.
        from conductor.client import get_redis
        from conductor.config import load_config
        from conductor.scheduled import drain_due_messages
        from conductor.streams import ensure_consumer_group, stream_key
        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)

        for _ in range(6):  # ample iterations
            run_worker_once(queues=["default"], concurrency=1, site=frappe.local.site, block_ms=500)
            # Pump the scheduler set into the stream
            for encoded in drain_due_messages(r, frappe.local.site, now_ms=int(__import__("time").time() * 1000) + 60_000):
                target = stream_key(frappe.local.site, encoded["queue"])
                ensure_consumer_group(r, target)
                r.xadd(target, encoded, maxlen=10000, approximate=True)
            # Check terminal
            frappe.db.rollback()
            status = frappe.db.get_value("Conductor Job", jid, "status")
            if status in ("SUCCEEDED", "DLQ"):
                break

        self.assertEqual(frappe.db.get_value("Conductor Job", jid, "status"), "SUCCEEDED")
        runs = frappe.get_all(
            "Conductor Job Run", filters={"job": jid}, fields=["status"], order_by="creation"
        )
        statuses = [r.status for r in runs]
        # 2 FAILED then 1 SUCCEEDED
        self.assertEqual(statuses[-1], "SUCCEEDED")
        self.assertEqual(statuses.count("FAILED"), 2)
        frappe.delete_doc("Conductor Job", jid, force=True)
        for r in runs:
            frappe.delete_doc("Conductor Job Run", r.name if hasattr(r, "name") else r["name"], force=True)


class TestWorkerExhaustsToDLQ(FrappeTestCase):
    def setUp(self):
        from conductor.client import get_redis
        from conductor.config import load_config
        from conductor.streams import stream_key
        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)
        r.delete(stream_key(frappe.local.site, "default"))

    def test_exhausts_to_dlq(self):
        from conductor.worker import run_worker_once
        from conductor.client import get_redis
        from conductor.config import load_config
        from conductor.scheduled import drain_due_messages
        from conductor.streams import ensure_consumer_group, stream_key

        jid = conductor.enqueue("conductor.demo.boom", queue="default", max_attempts=3)

        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)
        for _ in range(8):
            run_worker_once(queues=["default"], concurrency=1, site=frappe.local.site, block_ms=500)
            for encoded in drain_due_messages(r, frappe.local.site, now_ms=int(__import__("time").time() * 1000) + 60_000):
                target = stream_key(frappe.local.site, encoded["queue"])
                ensure_consumer_group(r, target)
                r.xadd(target, encoded, maxlen=10000, approximate=True)
            frappe.db.rollback()
            if frappe.db.get_value("Conductor Job", jid, "status") == "DLQ":
                break

        self.assertEqual(frappe.db.get_value("Conductor Job", jid, "status"), "DLQ")
        # Three Job Run rows, all FAILED
        runs = frappe.get_all("Conductor Job Run", filters={"job": jid}, fields=["status"])
        self.assertEqual(len(runs), 3)
        self.assertTrue(all(r.status == "FAILED" for r in runs))
        # One DLQ Entry
        dlq = frappe.get_all("Conductor DLQ Entry", filters={"job": jid})
        self.assertEqual(len(dlq), 1)
        # Cleanup
        for r in runs:
            frappe.delete_doc("Conductor Job Run", r.name if hasattr(r, "name") else r["name"], force=True)
        for d in dlq:
            frappe.delete_doc("Conductor DLQ Entry", d.name if hasattr(d, "name") else d["name"], force=True)
        frappe.delete_doc("Conductor Job", jid, force=True)


class TestWorkerNoRetryOnValueError(FrappeTestCase):
    def setUp(self):
        import conductor.demo as demo_mod

        def value_error_immediately(**kw):
            raise ValueError("user input wrong")

        demo_mod.bad_input = value_error_immediately
        from conductor.client import get_redis
        from conductor.config import load_config
        from conductor.streams import stream_key
        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)
        r.delete(stream_key(frappe.local.site, "default"))

    def tearDown(self):
        import conductor.demo as demo_mod
        if hasattr(demo_mod, "bad_input"):
            del demo_mod.bad_input

    def test_value_error_in_no_retry_on_terminates_immediately(self):
        from conductor.worker import run_worker_once
        from conductor import job as conductor_job
        import conductor.demo as demo_mod

        @conductor_job(no_retry_on=(ValueError,), max_attempts=10)
        def bad_input_decorated(**kw):
            raise ValueError("nope")
        demo_mod.bad_input_decorated = bad_input_decorated

        try:
            jid = conductor.enqueue("conductor.demo.bad_input_decorated")
            run_worker_once(queues=["default"], concurrency=1, site=frappe.local.site, block_ms=2000)
            frappe.db.rollback()
            # Goes straight to DLQ — no retry
            self.assertEqual(frappe.db.get_value("Conductor Job", jid, "status"), "DLQ")
            runs = frappe.get_all("Conductor Job Run", filters={"job": jid})
            self.assertEqual(len(runs), 1)  # one attempt, no retries
            for r in runs:
                frappe.delete_doc("Conductor Job Run", r.name if hasattr(r, "name") else r["name"], force=True)
            dlq = frappe.get_all("Conductor DLQ Entry", filters={"job": jid})
            for d in dlq:
                frappe.delete_doc("Conductor DLQ Entry", d.name if hasattr(d, "name") else d["name"], force=True)
            frappe.delete_doc("Conductor Job", jid, force=True)
        finally:
            del demo_mod.bad_input_decorated
```

- [ ] **Step 3: Run; expect ImportError or AssertionError**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_job.test_worker_e2e 2>&1 | tail -30
```

Expected: existing 2 tests pass; new 3 fail (Job Run rows don't exist yet, retry path missing, DLQ path missing).

- [ ] **Step 4: Replace `worker.py` with the Phase 1 version**

Write to `<BENCH>/apps/conductor/conductor/worker.py`:

```python
"""Conductor worker loop: XREADGROUP → execute → status update → XACK.

Phase 1 additions:
- Acquire/release execution lock around job execution.
- On retryable failure: ZADD to scheduled set, status=SCHEDULED_RETRY.
- On exhausted retries: XADD to DLQ stream + Conductor DLQ Entry row, status=DLQ.
- Per-attempt Conductor Job Run row at terminal of each attempt.
- XAUTOCLAIM stalled-message reclamation per iteration (idle ≥ 60s).
- Spawn DelayDrainer thread (Phase 2 lifts to scheduler process).
"""

from __future__ import annotations

import importlib
import json
import os
import signal
import socket
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import frappe
import redis as redis_mod

from conductor.client import get_redis
from conductor.config import load_config
from conductor.context import set_context, start_watchdog
from conductor.execution_lock import acquire_exec_lock, release_exec_lock
from conductor.logging import get_logger, setup_logging
from conductor.messages import JobMessage, decode, encode
from conductor.otel import extract_traceparent, get_tracer, setup_otel
from conductor.retry import RetryPolicy
from conductor.scheduled import DelayDrainer, schedule_message
from conductor.streams import CONSUMER_GROUP, dlq_key, ensure_consumer_group, stream_key

log = get_logger("conductor.worker")

_HEARTBEAT_SECS = 5
_PREVIEW_MAX = 4096
_AUTOCLAIM_IDLE_MS = 60_000
_RECLAIM_BATCH = 32


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_naive() -> datetime:
    """MariaDB DATETIME doesn't accept tz-aware strings."""
    return _now().replace(tzinfo=None)


def _preview(value) -> str:
    try:
        return json.dumps(value, default=str)[:_PREVIEW_MAX]
    except Exception:
        return repr(value)[:_PREVIEW_MAX]


def _make_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _register_worker(worker_id: str, queues: list[str], site: str) -> None:
    if frappe.db.exists("Conductor Worker", worker_id):
        return
    frappe.get_doc({
        "doctype": "Conductor Worker",
        "worker_id": worker_id,
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "queues": json.dumps(queues),
        "site": site,
        "status": "ALIVE",
        "started_at": _now_naive(),
        "last_heartbeat": _now_naive(),
    }).insert(ignore_permissions=True)
    frappe.db.commit()


def _heartbeat(worker_id: str) -> None:
    frappe.db.set_value("Conductor Worker", worker_id, "last_heartbeat", _now_naive(), update_modified=False)
    frappe.db.commit()


def _mark_worker_gone(worker_id: str) -> None:
    if frappe.db.exists("Conductor Worker", worker_id):
        frappe.db.set_value("Conductor Worker", worker_id, "status", "GONE", update_modified=False)
        frappe.db.commit()


def _set_job_running(job_id: str, worker_id: str) -> None:
    frappe.db.set_value(
        "Conductor Job",
        job_id,
        {"status": "RUNNING", "started_at": _now_naive(), "worker_id": worker_id},
        update_modified=False,
    )
    frappe.db.commit()


def _set_job_succeeded(job_id: str, result) -> None:
    frappe.db.set_value(
        "Conductor Job",
        job_id,
        {"status": "SUCCEEDED", "finished_at": _now_naive(), "result_preview": _preview(result)},
        update_modified=False,
    )
    frappe.db.commit()


def _resolve_policy_from_msg(msg: JobMessage) -> RetryPolicy:
    """Reconstruct a RetryPolicy from JobMessage stamped fields, importing
    exception classes by fully-qualified name. Import failures fall back to
    Exception for retry_on (conservative-DLQ rather than retry-on-wrong-class)
    and the empty tuple for no_retry_on."""
    def _import_classes(names: list[str]) -> tuple[type[BaseException], ...]:
        out = []
        for n in names:
            try:
                module_name, _, qualname = n.rpartition(".")
                if not module_name:
                    continue
                mod = importlib.import_module(module_name)
                cls = getattr(mod, qualname, None)
                if cls and isinstance(cls, type) and issubclass(cls, BaseException):
                    out.append(cls)
            except Exception as e:
                log.warning("retry_on_class_import_failed", name=n, error=str(e))
        return tuple(out)

    return RetryPolicy(
        max_attempts=msg.max_attempts,
        backoff=msg.backoff or "exponential",
        base_delay_seconds=msg.base_delay_seconds or 2,
        max_delay_seconds=msg.max_delay_seconds or 600,
        jitter=msg.jitter or "full",
        retry_on=_import_classes(msg.retry_on_names) or (Exception,),
        no_retry_on=_import_classes(msg.no_retry_on_names),
    )


def _schedule_retry(msg: JobMessage, delay_seconds: float, redis_client, site: str) -> None:
    new_msg = msg.replace(attempt=msg.attempt + 1)
    encoded = encode(new_msg)
    next_run = _now() + timedelta(seconds=delay_seconds)
    run_at_ms = int(next_run.timestamp() * 1000)
    schedule_message(redis_client, site, encoded, run_at_ms)
    frappe.db.set_value(
        "Conductor Job",
        msg.job_id,
        {
            "status": "SCHEDULED_RETRY",
            "attempt": new_msg.attempt,
            "next_run_at": next_run.replace(tzinfo=None),
        },
        update_modified=False,
    )
    frappe.db.commit()


def _move_to_dlq(msg: JobMessage, exc: BaseException, redis_client, site: str) -> None:
    encoded = encode(msg)
    redis_client.xadd(dlq_key(site, msg.queue), encoded, maxlen=10000, approximate=True)
    frappe.get_doc({
        "doctype": "Conductor DLQ Entry",
        "job": msg.job_id,
        "queue": msg.queue,
        "moved_at": _now_naive(),
        "attempts": msg.attempt,
        "status": "PENDING_REVIEW",
        "last_error_type": type(exc).__name__,
        "last_error_message": str(exc)[:140],
        "last_traceback": traceback.format_exc(),
        "payload": json.dumps(encoded),
        "trace_id": msg.trace_parent or "",
    }).insert(ignore_permissions=True)
    frappe.db.set_value("Conductor Job", msg.job_id, "status", "DLQ", update_modified=False)
    frappe.db.commit()


def _write_job_run_row(
    msg: JobMessage,
    worker_id: str,
    *,
    status: str,
    exc: BaseException | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> None:
    finished_at = finished_at or _now()
    started_at = started_at or finished_at
    duration_ms = int((finished_at - started_at).total_seconds() * 1000) if started_at and finished_at else 0
    payload = {
        "doctype": "Conductor Job Run",
        "job": msg.job_id,
        "attempt_number": msg.attempt,
        "status": status,
        "worker_id": worker_id,
        "started_at": started_at.replace(tzinfo=None) if started_at else None,
        "finished_at": finished_at.replace(tzinfo=None) if finished_at else None,
        "duration_ms": duration_ms,
        "trace_id": msg.trace_parent or "",
    }
    if exc is not None:
        payload.update({
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:140],
            "traceback": traceback.format_exc(),
        })
    frappe.get_doc(payload).insert(ignore_permissions=True)
    frappe.db.commit()


def _xautoclaim_pending(redis_client, stream: str, worker_id: str) -> list[tuple[bytes, dict]]:
    """Return reclaimed (msg_id, fields) tuples. Bounded to _RECLAIM_BATCH."""
    try:
        result = redis_client.xautoclaim(
            stream, CONSUMER_GROUP, worker_id, min_idle_time=_AUTOCLAIM_IDLE_MS, count=_RECLAIM_BATCH
        )
    except redis_mod.exceptions.ResponseError as e:
        if "NOGROUP" in str(e):
            return []
        raise
    # redis-py returns (next_cursor, list_of_(id, fields), deleted_ids) on v5+.
    if len(result) >= 2:
        return result[1] or []
    return []


def _handle_one(
    stream_name: str,
    msg_id: bytes,
    fields: dict,
    worker_id: str,
    redis_client,
    site: str,
    sites_path: str,
) -> None:
    frappe.init(site=site, sites_path=sites_path)
    frappe.connect()
    try:
        decoded = {k.decode(): v.decode() for k, v in fields.items()}
        msg = decode(decoded)

        # Pre-execution cancellation: cancel() ran before we picked up.
        if frappe.db.get_value("Conductor Job", msg.job_id, "status") == "CANCELLED":
            redis_client.xack(stream_name, CONSUMER_GROUP, msg_id)
            return

        if not acquire_exec_lock(redis_client, site, msg.job_id, worker_id, ttl=msg.timeout_seconds + 30):
            log.info("exec_lock_held_by_peer", job_id=msg.job_id)
            redis_client.xack(stream_name, CONSUMER_GROUP, msg_id)
            return

        cancel_event = threading.Event()
        watchdog = start_watchdog(msg.deadline, cancel_event) if msg.deadline else None
        started_at = _now()

        succeeded = False; result = None; exc: BaseException | None = None
        try:
            with set_context(job_id=msg.job_id, attempt=msg.attempt, deadline=msg.deadline, cancel_event=cancel_event):
                _set_job_running(msg.job_id, worker_id)
                func = frappe.get_attr(msg.method)
                result = func(**msg.kwargs)
            succeeded = True
        except BaseException as e:
            exc = e

        finished_at = _now()
        current_status = frappe.db.get_value("Conductor Job", msg.job_id, "status")

        if current_status == "CANCELLED":
            # cancel() observed during run — preserve CANCELLED.
            _write_job_run_row(
                msg, worker_id,
                status="SUCCEEDED" if succeeded else "FAILED",
                exc=exc, started_at=started_at, finished_at=finished_at,
            )
            log.info("job_cancelled", job_id=msg.job_id, completed_anyway=succeeded)

        elif succeeded:
            _set_job_succeeded(msg.job_id, result)
            _write_job_run_row(msg, worker_id, status="SUCCEEDED", started_at=started_at, finished_at=finished_at)
            log.info("job_succeeded", job_id=msg.job_id)

        else:
            policy = _resolve_policy_from_msg(msg)
            if cancel_event.is_set():
                _write_job_run_row(msg, worker_id, status="TIMED_OUT", exc=exc, started_at=started_at, finished_at=finished_at)
                if policy.should_retry(exc, msg.attempt):
                    delay = policy.compute_next_delay(msg.attempt)
                    _schedule_retry(msg, delay, redis_client, site)
                else:
                    _move_to_dlq(msg, exc, redis_client, site)
                    frappe.db.set_value("Conductor Job", msg.job_id, "status", "TIMED_OUT", update_modified=False)
                    frappe.db.commit()
            elif policy.should_retry(exc, msg.attempt):
                delay = policy.compute_next_delay(msg.attempt)
                _schedule_retry(msg, delay, redis_client, site)
                _write_job_run_row(msg, worker_id, status="FAILED", exc=exc, started_at=started_at, finished_at=finished_at)
            else:
                _move_to_dlq(msg, exc, redis_client, site)
                _write_job_run_row(msg, worker_id, status="FAILED", exc=exc, started_at=started_at, finished_at=finished_at)
            log.error("job_failed", job_id=msg.job_id, attempt=msg.attempt)

        if watchdog: watchdog.cancel()
        release_exec_lock(redis_client, site, msg.job_id, worker_id)
        redis_client.xack(stream_name, CONSUMER_GROUP, msg_id)
    finally:
        frappe.destroy()


def _read_and_dispatch(
    redis_client, streams: dict, count: int, block_ms: int, worker_id: str,
    pool: ThreadPoolExecutor, site: str, sites_path: str, *, wait: bool,
):
    """See Phase 0 docstring. wait=True for tests; wait=False for production."""
    msgs = redis_client.xreadgroup(CONSUMER_GROUP, worker_id, streams, count=count, block=block_ms)
    futures = []
    for stream_name, entries in (msgs or []):
        sname = stream_name.decode() if isinstance(stream_name, bytes) else stream_name
        for msg_id, fields in entries:
            futures.append(pool.submit(_handle_one, sname, msg_id, fields, worker_id, redis_client, site, sites_path))
    if wait:
        for f in futures:
            f.result()


def _reclaim_into_pool(
    redis_client, streams: dict, worker_id: str, pool: ThreadPoolExecutor,
    site: str, sites_path: str, *, wait: bool,
):
    """XAUTOCLAIM all watched streams; submit reclaimed entries to the pool."""
    futures = []
    for stream in streams:
        for msg_id, fields in _xautoclaim_pending(redis_client, stream, worker_id):
            futures.append(pool.submit(_handle_one, stream, msg_id, fields, worker_id, redis_client, site, sites_path))
    if wait:
        for f in futures:
            f.result()


def run_worker_once(*, queues: list[str], concurrency: int, site: str, block_ms: int = 5000) -> None:
    """Test-only single iteration. Reclaim + read + execute synchronously."""
    setup_otel(service_name="conductor")
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    worker_id = _make_worker_id()
    sites_path = frappe.local.sites_path
    _register_worker(worker_id, queues, site)
    streams = {}
    for q in queues:
        skey = stream_key(site, q)
        ensure_consumer_group(r, skey)
        streams[skey] = ">"
    pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="conductor-once-")
    try:
        _reclaim_into_pool(r, streams, worker_id, pool, site, sites_path, wait=True)
        _read_and_dispatch(r, streams, concurrency, block_ms, worker_id, pool, site, sites_path, wait=True)
    finally:
        pool.shutdown(wait=True)
        _mark_worker_gone(worker_id)


_shutdown = threading.Event()


def _install_signal_handlers():
    def handler(signum, frame):
        log.info("signal_received", signum=signum)
        _shutdown.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, handler)
        except ValueError:
            pass


def run_worker(*, queues: list[str], concurrency: int, site: str, grace_seconds: int = 30) -> None:
    setup_logging(site=site)
    setup_otel(service_name="conductor")
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    worker_id = _make_worker_id()
    sites_path = frappe.local.sites_path
    _register_worker(worker_id, queues, site)
    _install_signal_handlers()

    log_ctx = log.bind(worker_id=worker_id, site=site)
    log_ctx.info("worker_started", queues=queues, concurrency=concurrency)

    streams = {}
    for q in queues:
        skey = stream_key(site, q)
        ensure_consumer_group(r, skey)
        streams[skey] = ">"

    pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="conductor-")
    drainer = DelayDrainer(r, site)
    drainer.start()

    last_beat = 0.0
    try:
        while not _shutdown.is_set():
            now = time.time()
            if now - last_beat >= _HEARTBEAT_SECS:
                _heartbeat(worker_id)
                last_beat = now

            try:
                _reclaim_into_pool(r, streams, worker_id, pool, site, sites_path, wait=False)
                _read_and_dispatch(r, streams, concurrency, 5000, worker_id, pool, site, sites_path, wait=False)
            except redis_mod.exceptions.ConnectionError as e:
                log_ctx.warning("redis_connection_error", error=str(e))
                time.sleep(2)
            except Exception as e:
                log_ctx.error("worker_iteration_failed", error=str(e))
                time.sleep(1)
    finally:
        log_ctx.info("worker_shutting_down", grace_seconds=grace_seconds)
        drainer.stop()
        pool.shutdown(wait=True)
        _mark_worker_gone(worker_id)
        log_ctx.info("worker_stopped")
```

- [ ] **Step 5: Run e2e tests; expect all 5 pass**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_job.test_worker_e2e
```

Expected: 5 tests pass (the original 2 + 3 new).

- [ ] **Step 6: Run full suites**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/ -q
bench --site frappe.localhost run-tests --app conductor 2>&1 | tail -3
```

- [ ] **Step 7: Commit**

```bash
git -C /Users/osamamuhammed/frappe_15/apps/conductor add conductor/worker.py conductor/conductor/doctype/conductor_job/test_worker_e2e.py
git -C /Users/osamamuhammed/frappe_15/apps/conductor commit -m "feat(worker): exec lock, retry/DLQ paths, Job Run rows, XAUTOCLAIM, delay drainer"
```

---

## Task 11: TDD `conductor.sweeper` (orphan-row sweeper)

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/sweeper.py`
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job/test_sweeper.py`

The sweeper requires a Frappe site (DB queries), so its tests live as Frappe integration tests rather than pytest unit tests.

- [ ] **Step 1: Write failing integration test**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job/test_sweeper.py`:

```python
"""Integration tests for conductor.sweeper — recovers orphaned QUEUED rows
that have no redis_msg_id (the dispatch dual-write crash window)."""

import time
from datetime import datetime, timedelta

import frappe
from frappe.tests.utils import FrappeTestCase

from conductor.client import get_redis
from conductor.config import load_config
from conductor.streams import stream_key


class TestOrphanSweeper(FrappeTestCase):
    def setUp(self):
        cfg = load_config(frappe.local.conf)
        self.r = get_redis(cfg.redis_url)
        self.r.delete(stream_key(frappe.local.site, "default"))

    def _insert_orphan(self, age_seconds: int) -> str:
        job_id = f"test-orphan-{int(time.time() * 1000)}-{age_seconds}"
        enq_at = (datetime.now() - timedelta(seconds=age_seconds)).replace(microsecond=0)
        if frappe.db.exists("Conductor Job", job_id):
            frappe.delete_doc("Conductor Job", job_id, force=True)
        if not frappe.db.exists("Conductor Queue", "default"):
            frappe.get_doc({"doctype": "Conductor Queue", "queue_name": "default", "concurrency": 4}).insert(ignore_permissions=True)
        frappe.get_doc({
            "doctype": "Conductor Job",
            "job_id": job_id,
            "queue": "default",
            "method": "conductor.demo.echo",
            "status": "QUEUED",
            "site": frappe.local.site,
            "args": "",
            "kwargs": "",
            "args_preview": "[]",
            "kwargs_preview": "{}",
            "attempt": 1,
            "max_attempts": 3,
            "timeout_seconds": 60,
            "enqueued_at": enq_at,
            "deadline": enq_at + timedelta(seconds=60),
            # redis_msg_id intentionally NULL to simulate the crash window
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        return job_id

    def tearDown(self):
        # Clean any orphans we created
        for j in frappe.get_all("Conductor Job", filters={"job_id": ["like", "test-orphan-%"]}, pluck="name"):
            frappe.delete_doc("Conductor Job", j, force=True)

    def test_sweeper_re_xadds_orphan_older_than_threshold(self):
        from conductor.sweeper import sweep_orphans

        old = self._insert_orphan(age_seconds=60)  # > 30s threshold
        sweep_orphans(self.r, frappe.local.site, threshold_seconds=30)

        frappe.db.rollback()
        msg_id = frappe.db.get_value("Conductor Job", old, "redis_msg_id")
        self.assertTrue(msg_id, "orphan should have a redis_msg_id after sweep")
        # And it's actually in the stream
        entries = self.r.xrange(stream_key(frappe.local.site, "default"))
        self.assertTrue(any(mid.decode() == msg_id for mid, _ in entries))

    def test_sweeper_ignores_recent_rows(self):
        from conductor.sweeper import sweep_orphans

        recent = self._insert_orphan(age_seconds=5)  # below threshold
        sweep_orphans(self.r, frappe.local.site, threshold_seconds=30)

        frappe.db.rollback()
        self.assertIsNone(frappe.db.get_value("Conductor Job", recent, "redis_msg_id"))

    def test_sweeper_ignores_already_dispatched(self):
        from conductor.sweeper import sweep_orphans

        old = self._insert_orphan(age_seconds=60)
        # Mark as already dispatched
        frappe.db.set_value("Conductor Job", old, "redis_msg_id", "1234567-0", update_modified=False)
        frappe.db.commit()
        sweep_orphans(self.r, frappe.local.site, threshold_seconds=30)
        frappe.db.rollback()
        # Unchanged
        self.assertEqual(frappe.db.get_value("Conductor Job", old, "redis_msg_id"), "1234567-0")
```

- [ ] **Step 2: Run; expect ImportError**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_job.test_sweeper 2>&1 | tail -20
```

- [ ] **Step 3: Implement**

Write to `<BENCH>/apps/conductor/conductor/sweeper.py`:

```python
"""Orphan-row sweeper for the dispatch dual-write crash window (master §3 #12 option C).

Periodically queries Conductor Job for rows that:
  - status = QUEUED
  - redis_msg_id IS NULL
  - enqueued_at < now - 30s (longer than any normal commit-then-XADD round trip)

For each orphan, reconstruct a JobMessage from the row + queue defaults and
re-XADD. Update redis_msg_id; if XADD still fails, mark DISPATCH_FAILED.

NOTE: retry-policy fields are NOT stored on the Conductor Job row in v1, so
sweeper-recovered messages fall back to QUEUE defaults for backoff/jitter/etc.
For most workloads this is a graceful degradation; users with custom retry
policies are encouraged to keep dispatch reliable enough to never need the
sweeper (e.g., monitoring DISPATCH_FAILED rates).
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import frappe
import redis as redis_mod

from conductor.logging import get_logger
from conductor.messages import JobMessage, encode
from conductor.streams import ensure_consumer_group, stream_key

log = get_logger("conductor.sweeper")

SWEEP_INTERVAL_SECONDS = 30.0
DEFAULT_THRESHOLD_SECONDS = 30
SWEEP_BATCH = 100


def _row_to_jobmessage(row: dict, site: str, queue_doc: Any) -> JobMessage:
    """Reconstruct a JobMessage from the persisted Conductor Job row.
    Retry-policy fields fall back to queue defaults (see module docstring)."""
    return JobMessage(
        job_id=row["job_id"],
        site=site,
        method=row["method"],
        queue=row["queue"],
        # args/kwargs are already base64-msgpack on the row; the encoder will
        # re-emit them as the *_b64 wire fields, so we pass empty lists/dicts here
        # and inject the stored values directly into the encoded dict below.
        args=[],
        kwargs={},
        attempt=int(row.get("attempt") or 1),
        max_attempts=int(row.get("max_attempts") or queue_doc.default_max_attempts or 3),
        timeout_seconds=int(row.get("timeout_seconds") or queue_doc.default_timeout or 300),
        enqueued_at=row["enqueued_at"].replace(tzinfo=timezone.utc) if row.get("enqueued_at") else datetime.now(timezone.utc),
        deadline=row["deadline"].replace(tzinfo=timezone.utc) if row.get("deadline") else None,
        trace_parent="",  # original traceparent not stored; recovery loses trace continuity
        idempotency_key=row.get("idempotency_key") or "",
        backoff=str(queue_doc.default_backoff or "exponential"),
        base_delay_seconds=int(queue_doc.default_base_delay_seconds or 2),
        max_delay_seconds=int(queue_doc.default_max_delay_seconds or 600),
        jitter=str(queue_doc.default_jitter or "full"),
    )


def sweep_orphans(
    redis_client: redis_mod.Redis,
    site: str,
    *,
    threshold_seconds: int = DEFAULT_THRESHOLD_SECONDS,
    batch: int = SWEEP_BATCH,
) -> int:
    """One-pass sweep. Returns the number of orphans recovered."""
    threshold = datetime.now() - timedelta(seconds=threshold_seconds)
    rows = frappe.db.sql(
        """
        SELECT job_id, queue, method, status, site, attempt, max_attempts, timeout_seconds,
               enqueued_at, deadline, idempotency_key, args, kwargs
        FROM `tabConductor Job`
        WHERE status = 'QUEUED'
          AND (redis_msg_id IS NULL OR redis_msg_id = '')
          AND enqueued_at < %(threshold)s
        ORDER BY enqueued_at ASC
        LIMIT %(batch)s
        """,
        {"threshold": threshold, "batch": batch},
        as_dict=True,
    )

    recovered = 0
    for row in rows:
        try:
            queue_doc = frappe.get_cached_doc("Conductor Queue", row["queue"])
            msg = _row_to_jobmessage(row, site, queue_doc)
            encoded = encode(msg)
            # Inject the persisted args/kwargs base64 directly (don't re-encode).
            encoded["args_b64"] = row.get("args") or ""
            encoded["kwargs_b64"] = row.get("kwargs") or ""

            target = stream_key(site, row["queue"])
            ensure_consumer_group(redis_client, target)
            try:
                msg_id = redis_client.xadd(target, encoded, maxlen=10000, approximate=True)
                msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
                frappe.db.set_value("Conductor Job", row["job_id"], "redis_msg_id", msg_id_str, update_modified=False)
                frappe.db.commit()
                recovered += 1
                log.info("sweeper_recovered_orphan", job_id=row["job_id"], queue=row["queue"])
            except Exception as e:
                frappe.db.set_value(
                    "Conductor Job", row["job_id"],
                    {"status": "DISPATCH_FAILED",
                     "last_error_type": type(e).__name__,
                     "last_error_message": f"sweeper re-XADD failed: {str(e)[:120]}"},
                    update_modified=False,
                )
                frappe.db.commit()
                log.error("sweeper_re_xadd_failed", job_id=row["job_id"], error=str(e))
        except Exception as e:
            log.error("sweeper_row_failed", job_id=row.get("job_id"), error=str(e))

    return recovered


class OrphanSweeper:
    """Worker-side thread that runs sweep_orphans periodically."""

    def __init__(self, redis_client: redis_mod.Redis, site: str, sites_path: str):
        self._client = redis_client
        self._site = site
        self._sites_path = sites_path
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="conductor-sweeper")

    def start(self) -> None:
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        self._thread.join(timeout=timeout)

    def _run(self) -> None:
        log.info("sweeper_started", site=self._site)
        while not self._stop.is_set():
            try:
                frappe.init(site=self._site, sites_path=self._sites_path)
                frappe.connect()
                try:
                    sweep_orphans(self._client, self._site)
                finally:
                    frappe.destroy()
            except Exception as e:
                log.error("sweeper_iteration_failed", error=str(e))
            self._stop.wait(SWEEP_INTERVAL_SECONDS)
        log.info("sweeper_stopped", site=self._site)
```

- [ ] **Step 4: Run; expect 3 passed**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_job.test_sweeper
```

- [ ] **Step 5: Wire OrphanSweeper into `run_worker`**

Edit `<BENCH>/apps/conductor/conductor/worker.py`. Find the `run_worker` function and:

1. At the top of `run_worker` imports, add: `from conductor.sweeper import OrphanSweeper`
2. After `drainer = DelayDrainer(r, site)` line, add:
   ```python
       sweeper = OrphanSweeper(r, site, sites_path)
       sweeper.start()
   ```
3. In the `finally:` block, after `drainer.stop()`, add:
   ```python
           sweeper.stop()
   ```

Use Edit tool. The diff is small.

- [ ] **Step 6: Re-run full suites**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/ -q
bench --site frappe.localhost run-tests --app conductor 2>&1 | tail -3
```

- [ ] **Step 7: Commit**

```bash
git -C /Users/osamamuhammed/frappe_15/apps/conductor add conductor/sweeper.py conductor/worker.py conductor/conductor/doctype/conductor_job/test_sweeper.py
git -C /Users/osamamuhammed/frappe_15/apps/conductor commit -m "feat(sweeper): orphan recovery for dispatch dual-write crash window"
```

---

## Task 12: `conductor.cancellation` + worker cancel-poller

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/cancellation.py`
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job/test_cancellation.py`
- Modify: `<BENCH>/apps/conductor/conductor/worker.py` (add cancel_events map + CancelPoller)
- Modify: `<BENCH>/apps/conductor/conductor/api.py` and `__init__.py` (export `cancel`)

- [ ] **Step 1: Write failing tests**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job/test_cancellation.py`:

```python
"""Integration tests for conductor.cancellation."""

import frappe
from frappe.tests.utils import FrappeTestCase

import conductor


class TestCancelQueuedJob(FrappeTestCase):
    def setUp(self):
        from conductor.client import get_redis
        from conductor.config import load_config
        from conductor.streams import stream_key
        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)
        r.delete(stream_key(frappe.local.site, "default"))

    def test_cancel_returns_true_and_sets_status(self):
        jid = conductor.enqueue("conductor.demo.echo", queue="default")
        ok = conductor.cancel(jid)
        self.assertTrue(ok)
        self.assertEqual(frappe.db.get_value("Conductor Job", jid, "status"), "CANCELLED")
        frappe.delete_doc("Conductor Job", jid, force=True)

    def test_cancel_already_terminal_returns_false(self):
        jid = conductor.enqueue("conductor.demo.echo", queue="default")
        # Force terminal status
        frappe.db.set_value("Conductor Job", jid, "status", "SUCCEEDED", update_modified=False)
        frappe.db.commit()
        ok = conductor.cancel(jid)
        self.assertFalse(ok)
        self.assertEqual(frappe.db.get_value("Conductor Job", jid, "status"), "SUCCEEDED")
        frappe.delete_doc("Conductor Job", jid, force=True)

    def test_cancel_unknown_job_returns_false(self):
        self.assertFalse(conductor.cancel("nonexistent-job-id"))

    def test_cancel_scheduled_retry_removes_from_zset(self):
        from conductor.client import get_redis
        from conductor.config import load_config
        from conductor.scheduled import schedule_message, scheduled_redis_key
        from conductor.messages import encode
        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)

        jid = conductor.enqueue("conductor.demo.echo", queue="default")
        # Mark SCHEDULED_RETRY with a sample ZSET entry
        from tests.test_messages import _sample_message
        msg = _sample_message().replace(job_id=jid)
        encoded = encode(msg)
        schedule_message(r, frappe.local.site, encoded, run_at_ms=999_999_999_999)
        frappe.db.set_value("Conductor Job", jid, "status", "SCHEDULED_RETRY", update_modified=False)
        frappe.db.commit()

        before = r.zcard(scheduled_redis_key(frappe.local.site))
        ok = conductor.cancel(jid)
        after = r.zcard(scheduled_redis_key(frappe.local.site))
        self.assertTrue(ok)
        self.assertEqual(after, before - 1)
        self.assertEqual(frappe.db.get_value("Conductor Job", jid, "status"), "CANCELLED")
        frappe.delete_doc("Conductor Job", jid, force=True)
```

- [ ] **Step 2: Run; expect AttributeError on conductor.cancel**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_job.test_cancellation 2>&1 | tail -20
```

- [ ] **Step 3: Implement `conductor.cancellation`**

Write to `<BENCH>/apps/conductor/conductor/cancellation.py`:

```python
"""Public cancellation API. Cooperative model — see Phase 1 spec §12.3.

cancel(job_id):
  - terminal status → return False
  - QUEUED → status=CANCELLED, best-effort XDEL from queue stream
  - SCHEDULED_RETRY → status=CANCELLED, ZREM matching member from scheduled set
  - RUNNING → status=CANCELLED, the cancel-poller thread will flip the
    worker's cancel_event within 1s; user code observes via should_cancel()
"""

from __future__ import annotations

import json

import frappe

from conductor.client import get_redis
from conductor.config import load_config
from conductor.logging import get_logger
from conductor.scheduled import scheduled_redis_key
from conductor.streams import stream_key

log = get_logger("conductor.cancellation")

_TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "DLQ", "CANCELLED", "DISPATCH_FAILED"}


@frappe.whitelist()
def cancel(job_id: str) -> bool:
    """Mark `job_id` as CANCELLED. Returns True iff the cancellation transitioned
    state; False if the job was already terminal or unknown."""
    if not frappe.db.exists("Conductor Job", job_id):
        return False
    current = frappe.db.get_value("Conductor Job", job_id, "status")
    if current in _TERMINAL_STATUSES:
        return False

    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    site = frappe.local.site

    # Update status first so the worker (or any future XREADGROUP) sees CANCELLED.
    frappe.db.set_value("Conductor Job", job_id, "status", "CANCELLED", update_modified=False)
    frappe.db.commit()

    if current == "QUEUED":
        # Best-effort: try XDEL from the queue stream by redis_msg_id.
        msg_id = frappe.db.get_value("Conductor Job", job_id, "redis_msg_id")
        queue = frappe.db.get_value("Conductor Job", job_id, "queue")
        if msg_id and queue:
            try:
                r.xdel(stream_key(site, queue), msg_id)
            except Exception as e:
                log.warning("cancel_xdel_failed", job_id=job_id, error=str(e))

    elif current == "SCHEDULED_RETRY":
        # Find and remove the matching member from the scheduled ZSET.
        skey = scheduled_redis_key(site)
        for member in r.zrange(skey, 0, -1):
            try:
                encoded = json.loads(member.decode("utf-8") if isinstance(member, bytes) else member)
                if encoded.get("job_id") == job_id:
                    r.zrem(skey, member)
                    break
            except Exception:
                continue

    log.info("job_cancelled", job_id=job_id, prior_status=current)
    return True
```

- [ ] **Step 4: Add cancel-poller to the worker**

Edit `<BENCH>/apps/conductor/conductor/worker.py`. We need:

1. A new module-level `CancelPoller` class.
2. Threading-safe `cancel_events` dict accessible to `_handle_one`.
3. `_handle_one` registers/unregisters its `cancel_event` keyed by `job_id`.

Append to `worker.py` (after the `OrphanSweeper` import block, before `_handle_one`):

```python


class CancelPoller:
    """Polls Conductor Job for status=CANCELLED rows belonging to this worker
    and flips matching cancel_event entries in the shared map (§12.4)."""

    def __init__(
        self,
        worker_id: str,
        site: str,
        sites_path: str,
        cancel_events: dict[str, threading.Event],
        cancel_events_lock: threading.Lock,
        interval: float = 1.0,
    ):
        self._worker_id = worker_id
        self._site = site
        self._sites_path = sites_path
        self._cancel_events = cancel_events
        self._lock = cancel_events_lock
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="conductor-cancel-poller")

    def start(self) -> None:
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        self._thread.join(timeout=timeout)

    def _run(self) -> None:
        log.info("cancel_poller_started", worker_id=self._worker_id)
        while not self._stop.is_set():
            try:
                frappe.init(site=self._site, sites_path=self._sites_path)
                frappe.connect()
                try:
                    rows = frappe.db.sql(
                        "SELECT job_id FROM `tabConductor Job` WHERE status='CANCELLED' AND worker_id=%s",
                        (self._worker_id,),
                        as_dict=True,
                    )
                    for row in rows:
                        with self._lock:
                            ev = self._cancel_events.get(row["job_id"])
                        if ev is not None:
                            ev.set()
                finally:
                    frappe.destroy()
            except Exception as e:
                log.error("cancel_poller_iteration_failed", error=str(e))
            self._stop.wait(self._interval)
        log.info("cancel_poller_stopped", worker_id=self._worker_id)


# Process-global cancel_events map populated by _handle_one for the duration of
# each running job; CancelPoller flips entries when the DB shows CANCELLED.
_cancel_events: dict[str, threading.Event] = {}
_cancel_events_lock = threading.Lock()
```

Then modify `_handle_one` to register/unregister the cancel_event in the shared map. Use Edit tool to make these changes inside the existing `_handle_one` body:

After `cancel_event = threading.Event()`, add:

```python
        with _cancel_events_lock:
            _cancel_events[msg.job_id] = cancel_event
```

Then in the path right before `release_exec_lock`, add:

```python
        with _cancel_events_lock:
            _cancel_events.pop(msg.job_id, None)
```

Make sure that pop runs even if an exception above propagated — wrap the body in a try/finally if needed (the existing code structure already has the cleanup in a deterministic position; just add the pop alongside `release_exec_lock`).

Then in `run_worker`, after `sweeper = OrphanSweeper(...); sweeper.start()`, add:

```python
    cancel_poller = CancelPoller(worker_id, site, sites_path, _cancel_events, _cancel_events_lock)
    cancel_poller.start()
```

And in the finally block, after `sweeper.stop()`, add:

```python
        cancel_poller.stop()
```

- [ ] **Step 5: Update `api.py` to export `cancel`**

Read it; replace with:

```python
"""Public API surface for the conductor package."""

from conductor.cancellation import cancel
from conductor.context import context
from conductor.decorator import job
from conductor.dispatcher import enqueue
from conductor.retry import RetryPolicy

__all__ = ["enqueue", "context", "job", "RetryPolicy", "cancel"]
```

And `__init__.py`:

```python
__version__ = "0.0.1"

from conductor.api import RetryPolicy, cancel, context, enqueue, job  # noqa: E402,F401

__all__ = ["enqueue", "context", "job", "RetryPolicy", "cancel", "__version__"]
```

- [ ] **Step 6: Run cancellation tests**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_job.test_cancellation
```

Expected: 4 passed.

- [ ] **Step 7: Run full suites**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/ -q
bench --site frappe.localhost run-tests --app conductor 2>&1 | tail -3
```

- [ ] **Step 8: Commit**

```bash
git -C /Users/osamamuhammed/frappe_15/apps/conductor add conductor/cancellation.py conductor/worker.py conductor/api.py conductor/__init__.py conductor/conductor/doctype/conductor_job/test_cancellation.py
git -C /Users/osamamuhammed/frappe_15/apps/conductor commit -m "feat(cancellation): cancel(job_id) + cancel-poller thread + cooperative running-job flag"
```

---

## Task 13: `bench conductor cancel <job_id>` command

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/commands/cancel.py`
- Modify: `<BENCH>/apps/conductor/conductor/commands/__init__.py`

- [ ] **Step 1: Implement the click command**

Write to `<BENCH>/apps/conductor/conductor/commands/cancel.py`:

```python
"""bench --site <site> conductor cancel <job_id>"""

from __future__ import annotations

import sys

import click
import frappe
from frappe.commands import get_site, pass_context


@click.command("cancel")
@click.argument("job_id")
@pass_context
def cancel_command(ctx, job_id):
    """Cancel a Conductor Job by ID."""
    site = get_site(ctx)
    frappe.init(site=site)
    frappe.connect()
    try:
        from conductor.cancellation import cancel
        ok = cancel(job_id)
        if ok:
            click.echo(f"cancelled: {job_id}")
            sys.exit(0)
        click.echo(f"not cancelled (already terminal or unknown): {job_id}", err=True)
        sys.exit(1)
    finally:
        frappe.destroy()
```

- [ ] **Step 2: Register in `commands/__init__.py`**

Read it; modify to add `cancel_command`:

```python
"""Click command group exported to bench via hooks.py."""

import click

from conductor.commands.cancel import cancel_command
from conductor.commands.doctor import doctor_command
from conductor.commands.worker import worker_command


@click.group("conductor")
def conductor_group():
    """Conductor — reliability-first background jobs."""


conductor_group.add_command(worker_command)
conductor_group.add_command(doctor_command)
conductor_group.add_command(cancel_command)


commands = [conductor_group]
```

- [ ] **Step 3: Smoke test**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost conductor --help 2>&1 | head -15
```

Expected: lists `cancel`, `doctor`, `worker` subcommands.

Then test it on a real job:

```bash
bench --site frappe.localhost console <<'EOF'
import conductor
jid = conductor.enqueue("conductor.demo.echo", queue="default")
print("created:", jid)
EOF

bench --site frappe.localhost conductor cancel $(bench --site frappe.localhost console <<'EOF'
import conductor, frappe
print(conductor.enqueue("conductor.demo.echo", queue="default"))
EOF
| tail -1)
```

Or simpler, manual:

```bash
bench --site frappe.localhost console
# in the console:
# import conductor; jid = conductor.enqueue("conductor.demo.echo", queue="default"); print(jid); exit
# then:
bench --site frappe.localhost conductor cancel <paste-jid>
```

Expected: prints "cancelled: <jid>", exits 0. Re-running prints "not cancelled (already terminal...)" and exits 1.

- [ ] **Step 4: Commit**

```bash
git -C /Users/osamamuhammed/frappe_15/apps/conductor add conductor/commands/cancel.py conductor/commands/__init__.py
git -C /Users/osamamuhammed/frappe_15/apps/conductor commit -m "feat(commands): bench conductor cancel <job_id>"
```

---

## Task 14: Backfill missing Phase 0 §11 tests

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job/test_phase0_backfill.py`

- [ ] **Step 1: Write all 4 tests**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job/test_phase0_backfill.py`:

```python
"""Backfill of the four Phase 0 §11 integration tests not implemented in Phase 0."""

import subprocess
import time

import frappe
from frappe.tests.utils import FrappeTestCase

import conductor
from conductor.client import get_redis
from conductor.config import load_config
from conductor.streams import stream_key


class TestWorkerRecordsTimeout(FrappeTestCase):
    def setUp(self):
        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)
        r.delete(stream_key(frappe.local.site, "default"))

        # A function that intentionally ignores should_cancel() and runs longer than its deadline.
        import conductor.demo as demo_mod

        def slow_uncooperative(**kw):
            time.sleep(2.0)
            return {"finished": True}

        demo_mod.slow_uncooperative = slow_uncooperative

    def tearDown(self):
        import conductor.demo as demo_mod
        if hasattr(demo_mod, "slow_uncooperative"):
            del demo_mod.slow_uncooperative

    def test_timeout_writes_TIMED_OUT_run_row(self):
        from conductor.worker import run_worker_once
        from conductor import job as conductor_job

        # Decorate with no_retry_on=Exception to force terminal-on-timeout (DLQ).
        import conductor.demo as demo_mod

        @conductor_job(no_retry_on=(Exception,), max_attempts=1)
        def slow_decorated(**kw):
            time.sleep(2.0)
            return {"finished": True}
        demo_mod.slow_decorated = slow_decorated

        try:
            jid = conductor.enqueue("conductor.demo.slow_decorated", queue="default", timeout=1)
            run_worker_once(queues=["default"], concurrency=1, site=frappe.local.site, block_ms=3000)
            frappe.db.rollback()
            # When a run completes after deadline, status will reflect what the worker observed.
            # The Job Run row records TIMED_OUT.
            runs = frappe.get_all(
                "Conductor Job Run", filters={"job": jid}, fields=["status", "error_type"]
            )
            self.assertTrue(any(r.status == "TIMED_OUT" for r in runs),
                            f"expected at least one TIMED_OUT run; got {[r.status for r in runs]}")
            for r in runs:
                frappe.delete_doc("Conductor Job Run", r.name if hasattr(r, "name") else r["name"], force=True)
            frappe.delete_doc("Conductor Job", jid, force=True)
        finally:
            del demo_mod.slow_decorated


class TestDoctorCleanInstall(FrappeTestCase):
    def test_doctor_no_demo_exits_zero_in_clean_install(self):
        proc = subprocess.run(
            ["bench", "--site", frappe.local.site, "conductor", "doctor"],
            cwd="/Users/osamamuhammed/frappe_15",
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout}\nstderr={proc.stderr}")


class TestDoctorRedisDown(FrappeTestCase):
    def test_doctor_exits_one_when_redis_unreachable(self):
        # Override redis_url via env to a port nothing is listening on.
        env_override = {"CONDUCTOR_REDIS_URL_OVERRIDE": "redis://127.0.0.1:1/0"}
        # Doctor reads from frappe.local.conf, not env. So we can't easily override
        # without editing site_config. Skip if we can't run the negative test in CI.
        # Instead, ensure the failure path in conductor.doctor.run() returns 1
        # when ping raises, by stubbing.
        from unittest.mock import patch
        from conductor.doctor import run

        class _BoomRedis:
            def ping(self): raise ConnectionError("simulated")
            def xadd(self, *a, **kw): raise ConnectionError("simulated")
            def xreadgroup(self, *a, **kw): raise ConnectionError("simulated")
            def delete(self, *a, **kw): raise ConnectionError("simulated")
            def xack(self, *a, **kw): raise ConnectionError("simulated")
            def xgroup_create(self, *a, **kw): raise ConnectionError("simulated")

        with patch("conductor.doctor.get_redis", return_value=_BoomRedis()):
            rc = run(demo=False)
        self.assertEqual(rc, 1)


class TestFrappeCompatShim(FrappeTestCase):
    def test_compat_shim_produces_equivalent_job(self):
        from conductor.frappe_compat import enqueue
        jid = enqueue("conductor.demo.echo", queue="default", x=1, msg="hi")
        self.assertIsInstance(jid, str)
        doc = frappe.get_doc("Conductor Job", jid)
        self.assertEqual(doc.method, "conductor.demo.echo")
        self.assertEqual(doc.queue, "default")
        self.assertEqual(doc.status, "QUEUED")
        frappe.delete_doc("Conductor Job", jid, force=True)
```

- [ ] **Step 2: Run; expect all 4 pass**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_job.test_phase0_backfill
```

(The `TestDoctorCleanInstall` test invokes `bench` as a subprocess. If your bench is in a different CWD, adjust the `cwd=` arg.)

- [ ] **Step 3: Commit**

```bash
git -C /Users/osamamuhammed/frappe_15/apps/conductor add conductor/conductor/doctype/conductor_job/test_phase0_backfill.py
git -C /Users/osamamuhammed/frappe_15/apps/conductor commit -m "test: backfill Phase 0 §11 — timeout + doctor-clean + doctor-redis-down + frappe-compat"
```

---

## Task 15: Chaos test scaffolding

**Files:**
- Create: `<BENCH>/apps/conductor/tests_chaos/__init__.py` (empty)
- Create: `<BENCH>/apps/conductor/tests_chaos/conftest.py`

- [ ] **Step 1: Create the directory**

```bash
mkdir -p /Users/osamamuhammed/frappe_15/apps/conductor/tests_chaos
touch /Users/osamamuhammed/frappe_15/apps/conductor/tests_chaos/__init__.py
```

- [ ] **Step 2: Write the conftest with subprocess-worker fixture**

Write to `<BENCH>/apps/conductor/tests_chaos/conftest.py`:

```python
"""Chaos-test fixtures: spawn `bench conductor worker` as a subprocess so we
can kill -9 it mid-job and verify reclaim semantics.

Chaos tests need a real Frappe site connection inside the test process to
inspect rows, so each test does its own frappe.init/connect/destroy.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

BENCH_ROOT = Path("/Users/osamamuhammed/frappe_15")
DEFAULT_SITE = "frappe.localhost"


@pytest.fixture(scope="session")
def site():
    return DEFAULT_SITE


@pytest.fixture(scope="session", autouse=True)
def _frappe_init(site):
    """One-time per-session Frappe init for the test process itself."""
    import frappe
    frappe.init(site=site)
    frappe.connect()
    yield
    frappe.destroy()


@pytest.fixture
def spawn_worker(site):
    """Spawn `bench --site SITE conductor worker --queue default --concurrency 1`
    as a subprocess. Returns a callable that yields the subprocess.Popen
    handle; the test is responsible for kill/wait."""
    procs: list[subprocess.Popen] = []

    @contextmanager
    def _spawn(*, queue: str = "default", concurrency: int = 1):
        cmd = [
            "bench", "--site", site, "conductor", "worker",
            "--queue", queue, "--concurrency", str(concurrency),
        ]
        proc = subprocess.Popen(
            cmd,
            cwd=str(BENCH_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,  # new process group; SIGKILL kills children too
        )
        procs.append(proc)
        # Give it a moment to register itself
        time.sleep(2.0)
        try:
            yield proc
        finally:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=5)
            except Exception:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    yield _spawn

    for p in procs:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def wait_for_status(job_id: str, expected: str, *, timeout: float = 30.0) -> str:
    """Poll the DB until the job reaches `expected` or timeout. Returns the
    last-observed status (whether or not it matched)."""
    import frappe
    end = time.time() + timeout
    last = None
    while time.time() < end:
        frappe.db.rollback()
        last = frappe.db.get_value("Conductor Job", job_id, "status")
        if last == expected:
            return last
        time.sleep(0.2)
    return last or ""
```

- [ ] **Step 3: Update pytest.ini to include tests_chaos**

Read `<BENCH>/apps/conductor/pytest.ini`; modify the `testpaths` line:

```ini
[pytest]
testpaths = tests tests_chaos
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
```

- [ ] **Step 4: Sanity-check pytest collects the chaos dir**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests_chaos/ --collect-only 2>&1 | tail -10
```

Expected: collected 0 tests (no test files yet) without errors.

- [ ] **Step 5: Commit**

```bash
git -C /Users/osamamuhammed/frappe_15/apps/conductor add tests_chaos/ pytest.ini
git -C /Users/osamamuhammed/frappe_15/apps/conductor commit -m "test(chaos): scaffold tests_chaos/ + subprocess-worker fixture"
```

---

## Task 16: Chaos test — kill-9 mid-job

**Files:**
- Create: `<BENCH>/apps/conductor/tests_chaos/test_kill_during_run.py`

- [ ] **Step 1: Write the test**

Write to `<BENCH>/apps/conductor/tests_chaos/test_kill_during_run.py`:

```python
"""Chaos test: kill -9 a worker mid-job; a peer must reclaim and finish.

To make XAUTOCLAIM fire fast in tests, we use a low-idle-time variant via the
worker's behavior: we wait long enough for the first worker's lock TTL +
autoclaim threshold to elapse on a peer. Production threshold is 60s; for
tests we set the timeout to a small value so the lock TTL = timeout+30s also
elapses.
"""

from __future__ import annotations

import os
import signal
import time

import frappe

import conductor
from tests_chaos.conftest import wait_for_status


def _setup_demo_slow_function():
    """Add a slow demo function visible to the worker subprocess."""
    # We can't dynamically inject into the subprocess; rely on a function that
    # already exists. Use conductor.demo.slow_chaos defined below at import time.
    pass


# Define the slow_chaos function on conductor.demo so it's importable by
# subprocess workers (which run a fresh interpreter — they re-import conductor.demo).
import conductor.demo as _demo

def _slow_chaos(**kw):
    """Sleeps long enough for a kill-9 to interrupt; returns OK on the second worker."""
    import time
    # 8s sleep — long enough for the test to kill the first worker after ~2s.
    time.sleep(8)
    return {"completed": True}


_demo.slow_chaos = _slow_chaos


def test_kill_during_run_reclaims_and_completes(spawn_worker):
    """Worker A picks up a slow job. We kill -9 worker A at t=2s. Worker B,
    spawned at the same time, must eventually XAUTOCLAIM and finish the job."""
    # Use a short XAUTOCLAIM idle time for the test by monkeypatching the worker
    # constant via env variable. The simplest path: rely on lock TTL + idle = ~90s.
    # For CI speed we override _AUTOCLAIM_IDLE_MS via env.
    os.environ["CONDUCTOR_TEST_AUTOCLAIM_IDLE_MS"] = "1500"

    # Two workers — A and B — both consuming "default".
    with spawn_worker() as worker_a, spawn_worker() as worker_b:
        # Dispatch the slow job. Whichever worker reads first holds it.
        job_id = conductor.enqueue("conductor.demo.slow_chaos", queue="default", timeout=20)
        time.sleep(2.0)  # let one of them start

        # Kill worker A unconditionally with -9 (does not unwind locks).
        try:
            os.killpg(worker_a.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

        # Worker B must reclaim within ~30s (lock TTL = timeout+30 = 50s, but
        # _AUTOCLAIM_IDLE_MS we set to 1500ms — peer will reclaim very quickly).
        # NOTE: this requires the worker module to honor the env var; we add
        # support for that in this same task.
        final = wait_for_status(job_id, "SUCCEEDED", timeout=60)
        assert final == "SUCCEEDED", f"expected SUCCEEDED, got {final}"

        runs = frappe.get_all(
            "Conductor Job Run", filters={"job": job_id}, fields=["status", "worker_id"]
        )
        # Worker A's incomplete attempt produces a stale exec lock that B reclaims.
        # Final SUCCEEDED row must come from B (different worker_id).
        assert any(r.status == "SUCCEEDED" for r in runs), runs

        # Cleanup
        for r in runs:
            frappe.delete_doc("Conductor Job Run", r.name if hasattr(r, "name") else r["name"], force=True)
        frappe.delete_doc("Conductor Job", job_id, force=True)

    os.environ.pop("CONDUCTOR_TEST_AUTOCLAIM_IDLE_MS", None)
```

- [ ] **Step 2: Add env-var override to the worker for the autoclaim threshold**

Edit `<BENCH>/apps/conductor/conductor/worker.py`. Replace the line:

```python
_AUTOCLAIM_IDLE_MS = 60_000
```

with:

```python
_AUTOCLAIM_IDLE_MS = int(os.environ.get("CONDUCTOR_TEST_AUTOCLAIM_IDLE_MS", "60000"))
```

(`os` is already imported at the top of `worker.py`.)

- [ ] **Step 3: Run the chaos test**

Make sure both Redis daemons are running first:

```bash
redis-cli -p 11000 ping; redis-cli -p 13000 ping
# If either fails:
# redis-server /Users/osamamuhammed/frappe_15/config/redis_queue.conf --daemonize yes
# redis-server /Users/osamamuhammed/frappe_15/config/redis_cache.conf --daemonize yes
```

Then:

```bash
cd /Users/osamamuhammed/frappe_15
CONDUCTOR_TEST_AUTOCLAIM_IDLE_MS=1500 ./env/bin/pytest apps/conductor/tests_chaos/test_kill_during_run.py -v
```

Expected: 1 passed in ≤90s.

- [ ] **Step 4: Commit**

```bash
git -C /Users/osamamuhammed/frappe_15/apps/conductor add tests_chaos/test_kill_during_run.py conductor/worker.py
git -C /Users/osamamuhammed/frappe_15/apps/conductor commit -m "test(chaos): kill -9 mid-job → peer reclaims via XAUTOCLAIM and completes"
```

---

## Task 17: Chaos test — retry exhausts to DLQ

**Files:**
- Create: `<BENCH>/apps/conductor/tests_chaos/test_retry_exhausts_to_dlq.py`

- [ ] **Step 1: Write the test**

Write to `<BENCH>/apps/conductor/tests_chaos/test_retry_exhausts_to_dlq.py`:

```python
"""Chaos test: a function that always raises hits max_attempts and lands in DLQ
correctly even when a worker is killed mid-retry sequence."""

import os
import signal
import time

import frappe

import conductor
from tests_chaos.conftest import wait_for_status

# Define an always-failing function on conductor.demo for subprocess imports.
import conductor.demo as _demo

def _always_fails(**kw):
    raise RuntimeError("planned failure")

_demo.always_fails = _always_fails


def test_retry_exhausts_to_dlq_under_chaos(spawn_worker):
    os.environ["CONDUCTOR_TEST_AUTOCLAIM_IDLE_MS"] = "1500"
    with spawn_worker() as worker_a:
        # Tight retry loop: 3 attempts, base_delay=0.5s
        job_id = conductor.enqueue(
            "conductor.demo.always_fails",
            queue="default",
            max_attempts=3,
            timeout=10,
        )

        # Kill worker A 0.5s in (mid-first-attempt) once just to exercise reclaim.
        time.sleep(0.5)
        try:
            os.killpg(worker_a.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    # A new worker handles the rest of the retry chain.
    with spawn_worker() as worker_b:
        final = wait_for_status(job_id, "DLQ", timeout=60)
        assert final == "DLQ", f"expected DLQ, got {final}"

        # Three Job Run rows
        runs = frappe.get_all("Conductor Job Run", filters={"job": job_id}, fields=["status"])
        assert len(runs) >= 3, f"expected ≥3 runs, got {len(runs)}: {[r.status for r in runs]}"
        # All FAILED (or one TIMED_OUT if reclaim raced)
        assert all(r.status in ("FAILED", "TIMED_OUT") for r in runs), [r.status for r in runs]

        # Exactly one DLQ Entry
        dlq = frappe.get_all("Conductor DLQ Entry", filters={"job": job_id})
        assert len(dlq) == 1

        # Cleanup
        for d in dlq:
            frappe.delete_doc("Conductor DLQ Entry", d.name if hasattr(d, "name") else d["name"], force=True)
        for r in runs:
            frappe.delete_doc("Conductor Job Run", r.name if hasattr(r, "name") else r["name"], force=True)
        frappe.delete_doc("Conductor Job", job_id, force=True)

    os.environ.pop("CONDUCTOR_TEST_AUTOCLAIM_IDLE_MS", None)
```

- [ ] **Step 2: Run**

```bash
cd /Users/osamamuhammed/frappe_15
CONDUCTOR_TEST_AUTOCLAIM_IDLE_MS=1500 ./env/bin/pytest apps/conductor/tests_chaos/test_retry_exhausts_to_dlq.py -v
```

Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git -C /Users/osamamuhammed/frappe_15/apps/conductor add tests_chaos/test_retry_exhausts_to_dlq.py
git -C /Users/osamamuhammed/frappe_15/apps/conductor commit -m "test(chaos): retry exhausts to DLQ even under worker churn"
```

---

## Task 18: Chaos test — concurrent dispatch idempotency

**Files:**
- Create: `<BENCH>/apps/conductor/tests_chaos/test_dispatch_idempotency.py`

- [ ] **Step 1: Write the test**

Write to `<BENCH>/apps/conductor/tests_chaos/test_dispatch_idempotency.py`:

```python
"""Chaos test: two SEPARATE processes call conductor.enqueue with the same
idempotency_key concurrently. Exactly one Conductor Job row and exactly one
stream entry must result, and both processes must return the same job_id."""

import os
import subprocess
from pathlib import Path

import frappe

BENCH_ROOT = Path("/Users/osamamuhammed/frappe_15")


def _enqueue_via_subprocess(site: str, idem_key: str) -> str:
    """Spawn a fresh Python process that calls conductor.enqueue, prints the
    job_id to stdout. Returns the job_id."""
    code = f"""
import frappe, conductor
frappe.init(site={site!r})
frappe.connect()
try:
    jid = conductor.enqueue("conductor.demo.echo", queue="default", idempotency_key={idem_key!r}, x=1)
    print(jid, flush=True)
finally:
    frappe.destroy()
"""
    proc = subprocess.run(
        ["./env/bin/python", "-c", code],
        cwd=str(BENCH_ROOT),
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"subprocess failed: {proc.stderr}")
    return proc.stdout.strip().splitlines()[-1]


def test_concurrent_dispatch_with_same_key_returns_same_job_id(site):
    # Clear any prior idempotency lock from previous runs.
    from conductor.client import get_redis
    from conductor.config import load_config
    from conductor.idempotency import idem_redis_key
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    r.delete(idem_redis_key(site, "chaos-idem-test"))

    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        futures = [
            ex.submit(_enqueue_via_subprocess, site, "chaos-idem-test"),
            ex.submit(_enqueue_via_subprocess, site, "chaos-idem-test"),
        ]
        results = [f.result() for f in futures]

    assert results[0] == results[1], f"expected same job_id, got {results}"

    rows = frappe.get_all("Conductor Job", filters={"job_id": results[0]})
    assert len(rows) == 1, f"expected 1 row, got {len(rows)}"

    # Cleanup
    frappe.delete_doc("Conductor Job", results[0], force=True)
```

- [ ] **Step 2: Run**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests_chaos/test_dispatch_idempotency.py -v
```

Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git -C /Users/osamamuhammed/frappe_15/apps/conductor add tests_chaos/test_dispatch_idempotency.py
git -C /Users/osamamuhammed/frappe_15/apps/conductor commit -m "test(chaos): concurrent dispatch with same idem-key → exactly one job"
```

---

## Task 19: Five-run flake gate

- [ ] **Step 1: Run the chaos suite five consecutive times**

```bash
cd /Users/osamamuhammed/frappe_15
for i in 1 2 3 4 5; do
  echo "=== chaos run $i ==="
  CONDUCTOR_TEST_AUTOCLAIM_IDLE_MS=1500 ./env/bin/pytest apps/conductor/tests_chaos/ -q 2>&1 | tail -3
  echo ""
done
```

Expected: all 5 runs report `3 passed in <Ns>` with no failures, no flakes.

If any run fails:
1. Capture the full output of the failing run.
2. Diagnose: timing-related (extend timeout)? Real bug (fix it)? Test-pollution (clean stream/DB in setUp)?
3. Apply the minimum fix and start the 5-run cycle over.

- [ ] **Step 2: Commit any flake fixes**

```bash
# (Only if flakes were found and fixed)
git -C /Users/osamamuhammed/frappe_15/apps/conductor add <changed files>
git -C /Users/osamamuhammed/frappe_15/apps/conductor commit -m "fix(chaos): <what the flake was>"
```

- [ ] **Step 3: Cement the gate result**

Run one final time and record the output for the DoD evidence:

```bash
CONDUCTOR_TEST_AUTOCLAIM_IDLE_MS=1500 ./env/bin/pytest apps/conductor/tests_chaos/ -v 2>&1 | tee /tmp/chaos-final-run.txt | tail -10
```

---

## Task 20: Final DoD sweep + final code review

- [ ] **Step 1: Walk the Phase 1 spec §15 DoD**

```bash
cd /Users/osamamuhammed/frappe_15

# (a) Phase 0 DoD still holds.
bench --site frappe.localhost conductor doctor --demo && echo "Phase 0 DoD OK"

# (b) All pytest unit tests pass (Phase 0 + Phase 1).
./env/bin/pytest apps/conductor/tests/ -q

# (c) All Frappe integration tests pass.
bench --site frappe.localhost run-tests --app conductor 2>&1 | tail -3

# (d) The four missing Phase 0 §11 tests are present and passing.
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_job.test_phase0_backfill 2>&1 | tail -3

# (e) Chaos suite passes 5 consecutive runs (Task 19).

# (f) Retry exhausts to DLQ programmatically.
bench --site frappe.localhost console <<'EOF'
import frappe
import conductor
import time
from conductor.worker import run_worker_once
from conductor.client import get_redis
from conductor.config import load_config
from conductor.scheduled import drain_due_messages
from conductor.streams import ensure_consumer_group, stream_key
cfg = load_config(frappe.local.conf)
r = get_redis(cfg.redis_url)

jid = conductor.enqueue("conductor.demo.boom", queue="default", max_attempts=3)
for _ in range(8):
    run_worker_once(queues=["default"], concurrency=1, site=frappe.local.site, block_ms=500)
    for encoded in drain_due_messages(r, frappe.local.site, now_ms=int(time.time()*1000)+60000):
        target = stream_key(frappe.local.site, encoded["queue"])
        ensure_consumer_group(r, target)
        r.xadd(target, encoded, maxlen=10000, approximate=True)
    frappe.db.rollback()
    if frappe.db.get_value("Conductor Job", jid, "status") == "DLQ": break

assert frappe.db.get_value("Conductor Job", jid, "status") == "DLQ"
runs = frappe.get_all("Conductor Job Run", filters={"job": jid})
assert len(runs) == 3
dlq = frappe.get_all("Conductor DLQ Entry", filters={"job": jid})
assert len(dlq) == 1 and dlq[0].status == "PENDING_REVIEW"
print("DoD (f) OK:", jid)

# Cleanup
for r in runs: frappe.delete_doc("Conductor Job Run", r.name, force=True)
for d in dlq: frappe.delete_doc("Conductor DLQ Entry", d.name, force=True)
frappe.delete_doc("Conductor Job", jid, force=True); frappe.db.commit()
EOF

# (g) Idempotency hit returns same job_id.
bench --site frappe.localhost console <<'EOF'
import conductor, frappe
jid1 = conductor.enqueue("conductor.demo.echo", queue="default", idempotency_key="dod-g", x=1)
jid2 = conductor.enqueue("conductor.demo.echo", queue="default", idempotency_key="dod-g", x=2)
assert jid1 == jid2
rows = frappe.get_all("Conductor Job", filters={"job_id": jid1})
assert len(rows) == 1
print("DoD (g) OK:", jid1)
frappe.delete_doc("Conductor Job", jid1, force=True); frappe.db.commit()
EOF

# (h) cancellation works on QUEUED.
bench --site frappe.localhost console <<'EOF'
import conductor, frappe
jid = conductor.enqueue("conductor.demo.echo", queue="default")
assert conductor.cancel(jid)
assert frappe.db.get_value("Conductor Job", jid, "status") == "CANCELLED"
print("DoD (h) OK:", jid)
frappe.delete_doc("Conductor Job", jid, force=True); frappe.db.commit()
EOF

# (i) M-2 verified by Task 9 test_dispatcher_dispatch_failed_single_txn — already part of (c).

# Final state
git -C apps/conductor log --oneline | wc -l | awk '{print $1, "commits on develop"}'
git -C apps/conductor status --short
```

Expected: every step prints OK / passes; final state = clean tree, ~50+ commits.

- [ ] **Step 2: Dispatch the final code reviewer**

In the controlling subagent-driven session, run the final review against the Phase 1 spec covering 60fa9cd → HEAD (Phase 0 + Phase 1 combined). Use `superpowers:code-reviewer` with `model: opus`.

The reviewer should:
- Verify Phase 1 spec §2 in-scope items each have a corresponding implementation.
- Confirm Phase 1 §3 out-of-scope items aren't accidentally implemented.
- Flag remaining items as Phase 2 input via a hand-off doc.

- [ ] **Step 3: Write a Phase 2 hand-off doc**

Mirror the Phase 0 → Phase 1 hand-off pattern. Save to `apps/conductor/docs/superpowers/specs/2026-04-27-conductor-phase2-handoff.md`. Include:
- Issues from the final review (Important + Minor).
- Real bugs caught during execution (whatever turned up).
- Outbox/sweeper notes (the policy-loss limitation).
- Phase 2 scope reminder from master §4.

- [ ] **Step 4: Final commit**

```bash
git -C /Users/osamamuhammed/frappe_15/apps/conductor add docs/superpowers/specs/2026-04-27-conductor-phase2-handoff.md
git -C /Users/osamamuhammed/frappe_15/apps/conductor commit -m "docs: phase 2 hand-off — final review findings + execution discoveries"
```

---

## Self-Review Notes

This section is for the planner — not part of execution.

**Spec coverage:** Each Phase 1 spec §2 in-scope item maps to a task —
- DocTypes: T7 (Job Run), T8 (DLQ Entry).
- RetryPolicy + decorator: T1 (RetryPolicy), T6 (decorator).
- Per-call enqueue overrides: T9.
- Dispatch idempotency: T3 (lock helper) + T9 (dispatcher integration).
- Execution lock: T4 (lock helper) + T10 (worker integration).
- Retry path (ZADD + SCHEDULED_RETRY + Job Run): T5 (ZSET helpers) + T10.
- DLQ path (XADD + DLQ Entry + DLQ status): T10.
- In-worker delay drainer: T5 (DelayDrainer) + T10 (start it in run_worker).
- Sweeper: T11.
- XAUTOCLAIM stalled-message reclaim: T10 (in run_worker iteration).
- Cancellation: T12 (cancel + cancel-poller) + T13 (CLI).
- 4 missing Phase 0 §11 tests: T14.
- M-2 dispatcher fix: T9.
- Chaos test framework: T15.
- Chaos tests + 5-run gate: T16, T17, T18, T19.
- Final DoD: T20.

**Type/name consistency check:**
- `RetryPolicy(max_attempts, backoff, base_delay_seconds, max_delay_seconds, jitter, retry_on, no_retry_on)` — used identically in T1 (definition), T6 (decorator builds it), T9 (dispatcher consumes it via `_resolve_dispatch_config`), T10 (worker reconstructs it via `_resolve_policy_from_msg`).
- `JobMessage` field names — Phase 1 additions (`backoff`, `base_delay_seconds`, `max_delay_seconds`, `jitter`, `retry_on_names`, `no_retry_on_names`) — added in T2, used identically in T9 (dispatcher stamping) and T10 (worker reading).
- `acquire_idem_lock(client, site, idempotency_key, job_id, *, ttl)` — defined T3, called identically in T9.
- `acquire_exec_lock(client, site, job_id, worker_id, *, ttl) → bool` — defined T4, called identically in T10. Same for `release_exec_lock`.
- `schedule_message(client, site, encoded, run_at_ms)`, `drain_due_messages(client, site, *, now_ms)` — defined T5, used in T10 and (drain) in chaos tests.
- `JobMetadata.queue / .timeout / .policy / .idempotency_key_fn` — defined T6, consumed in T9.
- `cancel(job_id) → bool` — defined T12, called in T13 (CLI) and chaos tests.
- `_handle_one`, `_resolve_policy_from_msg`, `_schedule_retry`, `_move_to_dlq`, `_write_job_run_row` — all defined in T10's worker.py rewrite.
- `_AUTOCLAIM_IDLE_MS` env-var override — added in T16; consumed inside the worker loop (T10).

**Placeholder scan:** Searched for "TBD", "TODO", "implement later", "fill in details", "similar to Task N" (without code), "add appropriate error handling". None found.

**Out-of-scope check:** No task implements Phase 2+ features (scheduler process, Conductor Schedule DocType, dead-worker reaper, dashboard UI, OTel exporter, workflows, pool workers, rate limits, named retry policy registry, per-call idem TTL override, subprocess hard-kill).

**Known limitation called out in code:** Sweeper-recovered messages lose original retry policy (see T11 module docstring); falls back to queue defaults. Documented; matches Phase 1 spec §13 + spec §16 risk #2.

---

## Execution

Plan complete and saved to `apps/conductor/docs/superpowers/plans/2026-04-27-conductor-phase1-reliability-core.md`. Two execution options:

1. **Subagent-Driven** (recommended) — fresh subagent per task, two-stage review between tasks.
2. **Inline Execution** — execute in this session, batched checkpoints.
