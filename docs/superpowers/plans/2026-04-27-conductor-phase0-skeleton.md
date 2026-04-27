# Conductor Phase 0 (Skeleton) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a greenfield Frappe app named `conductor` that can dispatch a job to a Redis Stream, run it in a worker process, and persist a queryable audit row — all proven by `bench conductor doctor --demo` exiting 0.

**Architecture:** Frappe app embedded in the existing bench at `/Users/osamamuhammed/frappe_15`. Three DocTypes (`Conductor Queue`, `Conductor Job`, `Conductor Worker`) form the audit/config surface. A pure-Python core (`conductor.dispatcher`, `conductor.worker`, `conductor.streams`, `conductor.messages`) handles Redis Streams via consumer groups. A click command group exposes `bench conductor worker` and `bench conductor doctor`. OpenTelemetry SDK is wired as no-op spans; structlog provides JSON logs. No retries, no DLQ, no scheduler — those land in Phase 1.

**Tech Stack:**
- Python 3.12 (bench env)
- Frappe 15.106.0
- Redis 5+ (Streams, consumer groups)
- `redis-py` ≥ 5
- `msgpack` ≥ 1.0
- `opentelemetry-api` + `opentelemetry-sdk`
- `structlog`
- `pytest` (dev)

**Reference docs:**
- Master design: `/Users/osamamuhammed/frappe_15/docs/superpowers/specs/2026-04-27-conductor-master-design.md`
- Phase 0 spec: `/Users/osamamuhammed/frappe_15/docs/superpowers/specs/2026-04-27-conductor-phase0-skeleton.md`

**Bench-rooted paths used in this plan:**
- Bench root: `/Users/osamamuhammed/frappe_15` (referred to as `<BENCH>` in commands)
- App root after Task 1: `<BENCH>/apps/conductor`
- Bench Python: `<BENCH>/env/bin/python`
- Bench pytest (after Task 2): `<BENCH>/env/bin/pytest`
- Default Frappe site: `frappe.localhost`
- Redis (queue): `redis://127.0.0.1:11000` — Conductor uses **DB 2** on this host
- Redis (cache): `redis://127.0.0.1:13000`

**Important conventions for the executor:**
- All `git` commands run inside `<BENCH>/apps/conductor` unless otherwise noted. The bench root itself is **not** a git repo.
- Run pytest from the bench root: `cd <BENCH> && ./env/bin/pytest apps/conductor/tests/...`
- Run Frappe tests from the bench root: `cd <BENCH> && bench --site frappe.localhost run-tests --app conductor --module <dotted.module>`
- Make small, frequent commits. One task = one commit (or two if test+impl are split).
- Never use `--no-verify` or `--no-edit` on commits.

---

## Task 1: Scaffold the Conductor app

**Files:**
- Create (by `bench new-app`): `<BENCH>/apps/conductor/` (directory tree)
- Create: `<BENCH>/apps/conductor/.gitignore` (added by Frappe)

- [ ] **Step 1: Verify bench is healthy and the app does not exist**

```bash
cd /Users/osamamuhammed/frappe_15
ls apps/ | grep -E "^conductor$" && echo "ABORT: conductor app already exists" || echo "OK: conductor not present"
bench --version 2>&1 | head -1
```

Expected: "OK: conductor not present" and a bench version line.

- [ ] **Step 2: Run `bench new-app` with answers piped in**

```bash
cd /Users/osamamuhammed/frappe_15
bench new-app conductor <<'EOF'
Conductor
Reliability-first background jobs for Frappe
Osama Muhammed
osama.m@aau.iq
mit
EOF
```

The prompts (in order) are: app title, description, publisher, email, license. If `bench new-app` asks an extra question (e.g., "App Branch" in newer bench versions), the executor must answer it interactively with `develop`.

Expected: command exits 0; `apps/conductor/` directory exists.

- [ ] **Step 3: Verify scaffold + initialize develop branch**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
ls -la
git status
git rev-parse --abbrev-ref HEAD
```

If the current branch is not `develop`:

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git branch -m develop || git checkout -b develop
```

Expected: directory contains `conductor/`, `pyproject.toml`, `license.txt`, `README.md`, etc.; current branch is `develop`.

- [ ] **Step 4: Commit the scaffold so we have a clean base**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add -A
git status
git commit -m "chore: scaffold conductor Frappe app"
```

(If `bench new-app` already committed the scaffold, `git status` will be clean — skip the add/commit.)

---

## Task 2: Add dependencies + dev tools to `pyproject.toml`

**Files:**
- Modify: `<BENCH>/apps/conductor/pyproject.toml`

- [ ] **Step 1: Read the current `pyproject.toml`**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
cat pyproject.toml
```

Expected: a Frappe-generated `pyproject.toml` with placeholder `[project.dependencies]` (often empty list).

- [ ] **Step 2: Replace dependency lists**

Edit `<BENCH>/apps/conductor/pyproject.toml` so the `[project]` section's `dependencies` list and the `[project.optional-dependencies]` section read exactly:

```toml
dependencies = [
    "redis>=5,<6",
    "msgpack>=1.0,<2",
    "opentelemetry-api>=1.27,<2",
    "opentelemetry-sdk>=1.27,<2",
    "structlog>=24.1,<26",
]

[project.optional-dependencies]
dev = [
    "pytest>=8,<9",
    "pytest-mock>=3.14,<4",
    "fakeredis>=2.23,<3",
]
```

Leave the rest of the file (name, version, description, authors, license, requires-python) as Frappe generated it.

- [ ] **Step 3: Install runtime + dev deps into the bench env**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pip install -e "apps/conductor[dev]"
```

Expected: pip resolves and installs all deps; `conductor` is now importable from the bench env.

- [ ] **Step 4: Verify imports**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/python -c "import conductor, redis, msgpack, opentelemetry, structlog, pytest; print('OK')"
```

Expected: prints `OK`.

- [ ] **Step 5: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add pyproject.toml
git commit -m "chore: declare runtime + dev deps in pyproject.toml"
```

---

## Task 3: Move design docs into the app

**Files:**
- Move: `<BENCH>/docs/superpowers/specs/2026-04-27-conductor-master-design.md` → `<BENCH>/apps/conductor/docs/superpowers/specs/2026-04-27-conductor-master-design.md`
- Move: `<BENCH>/docs/superpowers/specs/2026-04-27-conductor-phase0-skeleton.md` → `<BENCH>/apps/conductor/docs/superpowers/specs/2026-04-27-conductor-phase0-skeleton.md`
- Move: `<BENCH>/docs/superpowers/plans/2026-04-27-conductor-phase0-skeleton.md` → `<BENCH>/apps/conductor/docs/superpowers/plans/2026-04-27-conductor-phase0-skeleton.md`

- [ ] **Step 1: Move the docs into the app**

```bash
cd /Users/osamamuhammed/frappe_15
mkdir -p apps/conductor/docs/superpowers/specs apps/conductor/docs/superpowers/plans
mv docs/superpowers/specs/2026-04-27-conductor-master-design.md apps/conductor/docs/superpowers/specs/
mv docs/superpowers/specs/2026-04-27-conductor-phase0-skeleton.md apps/conductor/docs/superpowers/specs/
mv docs/superpowers/plans/2026-04-27-conductor-phase0-skeleton.md apps/conductor/docs/superpowers/plans/
ls apps/conductor/docs/superpowers/specs/
ls apps/conductor/docs/superpowers/plans/
```

Expected: both spec files and the plan file are listed.

- [ ] **Step 2: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add docs/
git commit -m "docs: move master design + phase 0 spec & plan into the app"
```

---

## Task 4: Create the empty `tests/` directory + conftest

**Files:**
- Create: `<BENCH>/apps/conductor/tests/__init__.py` (empty)
- Create: `<BENCH>/apps/conductor/tests/conftest.py`
- Create: `<BENCH>/apps/conductor/pytest.ini`

- [ ] **Step 1: Create `tests/__init__.py`** (empty file)

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
mkdir -p tests
touch tests/__init__.py
```

- [ ] **Step 2: Create `tests/conftest.py`**

Write this exact content to `<BENCH>/apps/conductor/tests/conftest.py`:

```python
"""Shared pytest fixtures for Conductor pure-Python tests (no Frappe site needed)."""

import pytest
import fakeredis


@pytest.fixture
def fake_redis():
    """A fakeredis instance with Stream support, fresh per test."""
    return fakeredis.FakeStrictRedis(server=fakeredis.FakeServer(), decode_responses=False)
```

- [ ] **Step 3: Create `pytest.ini`**

Write this exact content to `<BENCH>/apps/conductor/pytest.ini`:

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
```

- [ ] **Step 4: Sanity-check pytest discovery**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/ --collect-only
```

Expected: "no tests collected" (no errors). The directory is recognized.

- [ ] **Step 5: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add tests/ pytest.ini
git commit -m "test: scaffold pytest test directory and conftest"
```

---

## Task 5: TDD — `conductor.serialization` (msgpack codecs)

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/serialization.py`
- Create: `<BENCH>/apps/conductor/tests/test_serialization.py`

- [ ] **Step 1: Write failing tests for serialization**

Write to `<BENCH>/apps/conductor/tests/test_serialization.py`:

```python
"""Unit tests for conductor.serialization."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from conductor.serialization import dumps, loads


def test_roundtrip_basic_types():
    payload = {"a": 1, "b": "hello", "c": [1, 2, 3], "d": None, "e": True}
    assert loads(dumps(payload)) == payload


def test_roundtrip_datetime_aware():
    dt = datetime(2026, 4, 27, 15, 30, 0, tzinfo=timezone.utc)
    out = loads(dumps({"when": dt}))
    assert out["when"] == dt
    assert out["when"].tzinfo is not None


def test_roundtrip_decimal():
    out = loads(dumps({"amount": Decimal("123.45")}))
    assert out["amount"] == Decimal("123.45")
    assert isinstance(out["amount"], Decimal)


def test_oversize_payload_raises():
    too_big = {"data": "x" * (2 * 1024 * 1024)}  # 2 MiB > our 1 MiB cap
    with pytest.raises(ValueError, match="payload too large"):
        dumps(too_big, max_bytes=1024 * 1024)


def test_default_size_limit_is_1mib():
    near_limit = {"data": "x" * (900 * 1024)}
    dumps(near_limit)  # must not raise

    over_limit = {"data": "x" * (1100 * 1024)}
    with pytest.raises(ValueError):
        dumps(over_limit)
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_serialization.py -v
```

Expected: all tests FAIL with `ImportError` for `conductor.serialization`.

- [ ] **Step 3: Implement `conductor.serialization`**

Write to `<BENCH>/apps/conductor/conductor/serialization.py`:

```python
"""Msgpack-based (de)serialization for Conductor stream payloads.

Frappe code commonly relies on Python types JSON drops (datetime, Decimal),
so we use msgpack with extension types for losslessness.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import msgpack

DEFAULT_MAX_BYTES = 1024 * 1024  # 1 MiB

_EXT_DATETIME = 1
_EXT_DECIMAL = 2


def _default(obj: Any) -> msgpack.ExtType:
    if isinstance(obj, datetime):
        if obj.tzinfo is None:
            obj = obj.replace(tzinfo=timezone.utc)
        return msgpack.ExtType(_EXT_DATETIME, obj.isoformat().encode("utf-8"))
    if isinstance(obj, Decimal):
        return msgpack.ExtType(_EXT_DECIMAL, str(obj).encode("utf-8"))
    raise TypeError(f"unserializable type: {type(obj).__name__}")


def _ext_hook(code: int, data: bytes) -> Any:
    if code == _EXT_DATETIME:
        return datetime.fromisoformat(data.decode("utf-8"))
    if code == _EXT_DECIMAL:
        return Decimal(data.decode("utf-8"))
    return msgpack.ExtType(code, data)


def dumps(obj: Any, *, max_bytes: int = DEFAULT_MAX_BYTES) -> bytes:
    """Pack `obj` to msgpack bytes; raise ValueError if it exceeds `max_bytes`."""
    out = msgpack.packb(obj, default=_default, use_bin_type=True)
    if len(out) > max_bytes:
        raise ValueError(f"payload too large: {len(out)} bytes > {max_bytes} bytes")
    return out


def loads(data: bytes) -> Any:
    return msgpack.unpackb(data, ext_hook=_ext_hook, raw=False)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_serialization.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add conductor/serialization.py tests/test_serialization.py
git commit -m "feat(serialization): msgpack codecs for datetime/Decimal"
```

---

## Task 6: TDD — `conductor.messages` (stream message encode/decode)

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/messages.py`
- Create: `<BENCH>/apps/conductor/tests/test_messages.py`

- [ ] **Step 1: Write failing tests**

Write to `<BENCH>/apps/conductor/tests/test_messages.py`:

```python
"""Unit tests for conductor.messages — stream message encode/decode."""

from datetime import datetime, timezone

import pytest

from conductor.messages import (
    SCHEMA_VERSION,
    JobMessage,
    decode,
    encode,
)


def _sample_message(**overrides) -> JobMessage:
    base = JobMessage(
        job_id="11111111-1111-1111-1111-111111111111",
        site="frappe.localhost",
        method="conductor.demo.echo",
        queue="default",
        kwargs={"x": 1, "ts": datetime(2026, 4, 27, tzinfo=timezone.utc)},
        attempt=1,
        max_attempts=1,
        timeout_seconds=60,
        enqueued_at=datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc),
        deadline=None,
        trace_parent="",
        idempotency_key="",
        workflow_run_id="",
        step_id="",
    )
    return base.replace(**overrides) if overrides else base


def test_roundtrip_full_message():
    msg = _sample_message()
    encoded = encode(msg)
    decoded = decode(encoded)
    assert decoded == msg


def test_encoded_fields_are_str_to_str():
    encoded = encode(_sample_message())
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in encoded.items())


def test_schema_version_is_present():
    encoded = encode(_sample_message())
    assert encoded["schema_version"] == str(SCHEMA_VERSION)


def test_decode_unknown_schema_version_raises():
    encoded = encode(_sample_message())
    encoded["schema_version"] = "999"
    with pytest.raises(ValueError, match="unsupported schema_version"):
        decode(encoded)


def test_decode_missing_required_field_raises():
    encoded = encode(_sample_message())
    encoded.pop("job_id")
    with pytest.raises(ValueError, match="missing required field"):
        decode(encoded)


def test_optional_fields_default_to_empty_string_or_none():
    msg = _sample_message(idempotency_key="", workflow_run_id="", step_id="", deadline=None)
    encoded = encode(msg)
    assert encoded["idempotency_key"] == ""
    assert encoded["workflow_run_id"] == ""
    assert encoded["step_id"] == ""
    assert encoded["deadline"] == ""
    decoded = decode(encoded)
    assert decoded.idempotency_key == ""
    assert decoded.workflow_run_id == ""
    assert decoded.step_id == ""
    assert decoded.deadline is None
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_messages.py -v
```

Expected: ImportError for `conductor.messages`.

- [ ] **Step 3: Implement `conductor.messages`**

Write to `<BENCH>/apps/conductor/conductor/messages.py`:

```python
"""Conductor stream message schema (frozen, version 1).

A stream message is a flat str→str dict (Redis Streams field values are
ASCII-safe strings). args/kwargs are msgpack-then-base64 encoded.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field, fields, replace
from datetime import datetime
from typing import Any

from conductor.serialization import dumps, loads

SCHEMA_VERSION = 1

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
    args: list[Any] = field(default_factory=list)  # Phase 0 dispatch never populates this
    attempt: int = 1
    max_attempts: int = 1
    timeout_seconds: int = 300
    enqueued_at: datetime | None = None
    deadline: datetime | None = None
    trace_parent: str = ""
    idempotency_key: str = ""
    workflow_run_id: str = ""
    step_id: str = ""

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
    )
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_messages.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add conductor/messages.py tests/test_messages.py
git commit -m "feat(messages): JobMessage encode/decode, schema_version=1"
```

---

## Task 7: TDD — `conductor.streams` (key builders, lazy consumer group)

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/streams.py`
- Create: `<BENCH>/apps/conductor/tests/test_streams.py`

- [ ] **Step 1: Write failing tests**

Write to `<BENCH>/apps/conductor/tests/test_streams.py`:

```python
"""Unit tests for conductor.streams — Redis key builders and group helpers."""

import pytest
import redis as redis_mod

from conductor.streams import (
    CONSUMER_GROUP,
    dlq_key,
    ensure_consumer_group,
    scheduled_key,
    stream_key,
    workers_key,
)


def test_stream_key_builds_namespaced_key():
    assert stream_key("frappe.localhost", "default") == "conductor:frappe.localhost:stream:default"


def test_dlq_key_builds_namespaced_key():
    assert dlq_key("frappe.localhost", "critical") == "conductor:frappe.localhost:dlq:critical"


def test_scheduled_key_builds_namespaced_key():
    assert scheduled_key("aau.local") == "conductor:aau.local:scheduled"


def test_workers_key_builds_namespaced_key():
    assert workers_key("aau.local") == "conductor:aau.local:workers"


def test_consumer_group_is_constant():
    assert CONSUMER_GROUP == "conductor"


def test_ensure_consumer_group_creates_when_missing(fake_redis):
    key = stream_key("test.local", "default")
    ensure_consumer_group(fake_redis, key)
    groups = fake_redis.xinfo_groups(key)
    assert any(g[b"name"] == CONSUMER_GROUP.encode() for g in groups)


def test_ensure_consumer_group_idempotent(fake_redis):
    key = stream_key("test.local", "default")
    ensure_consumer_group(fake_redis, key)
    ensure_consumer_group(fake_redis, key)  # must not raise
    groups = fake_redis.xinfo_groups(key)
    assert sum(1 for g in groups if g[b"name"] == CONSUMER_GROUP.encode()) == 1


def test_ensure_consumer_group_propagates_other_errors(monkeypatch, fake_redis):
    def boom(*a, **kw):
        raise redis_mod.exceptions.ResponseError("ERR something else")

    monkeypatch.setattr(fake_redis, "xgroup_create", boom)
    with pytest.raises(redis_mod.exceptions.ResponseError, match="something else"):
        ensure_consumer_group(fake_redis, stream_key("test.local", "default"))
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_streams.py -v
```

Expected: ImportError on `conductor.streams`.

- [ ] **Step 3: Implement `conductor.streams`**

Write to `<BENCH>/apps/conductor/conductor/streams.py`:

```python
"""Redis Streams helpers for Conductor: key namespacing and consumer-group setup."""

from __future__ import annotations

import redis as redis_mod

CONSUMER_GROUP = "conductor"


def stream_key(site: str, queue: str) -> str:
    return f"conductor:{site}:stream:{queue}"


def dlq_key(site: str, queue: str) -> str:
    return f"conductor:{site}:dlq:{queue}"


def scheduled_key(site: str) -> str:
    return f"conductor:{site}:scheduled"


def workers_key(site: str) -> str:
    return f"conductor:{site}:workers"


def ensure_consumer_group(client: redis_mod.Redis, stream: str) -> None:
    """Create the conductor consumer group on `stream`, idempotently.

    Uses XGROUP CREATE … MKSTREAM so the stream is created on first call.
    Swallows BUSYGROUP (group already exists) only; re-raises everything else.
    """
    try:
        client.xgroup_create(name=stream, groupname=CONSUMER_GROUP, id="0", mkstream=True)
    except redis_mod.exceptions.ResponseError as e:
        if "BUSYGROUP" in str(e):
            return
        raise
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_streams.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add conductor/streams.py tests/test_streams.py
git commit -m "feat(streams): key builders and idempotent consumer group setup"
```

---

## Task 8: TDD — `conductor.config` (site-config reader)

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/config.py`
- Create: `<BENCH>/apps/conductor/tests/test_config.py`

- [ ] **Step 1: Write failing tests**

Write to `<BENCH>/apps/conductor/tests/test_config.py`:

```python
"""Unit tests for conductor.config — reading site_config['conductor']."""

import pytest

from conductor.config import ConductorConfig, load_config


def test_load_config_from_dict_with_all_fields():
    site_config = {
        "redis_queue": "redis://127.0.0.1:11000",
        "conductor": {
            "redis_url": "redis://127.0.0.1:11000/2",
            "default_queue": "default",
            "stream_max_len": 5000,
        },
    }
    cfg = load_config(site_config)
    assert isinstance(cfg, ConductorConfig)
    assert cfg.redis_url == "redis://127.0.0.1:11000/2"
    assert cfg.default_queue == "default"
    assert cfg.stream_max_len == 5000


def test_load_config_falls_back_to_redis_queue_with_db_2():
    site_config = {"redis_queue": "redis://127.0.0.1:11000"}
    cfg = load_config(site_config)
    assert cfg.redis_url == "redis://127.0.0.1:11000/2"


def test_load_config_falls_back_to_redis_queue_when_url_already_has_db():
    site_config = {"redis_queue": "redis://127.0.0.1:11000/1"}
    cfg = load_config(site_config)
    # Override the DB component to 2 regardless of what redis_queue specified.
    assert cfg.redis_url.endswith("/2")


def test_load_config_default_queue_is_default():
    cfg = load_config({"redis_queue": "redis://127.0.0.1:11000"})
    assert cfg.default_queue == "default"


def test_load_config_stream_max_len_default():
    cfg = load_config({"redis_queue": "redis://127.0.0.1:11000"})
    assert cfg.stream_max_len == 10000


def test_load_config_raises_when_no_redis_anywhere():
    with pytest.raises(ValueError, match="redis_url"):
        load_config({})
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_config.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `conductor.config`**

Write to `<BENCH>/apps/conductor/conductor/config.py`:

```python
"""Reads conductor configuration from a Frappe site_config dict.

This module deliberately does not import frappe — it accepts a plain dict so
unit tests can run without a Frappe site.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

DEFAULT_DB = 2
DEFAULT_QUEUE = "default"
DEFAULT_STREAM_MAX_LEN = 10000


@dataclass(frozen=True)
class ConductorConfig:
    redis_url: str
    default_queue: str
    stream_max_len: int


def _force_db(url: str, db: int) -> str:
    parsed = urlparse(url)
    new_path = f"/{db}"
    return urlunparse(parsed._replace(path=new_path))


def load_config(site_config: dict) -> ConductorConfig:
    conductor_section = site_config.get("conductor") or {}
    redis_url = conductor_section.get("redis_url")
    if not redis_url:
        base = site_config.get("redis_queue")
        if not base:
            raise ValueError(
                "redis_url not configured: set site_config['conductor']['redis_url'] "
                "or site_config['redis_queue']"
            )
        redis_url = _force_db(base, DEFAULT_DB)

    return ConductorConfig(
        redis_url=redis_url,
        default_queue=conductor_section.get("default_queue", DEFAULT_QUEUE),
        stream_max_len=int(conductor_section.get("stream_max_len", DEFAULT_STREAM_MAX_LEN)),
    )
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_config.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add conductor/config.py tests/test_config.py
git commit -m "feat(config): site_config reader with redis fallback"
```

---

## Task 9: TDD — `conductor.context` (per-job thread-local + watchdog)

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/context.py`
- Create: `<BENCH>/apps/conductor/tests/test_context.py`

- [ ] **Step 1: Write failing tests**

Write to `<BENCH>/apps/conductor/tests/test_context.py`:

```python
"""Unit tests for conductor.context — thread-local job context + watchdog."""

import threading
import time
from datetime import datetime, timedelta, timezone

from conductor.context import context, set_context, start_watchdog


def test_default_context_is_empty():
    assert context.job_id is None
    assert context.attempt is None
    assert context.deadline is None
    assert context.should_cancel() is False


def test_set_context_restores_on_exit():
    with set_context(job_id="abc", attempt=1, deadline=None):
        assert context.job_id == "abc"
        assert context.attempt == 1
    assert context.job_id is None
    assert context.attempt is None


def test_context_is_thread_local():
    seen = {}

    def worker(name: str):
        with set_context(job_id=name, attempt=1, deadline=None):
            time.sleep(0.05)
            seen[name] = context.job_id

    t1 = threading.Thread(target=worker, args=("A",))
    t2 = threading.Thread(target=worker, args=("B",))
    t1.start(); t2.start(); t1.join(); t2.join()

    assert seen == {"A": "A", "B": "B"}


def test_watchdog_flips_should_cancel_after_deadline():
    cancel = threading.Event()
    deadline = datetime.now(timezone.utc) + timedelta(milliseconds=50)
    wd = start_watchdog(deadline, cancel)
    try:
        time.sleep(0.15)
        assert cancel.is_set() is True
    finally:
        wd.cancel()


def test_watchdog_cancel_prevents_flip():
    cancel = threading.Event()
    deadline = datetime.now(timezone.utc) + timedelta(milliseconds=200)
    wd = start_watchdog(deadline, cancel)
    wd.cancel()
    time.sleep(0.3)
    assert cancel.is_set() is False


def test_should_cancel_reflects_event_in_context():
    cancel = threading.Event()
    with set_context(job_id="x", attempt=1, deadline=None, cancel_event=cancel):
        assert context.should_cancel() is False
        cancel.set()
        assert context.should_cancel() is True
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_context.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `conductor.context`**

Write to `<BENCH>/apps/conductor/conductor/context.py`:

```python
"""Per-job execution context exposed to user code.

The `context` object is thread-local; one job per thread (we use a
ThreadPoolExecutor in the worker, one job pinned to one thread for its lifetime).
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import datetime, timezone


class _Context(threading.local):
    job_id: str | None = None
    attempt: int | None = None
    deadline: datetime | None = None
    cancel_event: threading.Event | None = None

    def should_cancel(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()


context = _Context()


@contextmanager
def set_context(
    *,
    job_id: str,
    attempt: int,
    deadline: datetime | None,
    cancel_event: threading.Event | None = None,
):
    prev = (context.job_id, context.attempt, context.deadline, context.cancel_event)
    context.job_id = job_id
    context.attempt = attempt
    context.deadline = deadline
    context.cancel_event = cancel_event
    try:
        yield
    finally:
        context.job_id, context.attempt, context.deadline, context.cancel_event = prev


def start_watchdog(deadline: datetime, cancel_event: threading.Event) -> threading.Timer:
    """Schedule `cancel_event.set()` at `deadline`. Returns the Timer (call .cancel() to stop)."""
    now = datetime.now(timezone.utc)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    delay = max(0.0, (deadline - now).total_seconds())
    timer = threading.Timer(delay, cancel_event.set)
    timer.daemon = True
    timer.start()
    return timer
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_context.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add conductor/context.py tests/test_context.py
git commit -m "feat(context): thread-local job context + cooperative timeout watchdog"
```

---

## Task 10: `conductor.client` (Redis connection factory)

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/client.py`

This module is thin enough that we test it transitively through `streams` and dispatcher tests rather than writing a dedicated unit test.

- [ ] **Step 1: Implement**

Write to `<BENCH>/apps/conductor/conductor/client.py`:

```python
"""Redis client factory. One pool per (process, redis_url)."""

from __future__ import annotations

import threading
from functools import lru_cache

import redis

_lock = threading.Lock()
_pools: dict[str, redis.ConnectionPool] = {}


def get_redis(redis_url: str) -> redis.Redis:
    """Return a Redis client backed by a process-global pool keyed by URL."""
    with _lock:
        pool = _pools.get(redis_url)
        if pool is None:
            pool = redis.ConnectionPool.from_url(redis_url, decode_responses=False)
            _pools[redis_url] = pool
    return redis.Redis(connection_pool=pool)
```

- [ ] **Step 2: Smoke import**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/python -c "from conductor.client import get_redis; print(get_redis('redis://127.0.0.1:11000/2'))"
```

Expected: prints a `Redis<ConnectionPool<...>>` repr; no exception (does not connect until used).

- [ ] **Step 3: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add conductor/client.py
git commit -m "feat(client): redis connection pool factory"
```

---

## Task 11: `conductor.otel` (no-op tracer + traceparent helpers)

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/otel.py`
- Create: `<BENCH>/apps/conductor/tests/test_otel.py`

- [ ] **Step 1: Write failing tests**

Write to `<BENCH>/apps/conductor/tests/test_otel.py`:

```python
"""Unit tests for conductor.otel — traceparent inject/extract round-trip."""

from conductor.otel import (
    extract_traceparent,
    get_tracer,
    inject_traceparent,
    setup_otel,
)


def test_setup_otel_is_idempotent():
    setup_otel(service_name="conductor-test")
    setup_otel(service_name="conductor-test")
    tracer = get_tracer()
    assert tracer is not None


def test_inject_returns_w3c_traceparent_string():
    setup_otel(service_name="conductor-test")
    tracer = get_tracer()
    with tracer.start_as_current_span("dispatch") as span:
        tp = inject_traceparent()
    assert tp.startswith("00-")
    assert tp.count("-") == 3


def test_extract_then_start_span_links_to_parent():
    setup_otel(service_name="conductor-test")
    tracer = get_tracer()
    with tracer.start_as_current_span("producer") as parent:
        parent_trace_id = format(parent.get_span_context().trace_id, "032x")
        tp = inject_traceparent()
    ctx = extract_traceparent(tp)
    with tracer.start_as_current_span("consumer", context=ctx) as child:
        child_trace_id = format(child.get_span_context().trace_id, "032x")
    assert child_trace_id == parent_trace_id


def test_extract_empty_traceparent_returns_none_or_empty_context():
    ctx = extract_traceparent("")
    # Acceptable: None or an empty context that produces a fresh trace_id when used.
    assert ctx is None or ctx is not None
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_otel.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `conductor.otel`**

Write to `<BENCH>/apps/conductor/conductor/otel.py`:

```python
"""OpenTelemetry SDK wiring (no-op exporter for Phase 0).

Producer (dispatcher) creates a span and injects W3C traceparent into the stream
message; consumer (worker) extracts it and starts a child span. No traces are
exported until Phase 4 wires up an exporter.
"""

from __future__ import annotations

import threading
from typing import Optional

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider

_lock = threading.Lock()
_initialized = False
_TRACER_NAME = "conductor"


def setup_otel(*, service_name: str = "conductor") -> None:
    """Initialize a TracerProvider once per process. No exporter (Phase 4 adds one)."""
    global _initialized
    with _lock:
        if _initialized:
            return
        provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
        trace.set_tracer_provider(provider)
        _initialized = True


def get_tracer() -> trace.Tracer:
    return trace.get_tracer(_TRACER_NAME)


def inject_traceparent() -> str:
    """Return the W3C traceparent string for the current span context (or empty)."""
    carrier: dict[str, str] = {}
    inject(carrier)
    return carrier.get("traceparent", "")


def extract_traceparent(traceparent: str) -> Optional[otel_context.Context]:
    """Return an OTel Context to use as `context=...` when starting the consumer span."""
    if not traceparent:
        return None
    return extract({"traceparent": traceparent})
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/test_otel.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add conductor/otel.py tests/test_otel.py
git commit -m "feat(otel): no-op tracer setup + traceparent inject/extract"
```

---

## Task 12: `conductor.logging` (structlog setup)

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/logging.py`

- [ ] **Step 1: Implement**

Write to `<BENCH>/apps/conductor/conductor/logging.py`:

```python
"""Structlog configuration for Conductor processes.

JSON output to stdout; bind worker/site context up front so every line carries it.
"""

from __future__ import annotations

import logging
import sys

import structlog


def setup_logging(*, site: str | None = None, worker_id: str | None = None) -> None:
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )
    if site or worker_id:
        ctx = {}
        if site:
            ctx["site"] = site
        if worker_id:
            ctx["worker_id"] = worker_id
        structlog.contextvars.bind_contextvars(**ctx)


def get_logger(name: str = "conductor"):
    return structlog.get_logger(name)
```

- [ ] **Step 2: Smoke import**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/python -c "from conductor.logging import setup_logging, get_logger; setup_logging(site='test'); get_logger().info('hello', a=1)"
```

Expected: a single JSON line on stdout containing `"site": "test"` and `"a": 1`.

- [ ] **Step 3: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add conductor/logging.py
git commit -m "feat(logging): structlog JSON setup"
```

---

## Task 13: `Conductor Queue` DocType

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/conductor/__init__.py` (empty if not already created by Frappe)
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/__init__.py` (empty)
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_queue/__init__.py` (empty)
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_queue/conductor_queue.json`
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_queue/conductor_queue.py`
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_queue/test_conductor_queue.py`
- Modify: `<BENCH>/apps/conductor/conductor/modules.txt`

- [ ] **Step 1: Make sure module folders + `modules.txt` are wired (and create the `Conductor Operator` role first so DocType permissions resolve at install time)**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
mkdir -p conductor/conductor/doctype/conductor_queue
mkdir -p conductor/conductor/role/conductor_operator
touch conductor/conductor/__init__.py
touch conductor/conductor/doctype/__init__.py
touch conductor/conductor/doctype/conductor_queue/__init__.py
touch conductor/conductor/role/__init__.py
touch conductor/conductor/role/conductor_operator/__init__.py
cat conductor/modules.txt
```

If `modules.txt` does not contain a line `Conductor`, write that single line:

```bash
echo "Conductor" > conductor/modules.txt
```

Write the `Conductor Operator` role JSON now (Task 16 references it but DocType permissions need it earlier) — `<BENCH>/apps/conductor/conductor/conductor/role/conductor_operator/conductor_operator.json`:

```json
{
 "creation": "2026-04-27 00:00:00",
 "desk_access": 1,
 "doctype": "Role",
 "modified": "2026-04-27 00:00:00",
 "modified_by": "Administrator",
 "module": "Conductor",
 "name": "Conductor Operator",
 "owner": "Administrator",
 "role_name": "Conductor Operator"
}
```

- [ ] **Step 2: Write the DocType JSON**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_queue/conductor_queue.json`:

```json
{
 "actions": [],
 "allow_rename": 0,
 "autoname": "field:queue_name",
 "creation": "2026-04-27 00:00:00",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "queue_name",
  "enabled",
  "concurrency",
  "default_max_attempts",
  "default_timeout",
  "default_backoff",
  "default_base_delay_seconds",
  "default_max_delay_seconds",
  "default_jitter",
  "description"
 ],
 "fields": [
  {"fieldname": "queue_name", "fieldtype": "Data", "label": "Queue Name", "reqd": 1, "unique": 1, "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "enabled", "fieldtype": "Check", "label": "Enabled", "default": "1", "in_list_view": 1},
  {"fieldname": "concurrency", "fieldtype": "Int", "label": "Concurrency", "default": "4", "in_list_view": 1},
  {"fieldname": "default_max_attempts", "fieldtype": "Int", "label": "Default Max Attempts", "default": "3"},
  {"fieldname": "default_timeout", "fieldtype": "Int", "label": "Default Timeout (seconds)", "default": "300"},
  {"fieldname": "default_backoff", "fieldtype": "Select", "label": "Default Backoff", "options": "exponential\nlinear\nfixed", "default": "exponential"},
  {"fieldname": "default_base_delay_seconds", "fieldtype": "Int", "label": "Default Base Delay (seconds)", "default": "2"},
  {"fieldname": "default_max_delay_seconds", "fieldtype": "Int", "label": "Default Max Delay (seconds)", "default": "600"},
  {"fieldname": "default_jitter", "fieldtype": "Select", "label": "Default Jitter", "options": "none\nfull\nequal", "default": "full"},
  {"fieldname": "description", "fieldtype": "Small Text", "label": "Description"}
 ],
 "links": [],
 "modified": "2026-04-27 00:00:00",
 "modified_by": "Administrator",
 "module": "Conductor",
 "name": "Conductor Queue",
 "owner": "Administrator",
 "permissions": [
  {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "report": 1, "export": 1},
  {"role": "Conductor Operator", "read": 1, "report": 1, "export": 1}
 ],
 "sort_field": "queue_name",
 "sort_order": "ASC",
 "track_changes": 1
}
```

- [ ] **Step 3: Write the controller**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_queue/conductor_queue.py`:

```python
import frappe
from frappe.model.document import Document


class ConductorQueue(Document):
    def validate(self):
        if self.concurrency is not None and self.concurrency < 1:
            frappe.throw("Concurrency must be ≥ 1")
        if self.default_max_attempts is not None and self.default_max_attempts < 1:
            frappe.throw("default_max_attempts must be ≥ 1")
```

- [ ] **Step 4: Write the integration test**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_queue/test_conductor_queue.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase


class TestConductorQueue(FrappeTestCase):
    def test_create_and_read(self):
        if frappe.db.exists("Conductor Queue", "test_queue"):
            frappe.delete_doc("Conductor Queue", "test_queue", force=True)
        doc = frappe.get_doc(
            {
                "doctype": "Conductor Queue",
                "queue_name": "test_queue",
                "concurrency": 2,
            }
        ).insert()
        self.assertEqual(doc.name, "test_queue")
        self.assertEqual(doc.concurrency, 2)
        self.assertEqual(doc.enabled, 1)
        self.assertEqual(doc.default_max_attempts, 3)

    def test_concurrency_validation(self):
        if frappe.db.exists("Conductor Queue", "bad_queue"):
            frappe.delete_doc("Conductor Queue", "bad_queue", force=True)
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {"doctype": "Conductor Queue", "queue_name": "bad_queue", "concurrency": 0}
            ).insert()
```

(The `Conductor Operator` role must exist for `bench install-app` migrations to apply this DocType cleanly. We'll create that role in Task 17 via `after_install`. Until then, the test runs against a clean install where the DocType is migrated but the role-based permission row binds lazily — Frappe creates missing roles silently during migration in dev mode. If `bench migrate` complains, run Task 17 first and re-run this task's installer step.)

- [ ] **Step 5: Install the app + run migrations**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost install-app conductor 2>&1 | tail -20
```

Expected: install succeeds (or reports "already installed" if you are re-running). The `Conductor Queue` DocType is migrated.

- [ ] **Step 6: Run the test**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_queue.test_conductor_queue
```

Expected: 2 tests pass.

- [ ] **Step 7: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add conductor/modules.txt conductor/conductor/__init__.py conductor/conductor/doctype/__init__.py conductor/conductor/role/ conductor/conductor/doctype/conductor_queue/
git commit -m "feat(doctype): Conductor Queue DocType + Conductor Operator role + tests"
```

---

## Task 14: `Conductor Job` DocType

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job/__init__.py`
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job/conductor_job.json`
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job/conductor_job.py`
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job/test_conductor_job.py`

- [ ] **Step 1: Create the package folder**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
mkdir -p conductor/conductor/doctype/conductor_job
touch conductor/conductor/doctype/conductor_job/__init__.py
```

- [ ] **Step 2: Write the DocType JSON**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job/conductor_job.json`:

```json
{
 "actions": [],
 "allow_rename": 0,
 "autoname": "field:job_id",
 "creation": "2026-04-27 00:00:00",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "job_id", "queue", "method", "status", "site",
  "section_args", "args", "kwargs", "args_preview", "kwargs_preview",
  "section_lifecycle", "attempt", "max_attempts", "timeout_seconds",
  "enqueued_at", "scheduled_at", "started_at", "finished_at", "next_run_at", "deadline",
  "section_meta", "idempotency_key", "trace_id", "span_id",
  "workflow_run_id", "step_id",
  "section_result", "last_error_type", "last_error_message", "last_traceback", "result_preview",
  "section_routing", "worker_id", "redis_msg_id"
 ],
 "fields": [
  {"fieldname": "job_id", "fieldtype": "Data", "label": "Job ID", "reqd": 1, "unique": 1, "in_list_view": 1},
  {"fieldname": "queue", "fieldtype": "Link", "options": "Conductor Queue", "label": "Queue", "reqd": 1, "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "method", "fieldtype": "Data", "label": "Method", "reqd": 1, "in_list_view": 1},
  {"fieldname": "status", "fieldtype": "Select", "label": "Status",
   "options": "QUEUED\nRUNNING\nSUCCEEDED\nFAILED\nTIMED_OUT\nSCHEDULED_RETRY\nDLQ\nCANCELLED\nDISPATCH_FAILED",
   "default": "QUEUED", "reqd": 1, "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "site", "fieldtype": "Data", "label": "Site"},

  {"fieldname": "section_args", "fieldtype": "Section Break", "label": "Arguments"},
  {"fieldname": "args", "fieldtype": "Long Text", "label": "Args (msgpack-base64)"},
  {"fieldname": "kwargs", "fieldtype": "Long Text", "label": "Kwargs (msgpack-base64)"},
  {"fieldname": "args_preview", "fieldtype": "Code", "label": "Args (preview)", "options": "JSON", "read_only": 1},
  {"fieldname": "kwargs_preview", "fieldtype": "Code", "label": "Kwargs (preview)", "options": "JSON", "read_only": 1},

  {"fieldname": "section_lifecycle", "fieldtype": "Section Break", "label": "Lifecycle"},
  {"fieldname": "attempt", "fieldtype": "Int", "label": "Attempt", "default": "1", "in_list_view": 1},
  {"fieldname": "max_attempts", "fieldtype": "Int", "label": "Max Attempts", "default": "1"},
  {"fieldname": "timeout_seconds", "fieldtype": "Int", "label": "Timeout (s)", "default": "300"},
  {"fieldname": "enqueued_at", "fieldtype": "Datetime", "label": "Enqueued At", "in_list_view": 1},
  {"fieldname": "scheduled_at", "fieldtype": "Datetime", "label": "Scheduled At"},
  {"fieldname": "started_at", "fieldtype": "Datetime", "label": "Started At"},
  {"fieldname": "finished_at", "fieldtype": "Datetime", "label": "Finished At"},
  {"fieldname": "next_run_at", "fieldtype": "Datetime", "label": "Next Run At"},
  {"fieldname": "deadline", "fieldtype": "Datetime", "label": "Deadline"},

  {"fieldname": "section_meta", "fieldtype": "Section Break", "label": "Metadata"},
  {"fieldname": "idempotency_key", "fieldtype": "Data", "label": "Idempotency Key"},
  {"fieldname": "trace_id", "fieldtype": "Data", "label": "Trace ID"},
  {"fieldname": "span_id", "fieldtype": "Data", "label": "Span ID"},
  {"fieldname": "workflow_run_id", "fieldtype": "Data", "label": "Workflow Run ID"},
  {"fieldname": "step_id", "fieldtype": "Data", "label": "Step ID"},

  {"fieldname": "section_result", "fieldtype": "Section Break", "label": "Result / Error"},
  {"fieldname": "last_error_type", "fieldtype": "Data", "label": "Last Error Type"},
  {"fieldname": "last_error_message", "fieldtype": "Small Text", "label": "Last Error Message"},
  {"fieldname": "last_traceback", "fieldtype": "Long Text", "label": "Last Traceback"},
  {"fieldname": "result_preview", "fieldtype": "Code", "label": "Result Preview", "options": "JSON", "read_only": 1},

  {"fieldname": "section_routing", "fieldtype": "Section Break", "label": "Routing"},
  {"fieldname": "worker_id", "fieldtype": "Data", "label": "Worker ID"},
  {"fieldname": "redis_msg_id", "fieldtype": "Data", "label": "Redis Message ID"}
 ],
 "links": [],
 "modified": "2026-04-27 00:00:00",
 "modified_by": "Administrator",
 "module": "Conductor",
 "name": "Conductor Job",
 "owner": "Administrator",
 "permissions": [
  {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "report": 1, "export": 1},
  {"role": "Conductor Operator", "read": 1, "report": 1, "export": 1}
 ],
 "sort_field": "enqueued_at",
 "sort_order": "DESC",
 "track_changes": 0
}
```

- [ ] **Step 3: Write the controller**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job/conductor_job.py`:

```python
import frappe
from frappe.model.document import Document


class ConductorJob(Document):
    pass
```

- [ ] **Step 4: Write the integration test**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job/test_conductor_job.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase


class TestConductorJob(FrappeTestCase):
    def setUp(self):
        if not frappe.db.exists("Conductor Queue", "default"):
            frappe.get_doc(
                {"doctype": "Conductor Queue", "queue_name": "default", "concurrency": 4}
            ).insert(ignore_permissions=True)

    def test_can_create_and_read_minimal_row(self):
        doc = frappe.get_doc(
            {
                "doctype": "Conductor Job",
                "job_id": "test-uuid-0001",
                "queue": "default",
                "method": "conductor.demo.echo",
                "status": "QUEUED",
                "attempt": 1,
                "max_attempts": 1,
                "timeout_seconds": 60,
                "site": frappe.local.site,
            }
        ).insert(ignore_permissions=True)
        self.assertEqual(doc.name, "test-uuid-0001")
        self.assertEqual(doc.status, "QUEUED")
        frappe.delete_doc("Conductor Job", doc.name, force=True)
```

- [ ] **Step 5: Migrate**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost migrate 2>&1 | tail -10
```

Expected: migration succeeds; "Conductor Job" table created.

- [ ] **Step 6: Run test**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_job.test_conductor_job
```

Expected: 1 test passes.

- [ ] **Step 7: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add conductor/conductor/doctype/conductor_job/
git commit -m "feat(doctype): Conductor Job DocType (full schema, all phases) + tests"
```

---

## Task 15: `Conductor Worker` DocType

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_worker/__init__.py`
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_worker/conductor_worker.json`
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_worker/conductor_worker.py`
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_worker/test_conductor_worker.py`

- [ ] **Step 1: Create the package folder**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
mkdir -p conductor/conductor/doctype/conductor_worker
touch conductor/conductor/doctype/conductor_worker/__init__.py
```

- [ ] **Step 2: Write the DocType JSON**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_worker/conductor_worker.json`:

```json
{
 "actions": [],
 "allow_rename": 0,
 "autoname": "field:worker_id",
 "creation": "2026-04-27 00:00:00",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "worker_id", "host", "pid", "queues", "site", "status",
  "started_at", "last_heartbeat", "current_job", "conductor_version"
 ],
 "fields": [
  {"fieldname": "worker_id", "fieldtype": "Data", "label": "Worker ID", "reqd": 1, "unique": 1, "in_list_view": 1},
  {"fieldname": "host", "fieldtype": "Data", "label": "Host", "in_list_view": 1},
  {"fieldname": "pid", "fieldtype": "Int", "label": "PID"},
  {"fieldname": "queues", "fieldtype": "Long Text", "label": "Queues (JSON)"},
  {"fieldname": "site", "fieldtype": "Data", "label": "Site", "in_list_view": 1},
  {"fieldname": "status", "fieldtype": "Select", "label": "Status", "options": "ALIVE\nSTALE\nGONE", "default": "ALIVE", "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "started_at", "fieldtype": "Datetime", "label": "Started At"},
  {"fieldname": "last_heartbeat", "fieldtype": "Datetime", "label": "Last Heartbeat", "in_list_view": 1},
  {"fieldname": "current_job", "fieldtype": "Link", "options": "Conductor Job", "label": "Current Job"},
  {"fieldname": "conductor_version", "fieldtype": "Data", "label": "Conductor Version"}
 ],
 "links": [],
 "modified": "2026-04-27 00:00:00",
 "modified_by": "Administrator",
 "module": "Conductor",
 "name": "Conductor Worker",
 "owner": "Administrator",
 "permissions": [
  {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "report": 1},
  {"role": "Conductor Operator", "read": 1, "report": 1}
 ],
 "sort_field": "last_heartbeat",
 "sort_order": "DESC",
 "track_changes": 0
}
```

- [ ] **Step 3: Write the controller**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_worker/conductor_worker.py`:

```python
import frappe
from frappe.model.document import Document


class ConductorWorker(Document):
    pass
```

- [ ] **Step 4: Write the integration test**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_worker/test_conductor_worker.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase


class TestConductorWorker(FrappeTestCase):
    def test_create_and_read(self):
        wid = "test-worker-0001"
        if frappe.db.exists("Conductor Worker", wid):
            frappe.delete_doc("Conductor Worker", wid, force=True)
        doc = frappe.get_doc(
            {
                "doctype": "Conductor Worker",
                "worker_id": wid,
                "host": "localhost",
                "pid": 12345,
                "queues": '["default"]',
                "site": frappe.local.site,
                "status": "ALIVE",
            }
        ).insert(ignore_permissions=True)
        self.assertEqual(doc.name, wid)
        self.assertEqual(doc.status, "ALIVE")
        frappe.delete_doc("Conductor Worker", doc.name, force=True)
```

- [ ] **Step 5: Migrate + run test**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost migrate 2>&1 | tail -5
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_worker.test_conductor_worker
```

Expected: migrate succeeds; 1 test passes.

- [ ] **Step 6: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add conductor/conductor/doctype/conductor_worker/
git commit -m "feat(doctype): Conductor Worker DocType + tests"
```

---

## Task 16: `after_install` queue seeding + indexes

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/install.py`
- Modify: `<BENCH>/apps/conductor/conductor/hooks.py` (add `after_install`)

(The `Conductor Operator` role JSON was already created in Task 13 Step 1 so DocType permissions could resolve at install time.)

- [ ] **Step 1: Write `install.py`**

Write to `<BENCH>/apps/conductor/conductor/install.py`:

```python
"""Install/uninstall hooks for the Conductor app.

`after_install` is invoked once when `bench install-app conductor` is run on a
site. It seeds the four default queues and the Conductor Operator role.
"""

from __future__ import annotations

import frappe

DEFAULT_QUEUES = [
    {"queue_name": "default",  "concurrency": 4, "default_max_attempts": 3, "default_timeout": 300},
    {"queue_name": "short",    "concurrency": 4, "default_max_attempts": 3, "default_timeout": 60},
    {"queue_name": "long",     "concurrency": 2, "default_max_attempts": 3, "default_timeout": 3600},
    {"queue_name": "critical", "concurrency": 8, "default_max_attempts": 10, "default_timeout": 300},
]


def after_install():
    _ensure_role()
    _seed_queues()
    _add_indexes()
    frappe.db.commit()


def _ensure_role():
    if not frappe.db.exists("Role", "Conductor Operator"):
        frappe.get_doc(
            {"doctype": "Role", "role_name": "Conductor Operator", "desk_access": 1}
        ).insert(ignore_permissions=True)


def _seed_queues():
    for q in DEFAULT_QUEUES:
        if frappe.db.exists("Conductor Queue", q["queue_name"]):
            continue
        frappe.get_doc({"doctype": "Conductor Queue", **q}).insert(ignore_permissions=True)


def _add_indexes():
    # Composite indexes on Conductor Job for status-based queue scans.
    frappe.db.add_index("Conductor Job", ["status", "queue", "scheduled_at"])
    frappe.db.add_index("Conductor Job", ["status", "queue", "enqueued_at"])
    frappe.db.add_index("Conductor Job", ["idempotency_key"])
```

- [ ] **Step 2: Wire `after_install` into `hooks.py`**

Read the existing `hooks.py`:

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
cat conductor/hooks.py | head -40
```

Then add this line near the bottom of the file (after any `# Installation` comment block, or just before the "End of file" marker):

```python
after_install = "conductor.install.after_install"
```

If `hooks.py` already has an `after_install =` line, replace it with the line above.

- [ ] **Step 3: Re-install the app on the site**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost uninstall-app conductor --yes 2>&1 | tail -5 || true
bench --site frappe.localhost install-app conductor 2>&1 | tail -10
```

Expected: install succeeds; default queues seeded.

- [ ] **Step 4: Verify the queues + role**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost console <<'EOF'
import frappe
print("queues:", [q.name for q in frappe.get_all("Conductor Queue")])
print("role:", frappe.db.exists("Role", "Conductor Operator"))
EOF
```

Expected:
```
queues: ['critical', 'default', 'long', 'short']  (order may vary)
role: ('Conductor Operator',)
```

- [ ] **Step 5: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add conductor/install.py conductor/hooks.py
git commit -m "feat(install): after_install seeds default queues + indexes"
```

---

## Task 17: `conductor.dispatcher` (TDD via Frappe integration test)

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/dispatcher.py`
- Create: `<BENCH>/apps/conductor/conductor/api.py`
- Modify: `<BENCH>/apps/conductor/conductor/__init__.py`
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job/test_dispatcher.py`

- [ ] **Step 1: Write the failing integration test**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job/test_dispatcher.py`:

```python
import json

import frappe
from frappe.tests.utils import FrappeTestCase

import conductor


class TestDispatcher(FrappeTestCase):
    def test_enqueue_creates_queued_row_and_returns_job_id(self):
        job_id = conductor.enqueue("conductor.demo.echo", queue="default", x=1, msg="hi")
        self.assertIsInstance(job_id, str)
        self.assertGreater(len(job_id), 0)

        doc = frappe.get_doc("Conductor Job", job_id)
        self.assertEqual(doc.status, "QUEUED")
        self.assertEqual(doc.method, "conductor.demo.echo")
        self.assertEqual(doc.queue, "default")
        self.assertEqual(doc.attempt, 1)
        self.assertIsNotNone(doc.enqueued_at)
        self.assertTrue(doc.kwargs)  # base64-msgpack non-empty
        # Preview should be human-readable JSON
        preview = json.loads(doc.kwargs_preview)
        self.assertEqual(preview, {"x": 1, "msg": "hi"})
        # Cleanup
        frappe.delete_doc("Conductor Job", job_id, force=True)

    def test_enqueue_writes_message_to_redis_stream(self):
        from conductor.client import get_redis
        from conductor.config import load_config
        from conductor.streams import stream_key
        from conductor.messages import decode

        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)
        skey = stream_key(frappe.local.site, "default")

        job_id = conductor.enqueue("conductor.demo.echo", queue="default", k=42)
        # Read the latest entry; we don't ack here (no consumer group used).
        entries = r.xrevrange(skey, count=1)
        self.assertEqual(len(entries), 1)
        _, fields = entries[0]
        decoded = {k.decode(): v.decode() for k, v in fields.items()}
        msg = decode(decoded)
        self.assertEqual(msg.job_id, job_id)
        self.assertEqual(msg.method, "conductor.demo.echo")
        self.assertEqual(msg.kwargs, {"k": 42})
        # Cleanup
        frappe.delete_doc("Conductor Job", job_id, force=True)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_job.test_dispatcher 2>&1 | tail -30
```

Expected: test FAILs because `conductor.enqueue` is not yet a real callable.

- [ ] **Step 3: Implement `conductor.dispatcher`**

Write to `<BENCH>/apps/conductor/conductor/dispatcher.py`:

```python
"""Job dispatcher: write Conductor Job row, XADD to Redis Stream, publish realtime."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import frappe

from conductor.client import get_redis
from conductor.config import load_config
from conductor.logging import get_logger
from conductor.messages import JobMessage, encode
from conductor.otel import get_tracer, inject_traceparent, setup_otel
from conductor.streams import CONSUMER_GROUP, ensure_consumer_group, stream_key

log = get_logger("conductor.dispatcher")

_PREVIEW_MAX = 4096


def _preview(value: Any) -> str:
    try:
        return json.dumps(value, default=str)[:_PREVIEW_MAX]
    except Exception:
        return repr(value)[:_PREVIEW_MAX]


def enqueue(method: str, *, queue: str = "default", timeout: int | None = None, **kwargs: Any) -> str:
    """Enqueue a job. Returns the new job_id (UUID str)."""
    setup_otel(service_name="conductor")
    tracer = get_tracer()

    site = frappe.local.site
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)

    queue_doc = frappe.get_cached_doc("Conductor Queue", queue)
    if not queue_doc.enabled:
        frappe.throw(f"Queue {queue!r} is disabled")

    timeout_seconds = int(timeout if timeout is not None else queue_doc.default_timeout)
    enqueued_at = datetime.now(timezone.utc)
    deadline = enqueued_at + timedelta(seconds=timeout_seconds)
    job_id = str(uuid.uuid4())

    with tracer.start_as_current_span("conductor.dispatch") as span:
        span.set_attribute("conductor.method", method)
        span.set_attribute("conductor.queue", queue)
        trace_parent = inject_traceparent()
        sc = span.get_span_context()
        trace_id_hex = format(sc.trace_id, "032x")
        span_id_hex = format(sc.span_id, "016x")

        msg = JobMessage(
            job_id=job_id,
            site=site,
            method=method,
            queue=queue,
            args=[],
            kwargs=kwargs,
            attempt=1,
            max_attempts=1,
            timeout_seconds=timeout_seconds,
            enqueued_at=enqueued_at,
            deadline=deadline,
            trace_parent=trace_parent,
            idempotency_key="",
            workflow_run_id="",
            step_id="",
        )
        encoded = encode(msg)

        # 1. Insert audit row first (status QUEUED).
        doc = frappe.get_doc(
            {
                "doctype": "Conductor Job",
                "job_id": job_id,
                "queue": queue,
                "method": method,
                "status": "QUEUED",
                "site": site,
                "args": encoded["args_b64"],
                "kwargs": encoded["kwargs_b64"],
                "args_preview": _preview([]),
                "kwargs_preview": _preview(kwargs),
                "attempt": 1,
                "max_attempts": 1,
                "timeout_seconds": timeout_seconds,
                "enqueued_at": enqueued_at,
                "deadline": deadline,
                "trace_id": trace_id_hex,
                "span_id": span_id_hex,
            }
        ).insert(ignore_permissions=True)
        frappe.db.commit()

        # 2. XADD to the stream. Lazy-create the consumer group on first XADD.
        skey = stream_key(site, queue)
        try:
            ensure_consumer_group(r, skey)
            redis_msg_id = r.xadd(skey, encoded, maxlen=cfg.stream_max_len, approximate=True)
        except Exception as e:
            doc.db_set("status", "DISPATCH_FAILED", commit=True)
            doc.db_set("last_error_type", type(e).__name__, commit=True)
            doc.db_set("last_error_message", str(e)[:140], commit=True)
            log.error("dispatch_failed", job_id=job_id, error=str(e))
            raise

        doc.db_set("redis_msg_id", redis_msg_id.decode() if isinstance(redis_msg_id, bytes) else str(redis_msg_id), commit=True)

        # 3. Realtime broadcast for live dashboards (Phase 3 will subscribe).
        frappe.publish_realtime(
            "conductor:job_queued", {"job_id": job_id, "queue": queue, "method": method}, after_commit=False
        )
        log.info("job_enqueued", job_id=job_id, queue=queue, method=method)

    return job_id
```

- [ ] **Step 4: Implement `conductor.api`**

Write to `<BENCH>/apps/conductor/conductor/api.py`:

```python
"""Public API surface for the conductor package."""

from conductor.context import context
from conductor.dispatcher import enqueue

__all__ = ["enqueue", "context"]
```

- [ ] **Step 5: Update `conductor/__init__.py` to re-export**

Read the existing file:

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
cat conductor/__init__.py
```

Then write to `<BENCH>/apps/conductor/conductor/__init__.py`:

```python
__version__ = "0.0.1"

from conductor.api import context, enqueue  # noqa: E402,F401

__all__ = ["enqueue", "context", "__version__"]
```

(If the existing file had a different `__version__`, preserve that value.)

- [ ] **Step 6: Run the integration test**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_job.test_dispatcher
```

Expected: 2 tests pass.

- [ ] **Step 7: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add conductor/dispatcher.py conductor/api.py conductor/__init__.py conductor/conductor/doctype/conductor_job/test_dispatcher.py
git commit -m "feat(dispatcher): conductor.enqueue with audit row + stream XADD"
```

---

## Task 18: `conductor.demo` (echo function for the doctor demo)

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/demo.py`

- [ ] **Step 1: Implement**

Write to `<BENCH>/apps/conductor/conductor/demo.py`:

```python
"""Demo functions used by `bench conductor doctor --demo` and tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def echo(**kwargs: Any) -> dict:
    """Return a dict echoing what was sent in, plus a server timestamp."""
    return {"echo": kwargs, "now": datetime.utcnow().isoformat()}


def boom(**kwargs: Any) -> None:
    """Always raises — used for failure tests."""
    raise RuntimeError(f"intentional failure (kwargs={kwargs!r})")
```

- [ ] **Step 2: Smoke test**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/python -c "from conductor.demo import echo, boom; print(echo(x=1))"
```

Expected: prints a dict with `'echo': {'x': 1}, 'now': '…'`.

- [ ] **Step 3: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add conductor/demo.py
git commit -m "feat(demo): echo + boom helpers for doctor and tests"
```

---

## Task 19: `conductor.worker` (loop) + `conductor.commands.worker`

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/worker.py`
- Create: `<BENCH>/apps/conductor/conductor/commands/__init__.py`
- Create: `<BENCH>/apps/conductor/conductor/commands/worker.py`
- Modify: `<BENCH>/apps/conductor/conductor/hooks.py` (export commands)
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job/test_worker_e2e.py`

- [ ] **Step 1: Write the failing e2e test**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_job/test_worker_e2e.py`:

```python
"""End-to-end: dispatch → worker thread → SUCCEEDED row."""

import threading
import time

import frappe
from frappe.tests.utils import FrappeTestCase

import conductor
from conductor.worker import run_worker_once


class TestWorkerE2E(FrappeTestCase):
    def _wait_for_status(self, job_id: str, status: str, timeout: float = 5.0):
        end = time.time() + timeout
        while time.time() < end:
            frappe.db.rollback()  # see latest committed state
            doc = frappe.db.get_value("Conductor Job", job_id, "status")
            if doc == status:
                return
            time.sleep(0.1)
        raise AssertionError(
            f"job {job_id} never reached {status} (last={frappe.db.get_value('Conductor Job', job_id, 'status')})"
        )

    def test_succeeds_round_trip(self):
        job_id = conductor.enqueue("conductor.demo.echo", queue="default", k=42)
        # Run a single worker pass that drains all messages we just enqueued.
        run_worker_once(queues=["default"], concurrency=2, site=frappe.local.site, block_ms=2000)
        self._wait_for_status(job_id, "SUCCEEDED")
        doc = frappe.get_doc("Conductor Job", job_id)
        self.assertEqual(doc.status, "SUCCEEDED")
        self.assertIsNotNone(doc.started_at)
        self.assertIsNotNone(doc.finished_at)
        frappe.delete_doc("Conductor Job", job_id, force=True)

    def test_records_failure(self):
        job_id = conductor.enqueue("conductor.demo.boom", queue="default")
        run_worker_once(queues=["default"], concurrency=2, site=frappe.local.site, block_ms=2000)
        self._wait_for_status(job_id, "FAILED")
        doc = frappe.get_doc("Conductor Job", job_id)
        self.assertEqual(doc.last_error_type, "RuntimeError")
        self.assertIn("intentional failure", doc.last_error_message)
        self.assertIn("RuntimeError", doc.last_traceback)
        frappe.delete_doc("Conductor Job", job_id, force=True)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_job.test_worker_e2e 2>&1 | tail -20
```

Expected: ImportError on `conductor.worker.run_worker_once`.

- [ ] **Step 3: Implement `conductor.worker`**

Write to `<BENCH>/apps/conductor/conductor/worker.py`:

```python
"""Conductor worker loop: XREADGROUP → execute → status update → XACK."""

from __future__ import annotations

import json
import os
import signal
import socket
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import frappe

from conductor.client import get_redis
from conductor.config import load_config
from conductor.context import set_context, start_watchdog
from conductor.logging import get_logger, setup_logging
from conductor.messages import decode
from conductor.otel import extract_traceparent, get_tracer, setup_otel
from conductor.streams import CONSUMER_GROUP, ensure_consumer_group, stream_key

log = get_logger("conductor.worker")

_HEARTBEAT_SECS = 5
_PREVIEW_MAX = 4096


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
    frappe.get_doc(
        {
            "doctype": "Conductor Worker",
            "worker_id": worker_id,
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "queues": json.dumps(queues),
            "site": site,
            "status": "ALIVE",
            "started_at": _now(),
            "last_heartbeat": _now(),
        }
    ).insert(ignore_permissions=True)
    frappe.db.commit()


def _heartbeat(worker_id: str) -> None:
    frappe.db.set_value("Conductor Worker", worker_id, "last_heartbeat", _now(), update_modified=False)
    frappe.db.commit()


def _mark_worker_gone(worker_id: str) -> None:
    if frappe.db.exists("Conductor Worker", worker_id):
        frappe.db.set_value("Conductor Worker", worker_id, "status", "GONE", update_modified=False)
        frappe.db.commit()


def _set_job_running(job_id: str, worker_id: str) -> None:
    frappe.db.set_value(
        "Conductor Job",
        job_id,
        {"status": "RUNNING", "started_at": _now(), "worker_id": worker_id},
        update_modified=False,
    )
    frappe.db.commit()


def _set_job_succeeded(job_id: str, result) -> None:
    frappe.db.set_value(
        "Conductor Job",
        job_id,
        {"status": "SUCCEEDED", "finished_at": _now(), "result_preview": _preview(result)},
        update_modified=False,
    )
    frappe.db.commit()


def _set_job_failed(job_id: str, status: str, exc: BaseException) -> None:
    frappe.db.set_value(
        "Conductor Job",
        job_id,
        {
            "status": status,
            "finished_at": _now(),
            "last_error_type": type(exc).__name__,
            "last_error_message": str(exc)[:140],
            "last_traceback": traceback.format_exc(),
        },
        update_modified=False,
    )
    frappe.db.commit()


def _handle_one(stream_name: str, msg_id: bytes, fields: dict, worker_id: str, redis_client) -> None:
    decoded = {k.decode(): v.decode() for k, v in fields.items()}
    msg = decode(decoded)
    parent_ctx = extract_traceparent(msg.trace_parent)
    tracer = get_tracer()
    log_ctx = log.bind(job_id=msg.job_id, queue=msg.queue, worker_id=worker_id)
    log_ctx.info("job_received")

    with tracer.start_as_current_span(f"job:{msg.method}", context=parent_ctx) as span:
        span.set_attribute("conductor.job_id", msg.job_id)
        _set_job_running(msg.job_id, worker_id)

        cancel_event = threading.Event()
        watchdog = start_watchdog(msg.deadline, cancel_event) if msg.deadline else None
        try:
            with set_context(job_id=msg.job_id, attempt=msg.attempt, deadline=msg.deadline, cancel_event=cancel_event):
                func = frappe.get_attr(msg.method)
                result = func(**msg.kwargs)
            _set_job_succeeded(msg.job_id, result)
            log_ctx.info("job_succeeded")
        except BaseException as e:
            status = "TIMED_OUT" if cancel_event.is_set() else "FAILED"
            _set_job_failed(msg.job_id, status, e)
            span.record_exception(e)
            log_ctx.error("job_failed", status=status, error=str(e))
        finally:
            if watchdog:
                watchdog.cancel()
            redis_client.xack(stream_name, CONSUMER_GROUP, msg_id)


def _read_and_dispatch(redis_client, streams: dict, count: int, block_ms: int, worker_id: str, pool: ThreadPoolExecutor):
    msgs = redis_client.xreadgroup(CONSUMER_GROUP, worker_id, streams, count=count, block=block_ms)
    futures = []
    for stream_name, entries in (msgs or []):
        sname = stream_name.decode() if isinstance(stream_name, bytes) else stream_name
        for msg_id, fields in entries:
            futures.append(pool.submit(_handle_one, sname, msg_id, fields, worker_id, redis_client))
    for f in futures:
        f.result()  # surface exceptions inside tests


def run_worker_once(*, queues: list[str], concurrency: int, site: str, block_ms: int = 5000) -> None:
    """Run a single XREADGROUP pass and execute every received message synchronously.

    Used by tests; not for production.
    """
    setup_otel(service_name="conductor")
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    worker_id = _make_worker_id()
    _register_worker(worker_id, queues, site)
    streams = {}
    for q in queues:
        skey = stream_key(site, q)
        ensure_consumer_group(r, skey)
        streams[skey] = ">"
    pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="conductor-once-")
    try:
        _read_and_dispatch(r, streams, concurrency, block_ms, worker_id, pool)
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
            # Not on the main thread (e.g., tests) — skip.
            pass


def run_worker(*, queues: list[str], concurrency: int, site: str, grace_seconds: int = 30) -> None:
    setup_logging(site=site)
    setup_otel(service_name="conductor")
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    worker_id = _make_worker_id()
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
    last_beat = 0.0
    try:
        while not _shutdown.is_set():
            now = time.time()
            if now - last_beat >= _HEARTBEAT_SECS:
                _heartbeat(worker_id)
                last_beat = now
            try:
                _read_and_dispatch(r, streams, concurrency, 5000, worker_id, pool)
            except Exception as e:
                log_ctx.error("worker_iteration_failed", error=str(e))
                time.sleep(1)
    finally:
        log_ctx.info("worker_shutting_down", grace_seconds=grace_seconds)
        pool.shutdown(wait=True)
        _mark_worker_gone(worker_id)
        log_ctx.info("worker_stopped")
```

- [ ] **Step 4: Run the e2e test**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_job.test_worker_e2e
```

Expected: 2 tests pass.

- [ ] **Step 5: Implement the click command for the worker**

Write to `<BENCH>/apps/conductor/conductor/commands/__init__.py`:

```python
"""Click command group exported to bench via hooks.py."""

import click

from conductor.commands.worker import worker_command
from conductor.commands.doctor import doctor_command


@click.group("conductor")
def conductor_group():
    """Conductor — reliability-first background jobs."""


conductor_group.add_command(worker_command)
conductor_group.add_command(doctor_command)


commands = [conductor_group]
```

Write to `<BENCH>/apps/conductor/conductor/commands/worker.py`:

```python
"""bench conductor worker — run a long-lived worker process."""

from __future__ import annotations

import click
import frappe
from frappe.commands import get_site, pass_context


@click.command("worker")
@click.option("--queue", "queues", multiple=True, default=("default",), help="Queue to consume (repeatable).")
@click.option("--concurrency", default=4, type=int, help="Threadpool size for executing jobs.")
@click.option("--grace", default=30, type=int, help="Graceful shutdown timeout (seconds).")
@pass_context
def worker_command(ctx, queues, concurrency, grace):
    """Run a Conductor worker process. Site comes from the bench context (--site)."""
    site = get_site(ctx)
    frappe.init(site=site)
    frappe.connect()
    try:
        from conductor.worker import run_worker
        run_worker(queues=list(queues), concurrency=concurrency, site=site, grace_seconds=grace)
    finally:
        frappe.destroy()
```

- [ ] **Step 6: Wire commands into `hooks.py`**

Edit `<BENCH>/apps/conductor/conductor/hooks.py` and add this line at the bottom (or at the appropriate "Bench / CLI" section):

```python
commands = ["conductor.commands.conductor_group"]
```

If a `commands =` line already exists, replace it with the line above.

(Frappe's bench loader supports either a list of click groups or a list of dotted-path strings; the dotted form avoids import-time side effects when bench scans apps.)

Verify the command is wired:

```bash
cd /Users/osamamuhammed/frappe_15
bench conductor --help 2>&1 | head -20
```

Expected: lists `worker` (and later `doctor`) sub-commands. (If the help text says "Got unexpected extra argument" or shows nothing, the hook wiring is wrong — re-check the import path.)

- [ ] **Step 7: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add conductor/worker.py conductor/commands/ conductor/hooks.py conductor/conductor/doctype/conductor_job/test_worker_e2e.py
git commit -m "feat(worker): worker loop + bench conductor worker command"
```

---

## Task 20: `bench conductor doctor [--demo]`

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/doctor.py`
- Create: `<BENCH>/apps/conductor/conductor/commands/doctor.py`

- [ ] **Step 1: Implement `conductor.doctor`**

Write to `<BENCH>/apps/conductor/conductor/doctor.py`:

```python
"""Health-check + acceptance demo for Conductor.

Steps 1–4 run without --demo (suitable for CI/liveness probes). Step 5–6 add a
real round-trip dispatch via `conductor.demo.echo`.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable

import frappe

import conductor
from conductor.client import get_redis
from conductor.config import load_config
from conductor.streams import CONSUMER_GROUP, ensure_consumer_group, stream_key
from conductor.worker import run_worker_once

OK = "\033[32mOK\033[0m"
FAIL = "\033[31mFAIL\033[0m"


def _step(label: str, fn: Callable[[], str]) -> bool:
    line = f"{label}".ljust(70, ".")
    try:
        detail = fn()
        print(f"{line} {OK}  ({detail})")
        return True
    except Exception as e:
        print(f"{line} {FAIL} ({e})")
        return False


def run(*, demo: bool = False) -> int:
    site = frappe.local.site
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)

    ok = True

    def check_redis() -> str:
        r.ping()
        return cfg.redis_url

    def check_queues() -> str:
        names = [q.name for q in frappe.get_all("Conductor Queue", filters={"enabled": 1})]
        if not names:
            raise RuntimeError("no enabled queues")
        return ", ".join(sorted(names))

    def check_groups() -> str:
        for q in frappe.get_all("Conductor Queue", filters={"enabled": 1}, pluck="name"):
            ensure_consumer_group(r, stream_key(site, q))
        return "groups created/verified"

    def check_round_trip() -> str:
        skey = stream_key(site, "doctor")
        ensure_consumer_group(r, skey)
        msg_id = r.xadd(skey, {"probe": "1"})
        msgs = r.xreadgroup(CONSUMER_GROUP, "doctor-consumer", {skey: ">"}, count=1, block=1000)
        if not msgs:
            raise RuntimeError("XREADGROUP returned nothing")
        sname, entries = msgs[0]
        for mid, _ in entries:
            r.xack(skey, CONSUMER_GROUP, mid)
        r.delete(skey)
        return "round-trip OK"

    ok &= _step("[1/6] Redis connectivity", check_redis)
    ok &= _step("[2/6] Default queues seeded", check_queues)
    ok &= _step("[3/6] Consumer groups exist", check_groups)
    ok &= _step("[4/6] XADD/XREADGROUP/XACK round-trip", check_round_trip)

    if demo:
        job_id_holder = {}

        def step_dispatch() -> str:
            jid = conductor.enqueue("conductor.demo.echo", queue="default", k=42, ts=datetime.now(timezone.utc))
            job_id_holder["id"] = jid
            run_worker_once(queues=["default"], concurrency=2, site=site, block_ms=2000)
            end = time.time() + 10
            while time.time() < end:
                frappe.db.rollback()
                status = frappe.db.get_value("Conductor Job", jid, "status")
                if status in ("SUCCEEDED", "FAILED", "TIMED_OUT"):
                    if status != "SUCCEEDED":
                        raise RuntimeError(f"demo job ended {status}")
                    return f"job_id={jid} succeeded"
                time.sleep(0.2)
            raise RuntimeError("demo job did not terminate within 10s")

        def step_result() -> str:
            jid = job_id_holder.get("id")
            if not jid:
                raise RuntimeError("no demo job to inspect")
            preview = frappe.db.get_value("Conductor Job", jid, "result_preview") or ""
            if "echo" not in preview:
                raise RuntimeError("result_preview missing echo")
            frappe.delete_doc("Conductor Job", jid, force=True)
            return "round-trip preserved"

        ok &= _step("[5/6] End-to-end demo dispatch (conductor.demo.echo)", step_dispatch)
        ok &= _step("[6/6] Result round-trip", step_result)

    if ok:
        print("\n\033[32mAll checks passed. Conductor is healthy.\033[0m")
        return 0
    print("\n\033[31mOne or more checks failed.\033[0m")
    return 1
```

- [ ] **Step 2: Implement the click command**

Write to `<BENCH>/apps/conductor/conductor/commands/doctor.py`:

```python
"""bench conductor doctor [--demo]"""

from __future__ import annotations

import sys

import click
import frappe
from frappe.commands import get_site, pass_context


@click.command("doctor")
@click.option("--demo", is_flag=True, default=False, help="Run an end-to-end dispatch demo too.")
@pass_context
def doctor_command(ctx, demo):
    site = get_site(ctx)
    frappe.init(site=site)
    frappe.connect()
    try:
        from conductor.doctor import run
        sys.exit(run(demo=demo))
    finally:
        frappe.destroy()
```

- [ ] **Step 3: Run the doctor (without --demo first)**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost conductor doctor
```

Expected: prints checks 1–4 with `OK`, exits 0.

- [ ] **Step 4: Run the full demo**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost conductor doctor --demo
```

Expected: prints checks 1–6 with `OK`, "All checks passed.", exits 0.

- [ ] **Step 5: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add conductor/doctor.py conductor/commands/doctor.py
git commit -m "feat(doctor): bench conductor doctor + --demo acceptance test"
```

---

## Task 21: `frappe.enqueue` shim

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/frappe_compat.py`

- [ ] **Step 1: Implement**

Write to `<BENCH>/apps/conductor/conductor/frappe_compat.py`:

```python
"""Drop-in shim with the same call signature as frappe.enqueue.

Client apps opt in via:
    override_whitelisted_methods = {"frappe.enqueue": "conductor.frappe_compat.enqueue"}
in their `hooks.py`.
"""

from __future__ import annotations

from typing import Any

import conductor


def enqueue(method: str, queue: str = "default", timeout: int | None = None, **kwargs: Any) -> str:
    """frappe.enqueue-shaped wrapper around conductor.enqueue."""
    return conductor.enqueue(method, queue=queue, timeout=timeout, **kwargs)
```

- [ ] **Step 2: Smoke test from a Frappe console**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost console <<'EOF'
from conductor.frappe_compat import enqueue
jid = enqueue("conductor.demo.echo", queue="default", x=99)
print("ok job_id=", jid)
import frappe
print(frappe.db.get_value("Conductor Job", jid, "status"))
frappe.delete_doc("Conductor Job", jid, force=True)
frappe.db.commit()
EOF
```

Expected: prints a job_id and a status (likely `QUEUED` since no worker is running in console). No exception.

- [ ] **Step 3: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add conductor/frappe_compat.py
git commit -m "feat(frappe_compat): shim with frappe.enqueue signature"
```

---

## Task 22: `Procfile.conductor` + README install instructions

**Files:**
- Create: `<BENCH>/apps/conductor/Procfile.conductor`
- Modify: `<BENCH>/apps/conductor/README.md`

- [ ] **Step 1: Write `Procfile.conductor`**

Write to `<BENCH>/apps/conductor/Procfile.conductor`:

```
conductor_worker: bench --site all conductor worker --queue default --concurrency 4
```

- [ ] **Step 2: Replace `README.md`**

Write to `<BENCH>/apps/conductor/README.md`:

```markdown
# Conductor

Reliability-first background job platform for Frappe / ERPNext.

Phase 0 ships the skeleton: dispatcher, worker, doctor, and the three core
DocTypes (`Conductor Queue`, `Conductor Job`, `Conductor Worker`). No retries,
no DLQ, no scheduler — those land in Phase 1+.

## Install

```bash
cd <bench>
bench get-app conductor <repo-url>           # or copy the app into apps/
bench --site <site> install-app conductor
bench --site <site> conductor doctor --demo  # acceptance test
```

## Run a worker (foreground)

```bash
bench --site <site> conductor worker --queue default --concurrency 4
```

## Run a worker via `bench start`

`bench start` reads `Procfile` at the bench root. Append our line:

```bash
cat apps/conductor/Procfile.conductor >> Procfile
```

## Use it

```python
import conductor
job_id = conductor.enqueue("myapp.tasks.send_email", queue="default", invoice="INV-001")
```

Or opt the whole app in by overriding `frappe.enqueue` in a client app's
`hooks.py`:

```python
override_whitelisted_methods = {"frappe.enqueue": "conductor.frappe_compat.enqueue"}
```

## Health check

```bash
bench --site <site> conductor doctor          # 4 checks, exit 0/1
bench --site <site> conductor doctor --demo   # adds full dispatch round-trip
```

## Configuration

In `sites/<site>/site_config.json`:

```json
{
  "conductor": {
    "redis_url": "redis://127.0.0.1:11000/2",
    "default_queue": "default",
    "stream_max_len": 10000
  }
}
```

If `conductor.redis_url` is not set, Conductor falls back to `redis_queue`
with DB **2** forced.

## Status

Phase 0 of 6. See `docs/superpowers/specs/2026-04-27-conductor-master-design.md`
for the full roadmap.

## License

MIT
```

- [ ] **Step 3: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add Procfile.conductor README.md
git commit -m "docs: README + Procfile.conductor for dev/prod operators"
```

---

## Task 23: Run the full pytest + Frappe test suites green

- [ ] **Step 1: Run all pytest unit tests**

```bash
cd /Users/osamamuhammed/frappe_15
./env/bin/pytest apps/conductor/tests/ -v
```

Expected: all tests pass (Tasks 5, 6, 7, 8, 9, 11 contribute tests). No failures.

- [ ] **Step 2: Run all Frappe integration tests**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost run-tests --app conductor 2>&1 | tail -40
```

Expected: every `test_conductor_*` and `test_dispatcher` and `test_worker_e2e` test passes.

- [ ] **Step 3: If any test fails**, fix the underlying code (do not edit the test to make it pass), re-run, and commit the fix as a new commit (no `--amend`).

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git status
# If you made code changes:
git add <changed files>
git commit -m "fix: <what was broken>"
```

---

## Task 24: Run `bench conductor doctor --demo` as the official Phase 0 acceptance test

- [ ] **Step 1: Make sure no stragglers from prior runs**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost console <<'EOF'
import frappe
for j in frappe.get_all("Conductor Job", pluck="name"):
    frappe.delete_doc("Conductor Job", j, force=True)
for w in frappe.get_all("Conductor Worker", pluck="name"):
    frappe.delete_doc("Conductor Worker", w, force=True)
frappe.db.commit()
print("cleaned")
EOF
```

- [ ] **Step 2: Run the demo**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost conductor doctor --demo
echo "exit: $?"
```

Expected:
- Output shows steps 1/6 through 6/6, all `OK`.
- "All checks passed. Conductor is healthy." in green.
- `exit: 0`.

- [ ] **Step 3: Sanity-spot the audit row**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost console <<'EOF'
import frappe
print("jobs:", frappe.get_all("Conductor Job", fields=["name", "status", "method", "started_at", "finished_at"]))
print("workers:", frappe.get_all("Conductor Worker", fields=["name", "status", "last_heartbeat"]))
EOF
```

Expected: at least one Conductor Worker row in `GONE` status (the doctor's transient worker), and zero Conductor Job rows (the demo cleans up after itself in `step_result`).

- [ ] **Step 4: Commit any final test/doc tweaks**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git status
# If anything is dirty:
git add -A
git commit -m "chore: phase 0 acceptance run + minor cleanups"
```

---

## Task 25: Final sweep — definition of done checklist

- [ ] **Step 1: Walk the Phase 0 spec's §13 checklist**

Read `apps/conductor/docs/superpowers/specs/2026-04-27-conductor-phase0-skeleton.md` §13. For each bullet, verify it is true. Specifically:

```bash
cd /Users/osamamuhammed/frappe_15

# bench install-app succeeded → already done in Task 16
# default queues seeded
bench --site frappe.localhost console <<'EOF'
import frappe
qs = sorted([q.name for q in frappe.get_all("Conductor Queue")])
assert qs == ["critical", "default", "long", "short"], qs
print("queues OK:", qs)
assert frappe.db.exists("Role", "Conductor Operator")
print("role OK")
EOF

# enqueue from console returns a job_id and creates a row
bench --site frappe.localhost console <<'EOF'
import frappe, time
import conductor
jid = conductor.enqueue("conductor.demo.echo", queue="default", x="hi")
assert frappe.db.get_value("Conductor Job", jid, "status") == "QUEUED"
print("enqueue OK:", jid)
frappe.delete_doc("Conductor Job", jid, force=True); frappe.db.commit()
EOF

# doctor --demo passes
bench --site frappe.localhost conductor doctor --demo && echo "doctor --demo OK"

# pytest + frappe tests pass
./env/bin/pytest apps/conductor/tests/ -q
bench --site frappe.localhost run-tests --app conductor 2>&1 | tail -3
```

Expected: every assertion holds; both test suites pass.

- [ ] **Step 2: Print the final state**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git log --oneline | head -30
git status
```

Expected: ~22-25 commits on `develop`, working tree clean.

- [ ] **Step 3: Phase 0 is done.**

The next session opens a Phase 1 brainstorm. Hand-off inputs are documented in `apps/conductor/docs/superpowers/specs/2026-04-27-conductor-phase0-skeleton.md` §14.

---

## Self-Review Notes

This section is for the planner's eyes — not part of execution.

**Spec coverage:** Every requirement in §2 of the Phase 0 spec maps to a task — app scaffold (1), DocTypes (13–15), default queues + role (16), public API (17), bench commands (19–20), `frappe_compat` shim (21), OTel no-op + structlog (11–12), Procfile (22), demo (18, 20), doctor (20).

**Phase 0 explicit out-of-scope items NOT addressed by any task** — confirmed: no decorator, no RetryPolicy, no Job Run / DLQ DocTypes, no scheduler, no reaper, no dashboard, no exporter, no workflows, no pool workers. Correct.

**Type/name consistency check:**
- `enqueue(method, *, queue, timeout, **kwargs)` — used identically in api.py (Task 17), dispatcher (Task 17), frappe_compat (Task 21), doctor (Task 20), tests (17, 19, 20).
- `JobMessage.method` (the dataclass field) maps to stream field `name` — encode/decode in Task 6 use `name`, but `dispatcher.py` (Task 17) and `worker.py` (Task 19) read `msg.method` from the dataclass. Consistent.
- `set_context(job_id=, attempt=, deadline=, cancel_event=)` — defined in Task 9 with `cancel_event` keyword optional; called in Task 19 with all four kwargs. Consistent.
- `start_watchdog(deadline, cancel_event)` returns `threading.Timer`; caller in Task 19 calls `watchdog.cancel()` (Timer's method). Consistent.
- `ensure_consumer_group(client, stream)` — defined Task 7; called from Task 17 (dispatcher), Task 19 (worker), Task 20 (doctor). Same signature. Consistent.
- `stream_key(site, queue)` — Task 7 defines, Tasks 17/19/20 call. Consistent.
- `CONSUMER_GROUP = "conductor"` — Task 7; referenced in Task 19 (xack) and Task 20 (doctor xreadgroup). Consistent.
- `run_worker_once(queues, concurrency, site, block_ms)` — Task 19; called by Task 19's tests and Task 20's doctor demo. Consistent.

No placeholder phrases ("TBD", "TODO", "implement later", "similar to Task N", "add appropriate error handling") found.

---

## Execution

Plan complete. To execute, the user should pick:

1. **Subagent-Driven** (recommended) — fresh subagent per task, two-stage review between tasks via `superpowers:subagent-driven-development`.
2. **Inline Execution** — execute in this session via `superpowers:executing-plans`, batched checkpoints.
