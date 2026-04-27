# Conductor Phase 2 (Scheduling) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lift `DelayDrainer` and `OrphanSweeper` out of the worker, add a per-site singleton `bench conductor scheduler` daemon that owns four background loops (delay, cron, reaper, sweeper), introduce the `Conductor Schedule` DocType with cron-driven dispatch, ship `bench conductor schedule {list, enable, disable, run-now}`, and harden the chaos suite (XGROUP DESTROY on teardown + tighter subprocess teardown) so the 5-run flake gate is reliably green. Acceptance: a `* * * * *` schedule produces ≥60 jobs/hr with avg drift <2s, killing the scheduler hands the lock off in ~20s, all Phase 1 chaos tests still pass, and `pytest tests_chaos --count=5` is green twice in a row.

**Architecture:** New modules `conductor/cron.py` (croniter wrapper), `conductor/scheduler_lock.py` (SET NX EX + Lua check-and-PEXPIRE renewal), `conductor/scheduler.py` (lock holder + four daemon-thread loops + lost-lock fence). New DocType `Conductor Schedule` (master §6.6). New click commands `commands/scheduler.py` and `commands/schedule.py`. `worker.py` shrinks: drop the two threads, modify `_heartbeat` to reset STALE→ALIVE.

**Tech Stack:**
- Python 3.10+ (bench env)
- Frappe 15.106.0
- redis-py ≥5 (Streams + ZSET + SET NX EX + EVAL)
- **croniter ≥2,<7** (NEW — added to install_requires)
- msgpack ≥1, structlog, opentelemetry-{api,sdk}
- pytest, fakeredis, lupa (Lua/EVAL in fakeredis), pytest-mock — already in `[dev]`
- pytest-repeat (NEW dev dep — for the 5-run flake gate)

**Reference docs:**
- Master design: `apps/conductor/docs/superpowers/specs/2026-04-27-conductor-master-design.md`
- Phase 2 spec: `apps/conductor/docs/superpowers/specs/2026-04-27-conductor-phase2-scheduling.md`
- Phase 2 hand-off: `apps/conductor/docs/superpowers/specs/2026-04-27-conductor-phase2-handoff.md`
- Phase 1 plan (precedent for layout): `apps/conductor/docs/superpowers/plans/2026-04-27-conductor-phase1-reliability-core.md`

**Bench-rooted paths:**
- Bench root: `/Users/osamamuhammed/frappe_15` (referred to as `<BENCH>`)
- App root: `<BENCH>/apps/conductor` (its own git repo on `develop`)
- Bench Python: `<BENCH>/env/bin/python`
- Bench pytest: `<BENCH>/env/bin/pytest`
- Default site: `frappe.localhost`
- Redis (queue): `127.0.0.1:11000` DB 2 (Conductor)

**Conventions:**
- Run unit `pytest` from bench root: `cd <BENCH> && ./env/bin/pytest apps/conductor/tests/...`
- Run Frappe integration tests from bench root: `cd <BENCH> && bench --site frappe.localhost run-tests --app conductor --module <dotted.module>`
- All `git` commands inside `<BENCH>/apps/conductor` (use absolute paths to avoid the persistent-CWD bug we hit in Phase 0).
- Small, frequent commits — one task = one or two commits. Never `--amend`.
- Both Redis daemons must be running before any task that hits Redis. If `redis-cli -p 11000 ping` fails: `redis-server <BENCH>/config/redis_queue.conf --daemonize yes` and same for `redis_cache`.

**Phase 1 invariants this plan must preserve:**
- 71 pytest unit tests stay green (Phase 0 + Phase 1).
- 27 Frappe integration tests stay green.
- 3 chaos tests stay green individually.
- `bench --site frappe.localhost conductor doctor --demo` exits 0.
- All public API surfaces (`conductor.enqueue`, `conductor.cancel`, `conductor.RetryPolicy`, `conductor.context`, `conductor.job`, `conductor.frappe_compat.enqueue`) unchanged.
- Stream `schema_version=1` unchanged.

**Frozen contracts (do NOT relitigate):**
- All 20 master cross-cutting decisions (master §3) and the 7 brainstorm decisions (Phase 2 spec §3).
- `Conductor Schedule` schema is master §6.6, modulo `last_status` Select options (`DISPATCHED` / `DISPATCH_FAILED`) which the spec §8.1 fills in.
- Cron tick is 1s (spec §6.2 deviates from master §4's 30s hint, with rationale).
- At-least-once cron on scheduler crash (spec §15 risk #8).

---

## Task 1: Bootstrap — add croniter + pytest-repeat, baseline tests still green

**Files:**
- Modify: `<BENCH>/apps/conductor/pyproject.toml`

- [ ] **Step 1: Add croniter to install_requires and pytest-repeat to dev deps**

Open `<BENCH>/apps/conductor/pyproject.toml` and edit the `dependencies` and `optional-dependencies.dev` arrays:

```toml
dependencies = [
    "redis>=5,<6",
    "msgpack>=1.0,<2",
    "opentelemetry-api>=1.27,<2",
    "opentelemetry-sdk>=1.27,<2",
    "structlog>=24.1,<26",
    "croniter>=2,<7",
]

[project.optional-dependencies]
dev = [
    "pytest>=8,<9",
    "pytest-mock>=3.14,<4",
    "fakeredis>=2.23,<3",
    "lupa>=2,<3",
    "pytest-repeat>=0.9,<1",
]
```

- [ ] **Step 2: Reinstall the app's dev extras into the bench env**

Run from `<BENCH>`:

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pip install -e "apps/conductor[dev]"
```

Expected: `Successfully installed croniter-… pytest-repeat-…`. (Memory: `bench update` will revert the conductor `redis~=4.5.5` pin; if so, this same command repins it.)

- [ ] **Step 3: Verify all Phase 1 tests still pass**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests/ -q
```

Expected: 71 passed (same count as the end of Phase 1).

```bash
cd /Users/osamamuhammed/frappe_15 && bench --site frappe.localhost run-tests --app conductor 2>&1 | tail -5
```

Expected: `Ran 27 tests in …s` `OK`.

- [ ] **Step 4: Verify croniter import works in the bench env**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/python -c "from croniter import croniter; print(croniter('* * * * *', None).get_next())"
```

Expected: a Unix timestamp printed (some float).

- [ ] **Step 5: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor && git add pyproject.toml && git commit -m "build(deps): add croniter>=2,<7 + pytest-repeat>=0.9,<1 for Phase 2"
```

---

## Task 2: TDD `conductor.cron` — `compute_next_run_at` (UTC, tz, DST, malformed)

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/cron.py`
- Create: `<BENCH>/apps/conductor/tests/test_cron.py`

- [ ] **Step 1: Write failing tests**

Write to `<BENCH>/apps/conductor/tests/test_cron.py`:

```python
"""Unit tests for conductor.cron — compute_next_run_at."""

from datetime import datetime, timezone

import pytest

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
    base = datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc)
    nxt = compute_next_run_at("0 9 * * *", "America/New_York", base=base)
    assert nxt.tzinfo is not None
    assert nxt.astimezone(timezone.utc) == datetime(2026, 4, 28, 13, 0, 0, tzinfo=timezone.utc)


def test_daily_at_9am_in_new_york_during_winter():
    # In January, NY is EST (UTC-5) → 9 AM ET = 14:00 UTC.
    base = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
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
    with pytest.raises(Exception):
        compute_next_run_at("not a cron", "UTC")


def test_default_base_is_now_utc():
    nxt = compute_next_run_at("* * * * *", "UTC")
    assert nxt.tzinfo is not None
    # Should be within next 60s of "now"
    delta = (nxt - datetime.now(timezone.utc)).total_seconds()
    assert -1 <= delta <= 61
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests/test_cron.py -v
```

Expected: ImportError / ModuleNotFoundError — `conductor.cron` doesn't exist yet.

- [ ] **Step 3: Write minimal implementation**

Write to `<BENCH>/apps/conductor/conductor/cron.py`:

```python
"""Cron expression evaluation in a per-Schedule timezone, returning UTC.

Skip-and-resume catch-up is implicit: get_next(base) returns a time strictly
after base = now, so missed runs are silently dropped.
"""

from __future__ import annotations

import zoneinfo
from datetime import datetime, timezone

from croniter import croniter


def compute_next_run_at(
    cron_expression: str,
    tz_name: str = "UTC",
    base: datetime | None = None,
) -> datetime:
    """Return the next fire time strictly after `base` (default: now), as UTC-aware.

    `base` may be naive (treated as UTC) or tz-aware. `tz_name` is the schedule's
    declared timezone; cron is evaluated in that local time. Unknown timezones
    fall back to UTC. Raises whatever `croniter` raises on malformed expressions
    (typically `croniter.CroniterBadCronError`)."""
    if base is None:
        base = datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    try:
        tz = zoneinfo.ZoneInfo(tz_name or "UTC")
    except zoneinfo.ZoneInfoNotFoundError:
        tz = zoneinfo.ZoneInfo("UTC")
    base_local = base.astimezone(tz)
    itr = croniter(cron_expression, base_local)
    next_local = itr.get_next(datetime)
    return next_local.astimezone(timezone.utc)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests/test_cron.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor && git add conductor/cron.py tests/test_cron.py && git commit -m "feat(cron): compute_next_run_at — croniter wrapper with per-schedule tz, UTC return"
```

---

## Task 3: TDD `conductor.scheduler_lock` — acquire / renew (Lua) / release (Lua)

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/scheduler_lock.py`
- Create: `<BENCH>/apps/conductor/tests/test_scheduler_lock.py`

- [ ] **Step 1: Write failing tests**

Write to `<BENCH>/apps/conductor/tests/test_scheduler_lock.py`:

```python
"""Unit tests for conductor.scheduler_lock — singleton lock with Lua-renew/release."""

import time

import fakeredis
import pytest

from conductor.scheduler_lock import (
    acquire,
    lock_redis_key,
    release,
    renew,
)


@pytest.fixture
def r():
    """fakeredis with Lua via lupa."""
    return fakeredis.FakeStrictRedis()


def test_lock_redis_key_format():
    assert lock_redis_key("frappe.localhost") == "conductor:frappe.localhost:scheduler:lock"


def test_acquire_succeeds_on_empty(r):
    assert acquire(r, "site1", "instance-A", ttl=15) is True
    assert r.get("conductor:site1:scheduler:lock") == b"instance-A"


def test_second_acquire_fails(r):
    assert acquire(r, "site1", "instance-A", ttl=15) is True
    assert acquire(r, "site1", "instance-B", ttl=15) is False
    assert r.get("conductor:site1:scheduler:lock") == b"instance-A"


def test_renew_returns_true_while_we_own(r):
    assert acquire(r, "site1", "instance-A", ttl=15) is True
    assert renew(r, "site1", "instance-A", ttl=15) is True


def test_renew_returns_false_after_steal(r):
    assert acquire(r, "site1", "instance-A", ttl=15) is True
    # Simulate someone else owning the key.
    r.set("conductor:site1:scheduler:lock", "instance-B")
    assert renew(r, "site1", "instance-A", ttl=15) is False


def test_renew_returns_false_when_key_missing(r):
    # No prior acquire.
    assert renew(r, "site1", "instance-A", ttl=15) is False


def test_release_deletes_when_we_own(r):
    assert acquire(r, "site1", "instance-A", ttl=15) is True
    assert release(r, "site1", "instance-A") is True
    assert r.get("conductor:site1:scheduler:lock") is None


def test_release_does_not_delete_when_we_dont_own(r):
    assert acquire(r, "site1", "instance-A", ttl=15) is True
    r.set("conductor:site1:scheduler:lock", "instance-B")
    assert release(r, "site1", "instance-A") is False
    assert r.get("conductor:site1:scheduler:lock") == b"instance-B"


def test_double_release_returns_false(r):
    assert acquire(r, "site1", "instance-A", ttl=15) is True
    assert release(r, "site1", "instance-A") is True
    assert release(r, "site1", "instance-A") is False


def test_ttl_expiry_allows_takeover(r):
    assert acquire(r, "site1", "instance-A", ttl=1) is True
    time.sleep(1.2)
    assert acquire(r, "site1", "instance-B", ttl=15) is True
    assert r.get("conductor:site1:scheduler:lock") == b"instance-B"


def test_renew_extends_ttl_for_owner(r):
    assert acquire(r, "site1", "instance-A", ttl=2) is True
    time.sleep(1.0)
    assert renew(r, "site1", "instance-A", ttl=10) is True
    time.sleep(1.5)
    # Original 2s would have expired; renewal extended to 10s, so still alive.
    assert r.get("conductor:site1:scheduler:lock") == b"instance-A"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests/test_scheduler_lock.py -v
```

Expected: ImportError — `conductor.scheduler_lock` doesn't exist yet.

- [ ] **Step 3: Write minimal implementation**

Write to `<BENCH>/apps/conductor/conductor/scheduler_lock.py`:

```python
"""Singleton scheduler lock: SET NX EX + Lua check-and-PEXPIRE / check-and-DEL.

All three operations are single-key (master §3 #15 cluster-compat).
"""

from __future__ import annotations

import redis as redis_mod

# GET == ARGV[1] ? PEXPIRE KEYS[1] ARGV[2] : 0
_RENEW_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
else
  return 0
end
"""

# GET == ARGV[1] ? DEL KEYS[1] : 0
_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
else
  return 0
end
"""


def lock_redis_key(site: str) -> str:
    return f"conductor:{site}:scheduler:lock"


def acquire(client: redis_mod.Redis, site: str, instance_id: str, *, ttl: int = 15) -> bool:
    """SET NX EX ttl. Returns True on win, False if held by a peer."""
    return bool(client.set(lock_redis_key(site), instance_id, nx=True, ex=ttl))


def renew(client: redis_mod.Redis, site: str, instance_id: str, *, ttl: int = 15) -> bool:
    """Lua: GET == self ? PEXPIRE ttl*1000 : 0. Returns True iff still ours."""
    pttl_ms = ttl * 1000
    result = client.eval(_RENEW_LUA, 1, lock_redis_key(site), instance_id, pttl_ms)
    return bool(result)


def release(client: redis_mod.Redis, site: str, instance_id: str) -> bool:
    """Lua: GET == self ? DEL : 0. Returns True iff we deleted our own lock."""
    result = client.eval(_RELEASE_LUA, 1, lock_redis_key(site), instance_id)
    return bool(result)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests/test_scheduler_lock.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor && git add conductor/scheduler_lock.py tests/test_scheduler_lock.py && git commit -m "feat(scheduler-lock): SET NX EX + Lua check-and-PEXPIRE renewal + check-and-DEL release"
```

---

## Task 4: `Conductor Schedule` DocType — JSON, controller, validate, on_change

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_schedule/__init__.py`
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_schedule/conductor_schedule.json`
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_schedule/conductor_schedule.py`
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_schedule/test_conductor_schedule.py`

- [ ] **Step 1: Create empty module init**

```bash
mkdir -p /Users/osamamuhammed/frappe_15/apps/conductor/conductor/conductor/doctype/conductor_schedule
```

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_schedule/__init__.py`:

```python
```

(empty file — just like `conductor_queue/__init__.py`)

- [ ] **Step 2: Write the DocType JSON**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_schedule/conductor_schedule.json`:

```json
{
 "actions": [],
 "allow_rename": 0,
 "autoname": "field:schedule_name",
 "creation": "2026-04-27 00:00:00",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "schedule_name",
  "enabled",
  "cron_expression",
  "timezone",
  "method",
  "queue",
  "max_attempts",
  "args",
  "kwargs",
  "last_run_at",
  "last_status",
  "last_job",
  "next_run_at",
  "description"
 ],
 "fields": [
  {"fieldname": "schedule_name", "fieldtype": "Data", "label": "Schedule Name", "reqd": 1, "unique": 1, "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "enabled", "fieldtype": "Check", "label": "Enabled", "default": "1", "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "cron_expression", "fieldtype": "Data", "label": "Cron Expression", "reqd": 1, "in_list_view": 1, "description": "Standard 5-field cron, e.g. '0 9 * * *'. Macros @hourly/@daily/@weekly supported."},
  {"fieldname": "timezone", "fieldtype": "Data", "label": "Timezone", "default": "UTC", "description": "IANA tz name, e.g. 'America/New_York'. Unknown values fall back to UTC."},
  {"fieldname": "method", "fieldtype": "Data", "label": "Method", "reqd": 1, "description": "Dotted path, e.g. 'myapp.tasks.nightly_rollup'."},
  {"fieldname": "queue", "fieldtype": "Link", "options": "Conductor Queue", "label": "Queue", "reqd": 1, "in_list_view": 1},
  {"fieldname": "max_attempts", "fieldtype": "Int", "label": "Max Attempts", "description": "Optional override; falls back to queue defaults."},
  {"fieldname": "args", "fieldtype": "Long Text", "label": "Args (msgpack-base64)", "description": "Positional args. Always empty in v1; included for forward compatibility."},
  {"fieldname": "kwargs", "fieldtype": "Long Text", "label": "Kwargs (msgpack-base64)", "description": "Keyword args, msgpack-then-base64."},
  {"fieldname": "last_run_at", "fieldtype": "Datetime", "label": "Last Run At", "read_only": 1},
  {"fieldname": "last_status", "fieldtype": "Select", "options": "\nDISPATCHED\nDISPATCH_FAILED", "label": "Last Status", "read_only": 1, "in_list_view": 1},
  {"fieldname": "last_job", "fieldtype": "Link", "options": "Conductor Job", "label": "Last Job", "read_only": 1},
  {"fieldname": "next_run_at", "fieldtype": "Datetime", "label": "Next Run At", "read_only": 1, "in_list_view": 1},
  {"fieldname": "description", "fieldtype": "Small Text", "label": "Description"}
 ],
 "links": [],
 "modified": "2026-04-27 00:00:00",
 "modified_by": "Administrator",
 "module": "Conductor",
 "name": "Conductor Schedule",
 "owner": "Administrator",
 "permissions": [
  {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "report": 1, "export": 1},
  {"role": "Conductor Operator", "read": 1, "report": 1, "export": 1}
 ],
 "sort_field": "schedule_name",
 "sort_order": "ASC",
 "track_changes": 1
}
```

Note `next_run_at` is indexed via `in_list_view`. Frappe will create the index automatically when the DocType is migrated.

- [ ] **Step 3: Write the controller**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_schedule/conductor_schedule.py`:

```python
"""Conductor Schedule controller — keeps next_run_at fresh on validate/on_change."""

from __future__ import annotations

import frappe
from frappe.model.document import Document

from conductor.cron import compute_next_run_at


class ConductorSchedule(Document):
    def validate(self):
        if not self.enabled:
            self.next_run_at = None
            return
        if not self.cron_expression:
            frappe.throw("cron_expression required when enabled")
        # Validate by attempting to compute next_run_at — raises on bad expr.
        try:
            next_at = compute_next_run_at(self.cron_expression, self.timezone or "UTC")
        except Exception as e:
            frappe.throw(f"Invalid cron_expression {self.cron_expression!r}: {e}")
        self.next_run_at = next_at.replace(tzinfo=None)

    def on_update(self):
        # If user toggled enabled or edited cron/tz post-save, validate already
        # re-set next_run_at. on_update is called *after* validate, so nothing
        # else to do — the DB is consistent.
        pass
```

`on_change` from the spec is renamed to `on_update` (Frappe's actual hook name). The work happens in `validate`, which Frappe runs before every save.

- [ ] **Step 4: Write Frappe integration test**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_schedule/test_conductor_schedule.py`:

```python
"""Frappe integration tests for Conductor Schedule."""

from __future__ import annotations

import unittest

import frappe


class TestConductorSchedule(unittest.TestCase):
    def setUp(self):
        # Ensure the default queue exists.
        if not frappe.db.exists("Conductor Queue", "default"):
            frappe.get_doc({
                "doctype": "Conductor Queue",
                "queue_name": "default",
                "enabled": 1,
            }).insert(ignore_permissions=True)
            frappe.db.commit()

    def tearDown(self):
        for name in frappe.get_all("Conductor Schedule", pluck="name"):
            frappe.delete_doc("Conductor Schedule", name, force=True)
        frappe.db.commit()

    def test_insert_populates_next_run_at(self):
        doc = frappe.get_doc({
            "doctype": "Conductor Schedule",
            "schedule_name": "test-every-minute",
            "enabled": 1,
            "cron_expression": "* * * * *",
            "timezone": "UTC",
            "method": "frappe.utils.now",
            "queue": "default",
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        self.assertIsNotNone(doc.next_run_at)

    def test_malformed_cron_raises(self):
        with self.assertRaises(Exception):
            frappe.get_doc({
                "doctype": "Conductor Schedule",
                "schedule_name": "test-bad",
                "enabled": 1,
                "cron_expression": "this is not cron",
                "timezone": "UTC",
                "method": "frappe.utils.now",
                "queue": "default",
            }).insert(ignore_permissions=True)

    def test_disabled_clears_next_run_at(self):
        doc = frappe.get_doc({
            "doctype": "Conductor Schedule",
            "schedule_name": "test-disable",
            "enabled": 1,
            "cron_expression": "@hourly",
            "timezone": "UTC",
            "method": "frappe.utils.now",
            "queue": "default",
        }).insert(ignore_permissions=True)
        self.assertIsNotNone(doc.next_run_at)
        doc.enabled = 0
        doc.save(ignore_permissions=True)
        self.assertIsNone(doc.next_run_at)

    def test_edit_cron_updates_next_run_at(self):
        doc = frappe.get_doc({
            "doctype": "Conductor Schedule",
            "schedule_name": "test-edit",
            "enabled": 1,
            "cron_expression": "0 0 * * *",  # daily midnight
            "timezone": "UTC",
            "method": "frappe.utils.now",
            "queue": "default",
        }).insert(ignore_permissions=True)
        first_next = doc.next_run_at
        doc.cron_expression = "0 12 * * *"  # daily noon
        doc.save(ignore_permissions=True)
        self.assertNotEqual(doc.next_run_at, first_next)
```

- [ ] **Step 5: Migrate the DocType into the site**

```bash
cd /Users/osamamuhammed/frappe_15 && bench --site frappe.localhost migrate
```

Expected: `Migrating frappe.localhost` followed by `Updating Dashboard for conductor` or similar; no errors.

- [ ] **Step 6: Run the integration test**

```bash
cd /Users/osamamuhammed/frappe_15 && bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_schedule.test_conductor_schedule 2>&1 | tail -10
```

Expected: `Ran 4 tests in …s` `OK`.

- [ ] **Step 7: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor && git add conductor/conductor/doctype/conductor_schedule/ && git commit -m "feat(doctype): Conductor Schedule + controller + 4 integration tests"
```

---

## Task 5: Scheduler skeleton — `run_scheduler`, lock-hold lifecycle, lost-lock fence

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/scheduler.py`
- Create: `<BENCH>/apps/conductor/tests/test_scheduler_lifecycle.py`

- [ ] **Step 1: Write failing tests**

Write to `<BENCH>/apps/conductor/tests/test_scheduler_lifecycle.py`:

```python
"""Unit tests for the scheduler lifecycle: lock acquire, renewer, lost-lock fence.

These tests exercise the scheduler's plumbing in isolation — no Frappe init
required (the loops are skipped via the `loops_disabled=True` test hook)."""

import threading
import time

import fakeredis
import pytest

from conductor.scheduler import run_scheduler_lifecycle
from conductor.scheduler_lock import lock_redis_key


@pytest.fixture
def r():
    return fakeredis.FakeStrictRedis()


def test_acquires_lock_and_holds_it(r):
    stop = threading.Event()
    started = threading.Event()
    t = threading.Thread(
        target=run_scheduler_lifecycle,
        kwargs=dict(
            redis_client=r, site="site1", instance_id="A",
            lock_ttl_seconds=2, renew_interval_seconds=1, poll_interval_seconds=1,
            stop_event=stop, started_event=started, loops_disabled=True,
        ),
        daemon=True,
    )
    t.start()
    assert started.wait(timeout=5)
    # We are now the lock holder.
    assert r.get(lock_redis_key("site1")) == b"A"
    # Hold it across a renewal.
    time.sleep(1.5)
    assert r.get(lock_redis_key("site1")) == b"A"
    stop.set()
    t.join(timeout=5)
    # Released cleanly on shutdown.
    assert r.get(lock_redis_key("site1")) is None


def test_loser_polls_until_holder_releases(r):
    # Pre-populate lock as if held by another instance.
    r.set(lock_redis_key("site1"), "X", ex=2)
    stop = threading.Event()
    started = threading.Event()
    t = threading.Thread(
        target=run_scheduler_lifecycle,
        kwargs=dict(
            redis_client=r, site="site1", instance_id="B",
            lock_ttl_seconds=2, renew_interval_seconds=1, poll_interval_seconds=1,
            stop_event=stop, started_event=started, loops_disabled=True,
        ),
        daemon=True,
    )
    t.start()
    # Should not have acquired yet.
    time.sleep(0.5)
    assert r.get(lock_redis_key("site1")) == b"X"
    # Wait for X's TTL to expire and B to take over.
    assert started.wait(timeout=5)
    assert r.get(lock_redis_key("site1")) == b"B"
    stop.set()
    t.join(timeout=5)


def test_lost_lock_causes_exit(r):
    stop = threading.Event()
    started = threading.Event()
    lost = threading.Event()
    t = threading.Thread(
        target=run_scheduler_lifecycle,
        kwargs=dict(
            redis_client=r, site="site1", instance_id="A",
            lock_ttl_seconds=2, renew_interval_seconds=1, poll_interval_seconds=1,
            stop_event=stop, started_event=started, loops_disabled=True,
            lost_lock_event_for_test=lost,
        ),
        daemon=True,
    )
    t.start()
    assert started.wait(timeout=5)
    # Steal the lock.
    r.set(lock_redis_key("site1"), "X")
    # Renewer should detect within 1s of next renewal tick (≤ 2s wall clock).
    assert lost.wait(timeout=4)
    # The thread should self-terminate.
    t.join(timeout=5)
    assert not t.is_alive()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests/test_scheduler_lifecycle.py -v
```

Expected: ImportError — `conductor.scheduler` doesn't exist yet.

- [ ] **Step 3: Write minimal scheduler skeleton**

Write to `<BENCH>/apps/conductor/conductor/scheduler.py`:

```python
"""Conductor scheduler — per-site singleton owning four background loops.

Lock holder runs delay/cron/reaper/sweeper loops as daemon threads. On lost
lock (renewal returns False), the renewer sets `lost_lock_event`; the main
function returns and the supervisor (bench/systemd) restarts the process.

This module is built incrementally:
- Task 5: skeleton (lifecycle + renewer + lost-lock fence; loops disabled).
- Task 6: cron loop.
- Task 7: delay loop.
- Task 8: reaper loop.
- Task 9: sweeper loop.
"""

from __future__ import annotations

import os
import signal
import socket
import threading
import time
import uuid

import redis as redis_mod

from conductor.logging import get_logger
from conductor.scheduler_lock import acquire, lock_redis_key, release, renew

log = get_logger("conductor.scheduler")


def _make_instance_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _renewer(
    client: redis_mod.Redis,
    site: str,
    instance_id: str,
    *,
    ttl: int,
    interval: float,
    stop_event: threading.Event,
    lost_lock_event: threading.Event,
):
    """Daemon thread: every `interval` seconds, renew the lock. If renewal
    returns False (we no longer own the key), set `lost_lock_event` and exit."""
    while not stop_event.is_set():
        ok = renew(client, site, instance_id, ttl=ttl)
        if not ok:
            log.error("scheduler_lost_lock", site=site, instance_id=instance_id)
            lost_lock_event.set()
            return
        stop_event.wait(interval)


def run_scheduler_lifecycle(
    *,
    redis_client: redis_mod.Redis,
    site: str,
    instance_id: str,
    lock_ttl_seconds: int = 15,
    renew_interval_seconds: int = 5,
    poll_interval_seconds: int = 5,
    stop_event: threading.Event | None = None,
    started_event: threading.Event | None = None,
    loops_disabled: bool = False,
    sites_path: str | None = None,
    lost_lock_event_for_test: threading.Event | None = None,
):
    """Block until we acquire the lock; then run loops until stop_event or lost lock.

    Test hooks:
      - `started_event` — set after we acquire the lock.
      - `loops_disabled` — skip starting the four loops (we're testing the
        lifecycle in isolation; loops require frappe init).
      - `lost_lock_event_for_test` — same lost-lock event used internally; the
        test asserts it gets set when the lock is stolen.
    """
    stop_event = stop_event or threading.Event()
    lost_lock_event = lost_lock_event_for_test or threading.Event()

    # Phase 1: poll for the lock.
    while not stop_event.is_set():
        if acquire(redis_client, site, instance_id, ttl=lock_ttl_seconds):
            break
        stop_event.wait(poll_interval_seconds)
    if stop_event.is_set():
        return

    log.info("scheduler_acquired_lock", site=site, instance_id=instance_id)
    if started_event:
        started_event.set()

    # Phase 2: run the renewer + (later) the four loops.
    renewer = threading.Thread(
        target=_renewer,
        kwargs=dict(
            client=redis_client, site=site, instance_id=instance_id,
            ttl=lock_ttl_seconds, interval=renew_interval_seconds,
            stop_event=stop_event, lost_lock_event=lost_lock_event,
        ),
        daemon=True, name="conductor-scheduler-renewer",
    )
    renewer.start()

    loop_threads: list[threading.Thread] = []
    if not loops_disabled:
        # Filled in by Tasks 6-9.
        from conductor.scheduler_loops import start_all_loops  # noqa: F401
        loop_threads = start_all_loops(
            redis_client=redis_client, site=site, sites_path=sites_path,
            stop_event=stop_event, lost_lock_event=lost_lock_event,
        )

    # Wait for stop or lost-lock. Either way, drain and release.
    while not stop_event.is_set() and not lost_lock_event.is_set():
        time.sleep(0.1)
    log.info("scheduler_shutting_down",
             site=site, instance_id=instance_id,
             reason="stop" if stop_event.is_set() else "lost_lock")
    stop_event.set()  # Signal everyone if it was lost-lock that woke us.
    for t in loop_threads:
        t.join(timeout=5)
    renewer.join(timeout=5)
    # Only release if we still own it (lost-lock path: don't unset a peer's lock).
    release(redis_client, site, instance_id)


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


def run_scheduler(
    *,
    site: str,
    lock_ttl_seconds: int = 15,
    renew_interval_seconds: int = 5,
    poll_interval_seconds: int = 5,
):
    """Production entry — called from bench conductor scheduler. Loops outermost
    so a lost-lock exit is followed by a fresh poll."""
    import frappe

    from conductor.client import get_redis
    from conductor.config import load_config
    from conductor.logging import setup_logging
    from conductor.otel import setup_otel

    setup_logging(site=site)
    setup_otel(service_name="conductor-scheduler")
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    sites_path = frappe.local.sites_path
    instance_id = _make_instance_id()
    _install_signal_handlers()

    log_ctx = log.bind(site=site, instance_id=instance_id)
    log_ctx.info("scheduler_started",
                 lock_ttl=lock_ttl_seconds,
                 renew_interval=renew_interval_seconds)

    while not _shutdown.is_set():
        cycle_stop = threading.Event()
        # Bridge: when the global _shutdown trips, also set this cycle's stop.
        bridge = threading.Thread(
            target=lambda: (_shutdown.wait(), cycle_stop.set()),
            daemon=True, name="conductor-scheduler-shutdown-bridge",
        )
        bridge.start()
        run_scheduler_lifecycle(
            redis_client=r, site=site, instance_id=instance_id,
            lock_ttl_seconds=lock_ttl_seconds,
            renew_interval_seconds=renew_interval_seconds,
            poll_interval_seconds=poll_interval_seconds,
            stop_event=cycle_stop, sites_path=sites_path,
        )
        if not _shutdown.is_set():
            log_ctx.warning("scheduler_lost_lock_or_exited_cleanly_recycling")
            time.sleep(1)
    log_ctx.info("scheduler_stopped")
```

Also create the empty `conductor/scheduler_loops.py` module so the import in `run_scheduler_lifecycle` resolves under `loops_disabled=False`:

Write to `<BENCH>/apps/conductor/conductor/scheduler_loops.py`:

```python
"""Aggregator for the four scheduler loops. Each Task 6-9 fills in one loop."""

from __future__ import annotations

import threading

import redis as redis_mod


def start_all_loops(
    *,
    redis_client: redis_mod.Redis,
    site: str,
    sites_path: str | None,
    stop_event: threading.Event,
    lost_lock_event: threading.Event,
) -> list[threading.Thread]:
    """Start delay, cron, reaper, sweeper as daemon threads. Returns the list."""
    threads: list[threading.Thread] = []
    # Filled in by Tasks 6 (cron), 7 (delay), 8 (reaper), 9 (sweeper).
    return threads
```

- [ ] **Step 4: Run the lifecycle tests**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests/test_scheduler_lifecycle.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add conductor/scheduler.py conductor/scheduler_loops.py tests/test_scheduler_lifecycle.py && git commit -m "feat(scheduler): lifecycle skeleton — lock-hold + renewer + lost-lock fence"
```

---

## Task 6: Cron loop — walk Conductor Schedule, fire due rows via `conductor.enqueue`

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/scheduler_loops.py` (replaces the stub)
- Create: `<BENCH>/apps/conductor/tests/test_cron_loop.py`

- [ ] **Step 1: Write failing tests**

Write to `<BENCH>/apps/conductor/tests/test_cron_loop.py`:

```python
"""Unit tests for the cron loop — fire_schedule and one-shot loop iteration.

These exercise the loop body directly rather than spinning a real thread."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from conductor.scheduler_loops import _fire_schedule_once, _cron_loop_iter


@patch("conductor.scheduler_loops.frappe")
@patch("conductor.scheduler_loops.conductor_enqueue")
def test_fire_schedule_calls_enqueue_with_kwargs(mock_enqueue, mock_frappe):
    mock_enqueue.return_value = "job-123"
    doc = MagicMock()
    doc.method = "myapp.tasks.x"
    doc.queue = "default"
    doc.max_attempts = 5
    doc.kwargs = ""  # no kwargs
    mock_frappe.get_doc.return_value = doc

    now = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    _fire_schedule_once("sched-1", now, mock_frappe)

    mock_enqueue.assert_called_once_with("myapp.tasks.x", queue="default", max_attempts=5)
    doc.db_set.assert_any_call("last_status", "DISPATCHED", update_modified=False)
    doc.db_set.assert_any_call("last_job", "job-123", update_modified=False)


@patch("conductor.scheduler_loops.frappe")
@patch("conductor.scheduler_loops.conductor_enqueue")
def test_fire_schedule_handles_enqueue_failure(mock_enqueue, mock_frappe):
    mock_enqueue.side_effect = RuntimeError("redis down")
    doc = MagicMock()
    doc.method = "myapp.tasks.x"
    doc.queue = "default"
    doc.max_attempts = None
    doc.kwargs = ""
    mock_frappe.get_doc.return_value = doc

    now = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    _fire_schedule_once("sched-1", now, mock_frappe)

    doc.db_set.assert_any_call("last_status", "DISPATCH_FAILED", update_modified=False)
    # last_job is NOT set on failure.
    set_calls = [c for c in doc.db_set.call_args_list if c.args[0] == "last_job"]
    assert set_calls == []


@patch("conductor.scheduler_loops.frappe")
@patch("conductor.scheduler_loops._fire_schedule_once")
def test_cron_loop_iter_picks_only_due_rows(mock_fire, mock_frappe):
    now = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    # frappe.db.sql returns due-row dicts.
    mock_frappe.db.sql.return_value = [{"name": "due-1"}, {"name": "due-2"}]
    _cron_loop_iter(now, mock_frappe)
    assert mock_fire.call_count == 2
    fired_names = sorted(c.args[0] for c in mock_fire.call_args_list)
    assert fired_names == ["due-1", "due-2"]


@patch("conductor.scheduler_loops.frappe")
def test_cron_loop_iter_no_due_rows_is_noop(mock_frappe):
    now = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    mock_frappe.db.sql.return_value = []
    # Should not raise.
    _cron_loop_iter(now, mock_frappe)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests/test_cron_loop.py -v
```

Expected: ImportError on `_fire_schedule_once` / `_cron_loop_iter`.

- [ ] **Step 3: Implement the cron loop**

Replace `<BENCH>/apps/conductor/conductor/scheduler_loops.py` with:

```python
"""Aggregator for the four scheduler loops.

Each loop is a daemon thread that catches per-iteration exceptions and logs
them, so a transient DB or Redis failure never kills the scheduler. Each
iteration opens its own frappe.init/connect → … → frappe.db.commit() →
frappe.destroy() cycle (the Werkzeug-Local rule from Phase 1 hand-off §5).
"""

from __future__ import annotations

import base64
import threading
from datetime import datetime, timezone
from typing import Any

import redis as redis_mod

from conductor.cron import compute_next_run_at
from conductor.dispatcher import enqueue as conductor_enqueue
from conductor.logging import get_logger
from conductor.serialization import loads as msgpack_loads

log = get_logger("conductor.scheduler_loops")

CRON_LOOP_INTERVAL_SECONDS = 1.0


def _decode_kwargs(kwargs_b64: str) -> dict[str, Any]:
    """Reverse the schedule's stored kwargs (msgpack→base64). Empty → {}."""
    if not kwargs_b64:
        return {}
    return msgpack_loads(base64.b64decode(kwargs_b64.encode("ascii")))


def _fire_schedule_once(name: str, now_utc: datetime, frappe) -> None:
    """Fire one schedule: enqueue, update last_status/last_job/last_run_at,
    recompute next_run_at. Catches enqueue failures and records DISPATCH_FAILED."""
    doc = frappe.get_doc("Conductor Schedule", name)
    try:
        kwargs = _decode_kwargs(doc.kwargs) if doc.kwargs else {}
        max_attempts = doc.max_attempts or None
        job_id = conductor_enqueue(
            doc.method, queue=doc.queue, max_attempts=max_attempts, **kwargs,
        )
        doc.db_set("last_status", "DISPATCHED", update_modified=False)
        doc.db_set("last_job", job_id, update_modified=False)
    except Exception as e:
        doc.db_set("last_status", "DISPATCH_FAILED", update_modified=False)
        log.error("cron_fire_failed", schedule=name, error=str(e))

    doc.db_set("last_run_at", now_utc.replace(tzinfo=None), update_modified=False)

    # Recompute next_run_at from the just-fired moment so consecutive loops
    # don't pick the same row again.
    try:
        next_at = compute_next_run_at(doc.cron_expression, doc.timezone or "UTC", base=now_utc)
        doc.db_set("next_run_at", next_at.replace(tzinfo=None), update_modified=False)
    except Exception as e:
        log.error("cron_recompute_failed", schedule=name, error=str(e))


def _cron_loop_iter(now_utc: datetime, frappe) -> None:
    """One pass: SELECT due rows, fire each."""
    rows = frappe.db.sql(
        "SELECT name FROM `tabConductor Schedule` "
        "WHERE enabled=1 AND next_run_at IS NOT NULL AND next_run_at <= %s",
        (now_utc.replace(tzinfo=None),),
        as_dict=True,
    )
    for r in rows:
        try:
            _fire_schedule_once(r["name"], now_utc, frappe)
        except Exception as e:
            log.error("cron_fire_outer_failed", schedule=r["name"], error=str(e))


def _cron_loop(stop_event: threading.Event, lost_lock_event: threading.Event,
               site: str, sites_path: str | None) -> None:
    log.info("cron_loop_started", site=site)
    import frappe
    while not (stop_event.is_set() or lost_lock_event.is_set()):
        try:
            frappe.init(site=site, sites_path=sites_path)
            frappe.connect()
            try:
                now = datetime.now(timezone.utc)
                _cron_loop_iter(now, frappe)
                frappe.db.commit()
            finally:
                frappe.destroy()
        except Exception as e:
            log.error("cron_loop_iteration_failed", error=str(e))
        stop_event.wait(CRON_LOOP_INTERVAL_SECONDS)
    log.info("cron_loop_stopped", site=site)


def start_all_loops(
    *,
    redis_client: redis_mod.Redis,
    site: str,
    sites_path: str | None,
    stop_event: threading.Event,
    lost_lock_event: threading.Event,
) -> list[threading.Thread]:
    threads: list[threading.Thread] = []
    threads.append(threading.Thread(
        target=_cron_loop,
        args=(stop_event, lost_lock_event, site, sites_path),
        daemon=True, name="conductor-scheduler-cron",
    ))
    # Tasks 7, 8, 9 will append delay, reaper, sweeper here.
    for t in threads:
        t.start()
    return threads
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests/test_cron_loop.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Smoke-check Phase 1 unit tests still pass**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests/ -q
```

Expected: 86 passed (71 Phase 1 + cron + scheduler_lock + scheduler_lifecycle + cron_loop = 71 + 8 + 10 + 3 + 4 = 96).

- [ ] **Step 6: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor && git add conductor/scheduler_loops.py tests/test_cron_loop.py && git commit -m "feat(scheduler): cron loop — fires due Conductor Schedule rows via conductor.enqueue"
```

---

## Task 7: Delay loop — drain ZSET → XADD streams

**Files:**
- Modify: `<BENCH>/apps/conductor/conductor/scheduler_loops.py`
- Create: `<BENCH>/apps/conductor/tests/test_delay_loop.py`

- [ ] **Step 1: Write failing tests**

Write to `<BENCH>/apps/conductor/tests/test_delay_loop.py`:

```python
"""Unit tests for the scheduler's delay loop — drains ZSET → XADDs streams."""

import json
import time

import fakeredis
import pytest

from conductor.scheduled import scheduled_redis_key
from conductor.scheduler_loops import _delay_loop_iter
from conductor.streams import stream_key


@pytest.fixture
def r():
    return fakeredis.FakeStrictRedis()


def _make_encoded(queue: str, job_id: str = "j") -> dict[str, str]:
    return {
        "job_id": job_id,
        "site": "site1",
        "name": "x.y",
        "queue": queue,
        "args_b64": "",
        "kwargs_b64": "",
        "attempt": "1",
        "max_attempts": "1",
        "timeout_seconds": "60",
        "enqueued_at": "2026-04-27T12:00:00+00:00",
        "schema_version": "1",
    }


def test_due_messages_xadded_to_stream(r):
    site = "site1"
    encoded = _make_encoded("default")
    member = json.dumps(encoded)
    score = int(time.time() * 1000) - 5000  # due 5s ago
    r.zadd(scheduled_redis_key(site), {member: score})
    _delay_loop_iter(r, site)
    # ZSET drained.
    assert r.zcard(scheduled_redis_key(site)) == 0
    # Stream got the entry.
    skey = stream_key(site, "default")
    entries = r.xrange(skey)
    assert len(entries) == 1


def test_future_messages_left_alone(r):
    site = "site1"
    encoded = _make_encoded("default")
    member = json.dumps(encoded)
    score = int(time.time() * 1000) + 60_000  # due in 60s
    r.zadd(scheduled_redis_key(site), {member: score})
    _delay_loop_iter(r, site)
    assert r.zcard(scheduled_redis_key(site)) == 1


def test_messages_for_multiple_queues_route_correctly(r):
    site = "site1"
    now_ms = int(time.time() * 1000)
    a = _make_encoded("queueA", "ja")
    b = _make_encoded("queueB", "jb")
    r.zadd(scheduled_redis_key(site), {json.dumps(a): now_ms - 1000})
    r.zadd(scheduled_redis_key(site), {json.dumps(b): now_ms - 1000})
    _delay_loop_iter(r, site)
    assert len(r.xrange(stream_key(site, "queueA"))) == 1
    assert len(r.xrange(stream_key(site, "queueB"))) == 1


def test_message_with_empty_queue_is_skipped(r):
    site = "site1"
    encoded = _make_encoded("")
    r.zadd(scheduled_redis_key(site), {json.dumps(encoded): int(time.time() * 1000) - 1000})
    _delay_loop_iter(r, site)
    # Drained from ZSET (we still ZREM bad messages so they don't pile up).
    assert r.zcard(scheduled_redis_key(site)) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests/test_delay_loop.py -v
```

Expected: ImportError on `_delay_loop_iter`.

- [ ] **Step 3: Add the delay loop**

Edit `<BENCH>/apps/conductor/conductor/scheduler_loops.py`. Replace the entire file with the cron loop's content **plus** the additions below:

```python
"""Aggregator for the four scheduler loops.

Each loop is a daemon thread that catches per-iteration exceptions and logs
them, so a transient DB or Redis failure never kills the scheduler. Each
iteration opens its own frappe.init/connect → … → frappe.db.commit() →
frappe.destroy() cycle (the Werkzeug-Local rule from Phase 1 hand-off §5).
"""

from __future__ import annotations

import base64
import threading
from datetime import datetime, timezone
from typing import Any

import redis as redis_mod

from conductor.cron import compute_next_run_at
from conductor.dispatcher import enqueue as conductor_enqueue
from conductor.logging import get_logger
from conductor.scheduled import drain_due_messages
from conductor.serialization import loads as msgpack_loads
from conductor.streams import ensure_consumer_group, stream_key

log = get_logger("conductor.scheduler_loops")

CRON_LOOP_INTERVAL_SECONDS = 1.0
DELAY_LOOP_INTERVAL_SECONDS = 1.0


# --- cron ---------------------------------------------------------------------


def _decode_kwargs(kwargs_b64: str) -> dict[str, Any]:
    if not kwargs_b64:
        return {}
    return msgpack_loads(base64.b64decode(kwargs_b64.encode("ascii")))


def _fire_schedule_once(name: str, now_utc: datetime, frappe) -> None:
    doc = frappe.get_doc("Conductor Schedule", name)
    try:
        kwargs = _decode_kwargs(doc.kwargs) if doc.kwargs else {}
        max_attempts = doc.max_attempts or None
        job_id = conductor_enqueue(
            doc.method, queue=doc.queue, max_attempts=max_attempts, **kwargs,
        )
        doc.db_set("last_status", "DISPATCHED", update_modified=False)
        doc.db_set("last_job", job_id, update_modified=False)
    except Exception as e:
        doc.db_set("last_status", "DISPATCH_FAILED", update_modified=False)
        log.error("cron_fire_failed", schedule=name, error=str(e))

    doc.db_set("last_run_at", now_utc.replace(tzinfo=None), update_modified=False)
    try:
        next_at = compute_next_run_at(doc.cron_expression, doc.timezone or "UTC", base=now_utc)
        doc.db_set("next_run_at", next_at.replace(tzinfo=None), update_modified=False)
    except Exception as e:
        log.error("cron_recompute_failed", schedule=name, error=str(e))


def _cron_loop_iter(now_utc: datetime, frappe) -> None:
    rows = frappe.db.sql(
        "SELECT name FROM `tabConductor Schedule` "
        "WHERE enabled=1 AND next_run_at IS NOT NULL AND next_run_at <= %s",
        (now_utc.replace(tzinfo=None),),
        as_dict=True,
    )
    for r in rows:
        try:
            _fire_schedule_once(r["name"], now_utc, frappe)
        except Exception as e:
            log.error("cron_fire_outer_failed", schedule=r["name"], error=str(e))


def _cron_loop(stop_event: threading.Event, lost_lock_event: threading.Event,
               site: str, sites_path: str | None) -> None:
    log.info("cron_loop_started", site=site)
    import frappe
    while not (stop_event.is_set() or lost_lock_event.is_set()):
        try:
            frappe.init(site=site, sites_path=sites_path)
            frappe.connect()
            try:
                now = datetime.now(timezone.utc)
                _cron_loop_iter(now, frappe)
                frappe.db.commit()
            finally:
                frappe.destroy()
        except Exception as e:
            log.error("cron_loop_iteration_failed", error=str(e))
        stop_event.wait(CRON_LOOP_INTERVAL_SECONDS)
    log.info("cron_loop_stopped", site=site)


# --- delay --------------------------------------------------------------------


def _delay_loop_iter(redis_client: redis_mod.Redis, site: str) -> int:
    """Drain due ZSET messages → XADD their target streams. Returns drained count."""
    due = drain_due_messages(redis_client, site)
    drained = 0
    for encoded in due:
        queue = encoded.get("queue") or ""
        if not queue:
            log.warning("delay_loop_skipped_empty_queue", encoded=encoded)
            continue
        target = stream_key(site, queue)
        ensure_consumer_group(redis_client, target)
        redis_client.xadd(target, encoded, maxlen=10000, approximate=True)
        drained += 1
    return drained


def _delay_loop(redis_client: redis_mod.Redis, site: str,
                stop_event: threading.Event, lost_lock_event: threading.Event) -> None:
    log.info("delay_loop_started", site=site)
    while not (stop_event.is_set() or lost_lock_event.is_set()):
        try:
            _delay_loop_iter(redis_client, site)
        except Exception as e:
            log.error("delay_loop_iteration_failed", error=str(e))
        stop_event.wait(DELAY_LOOP_INTERVAL_SECONDS)
    log.info("delay_loop_stopped", site=site)


# --- aggregator ---------------------------------------------------------------


def start_all_loops(
    *,
    redis_client: redis_mod.Redis,
    site: str,
    sites_path: str | None,
    stop_event: threading.Event,
    lost_lock_event: threading.Event,
) -> list[threading.Thread]:
    threads: list[threading.Thread] = []
    threads.append(threading.Thread(
        target=_cron_loop,
        args=(stop_event, lost_lock_event, site, sites_path),
        daemon=True, name="conductor-scheduler-cron",
    ))
    threads.append(threading.Thread(
        target=_delay_loop,
        args=(redis_client, site, stop_event, lost_lock_event),
        daemon=True, name="conductor-scheduler-delay",
    ))
    # Tasks 8, 9 will append reaper and sweeper here.
    for t in threads:
        t.start()
    return threads
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests/test_delay_loop.py apps/conductor/tests/test_cron_loop.py -v
```

Expected: 4 + 4 = 8 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor && git add conductor/scheduler_loops.py tests/test_delay_loop.py && git commit -m "feat(scheduler): delay loop — ZSET drainer that lifts the in-worker DelayDrainer"
```

---

## Task 8: Reaper loop — STALE/GONE transitions + 7-day prune

**Files:**
- Modify: `<BENCH>/apps/conductor/conductor/scheduler_loops.py`
- Create: `<BENCH>/apps/conductor/tests/test_reaper_loop.py`

- [ ] **Step 1: Write failing tests**

Write to `<BENCH>/apps/conductor/tests/test_reaper_loop.py`:

```python
"""Unit tests for the reaper loop — STALE/GONE transitions + 7d prune."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from conductor.scheduler_loops import _reaper_loop_iter


def test_reaper_runs_three_sql_updates_in_order():
    frappe = MagicMock()
    site = "site1"
    _reaper_loop_iter(site, frappe)
    # Expect three sql calls: GONE, STALE, DELETE — in that order.
    assert frappe.db.sql.call_count == 3
    sql_texts = [c.args[0].strip().split()[0].upper() for c in frappe.db.sql.call_args_list]
    assert sql_texts == ["UPDATE", "UPDATE", "DELETE"]


def test_reaper_passes_correct_thresholds():
    frappe = MagicMock()
    _reaper_loop_iter("site1", frappe)
    # Inspect the parameters of each call.
    params = [c.args[1] for c in frappe.db.sql.call_args_list]
    # Each call's params is (site, cutoff[, …]).
    for p in params:
        assert p[0] == "site1"
    # GONE cutoff (≥ 120 s ago), STALE cutoff (≥ 30 s ago, < 120 s).
    gone_cut = params[0][1]
    stale_cut = params[1][1]
    prune_cut = params[2][1]
    now = datetime.now()
    assert (now - gone_cut).total_seconds() >= 119
    assert (now - stale_cut).total_seconds() >= 29
    assert (now - prune_cut).total_seconds() >= 7 * 24 * 3600 - 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests/test_reaper_loop.py -v
```

Expected: ImportError on `_reaper_loop_iter`.

- [ ] **Step 3: Add the reaper loop to `scheduler_loops.py`**

Append the following to `<BENCH>/apps/conductor/conductor/scheduler_loops.py` (between the `--- delay ---` section and the `--- aggregator ---` section):

```python
# --- reaper -------------------------------------------------------------------

REAPER_LOOP_INTERVAL_SECONDS = 60.0
REAPER_STALE_AGE_SECONDS = 30
REAPER_GONE_AGE_SECONDS = 120
REAPER_PRUNE_AGE_SECONDS = 7 * 24 * 3600


def _reaper_loop_iter(site: str, frappe) -> None:
    """One reaper pass: mark STALE/GONE based on heartbeat age, prune old rows."""
    now = datetime.now()
    gone_cut = now - timedelta(seconds=REAPER_GONE_AGE_SECONDS)
    stale_cut = now - timedelta(seconds=REAPER_STALE_AGE_SECONDS)
    prune_cut = now - timedelta(seconds=REAPER_PRUNE_AGE_SECONDS)

    # Order matters: mark GONE first, then STALE (which excludes already-GONE rows).
    frappe.db.sql(
        "UPDATE `tabConductor Worker` SET status='GONE' "
        "WHERE site=%s AND status<>'GONE' AND last_heartbeat < %s",
        (site, gone_cut),
    )
    frappe.db.sql(
        "UPDATE `tabConductor Worker` SET status='STALE' "
        "WHERE site=%s AND status='ALIVE' AND last_heartbeat < %s "
        "AND last_heartbeat >= %s",
        (site, stale_cut, gone_cut),
    )
    frappe.db.sql(
        "DELETE FROM `tabConductor Worker` "
        "WHERE site=%s AND last_heartbeat < %s",
        (site, prune_cut),
    )


def _reaper_loop(stop_event: threading.Event, lost_lock_event: threading.Event,
                 site: str, sites_path: str | None) -> None:
    log.info("reaper_loop_started", site=site)
    import frappe
    while not (stop_event.is_set() or lost_lock_event.is_set()):
        try:
            frappe.init(site=site, sites_path=sites_path)
            frappe.connect()
            try:
                _reaper_loop_iter(site, frappe)
                frappe.db.commit()
            finally:
                frappe.destroy()
        except Exception as e:
            log.error("reaper_loop_iteration_failed", error=str(e))
        stop_event.wait(REAPER_LOOP_INTERVAL_SECONDS)
    log.info("reaper_loop_stopped", site=site)
```

And add it to `start_all_loops` (the third thread):

```python
    threads.append(threading.Thread(
        target=_reaper_loop,
        args=(stop_event, lost_lock_event, site, sites_path),
        daemon=True, name="conductor-scheduler-reaper",
    ))
```

(insert this after the `_delay_loop` thread append, before the `for t in threads: t.start()`)

- [ ] **Step 4: Run tests**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests/test_reaper_loop.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor && git add conductor/scheduler_loops.py tests/test_reaper_loop.py && git commit -m "feat(scheduler): reaper loop — STALE/GONE transitions + 7d row prune"
```

---

## Task 9: Sweeper loop — orphan recovery, lifted from worker

**Files:**
- Modify: `<BENCH>/apps/conductor/conductor/scheduler_loops.py`
- Create: `<BENCH>/apps/conductor/tests/test_sweeper_loop.py`

- [ ] **Step 1: Write failing tests**

Write to `<BENCH>/apps/conductor/tests/test_sweeper_loop.py`:

```python
"""Unit tests for the sweeper loop — delegates to existing sweep_orphans()."""

from unittest.mock import MagicMock, patch

from conductor.scheduler_loops import _sweeper_loop_iter


@patch("conductor.scheduler_loops.sweep_orphans")
def test_sweeper_iter_calls_sweep_orphans(mock_sweep):
    mock_sweep.return_value = 3
    redis_client = MagicMock()
    _sweeper_loop_iter(redis_client, "site1")
    mock_sweep.assert_called_once_with(redis_client, "site1")


@patch("conductor.scheduler_loops.sweep_orphans")
def test_sweeper_iter_swallows_exceptions(mock_sweep):
    mock_sweep.side_effect = RuntimeError("DB blew up")
    redis_client = MagicMock()
    # Should NOT raise — the loop wrapper catches, but the helper itself
    # may bubble. The loop body in scheduler_loops catches it.
    # _sweeper_loop_iter is the inner helper that should propagate; the
    # caller (the thread loop) catches.
    import pytest
    with pytest.raises(RuntimeError):
        _sweeper_loop_iter(redis_client, "site1")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests/test_sweeper_loop.py -v
```

Expected: ImportError on `_sweeper_loop_iter`.

- [ ] **Step 3: Add the sweeper loop to `scheduler_loops.py`**

Add this import near the other imports in `scheduler_loops.py`:

```python
from conductor.sweeper import sweep_orphans
```

Append the following just above the `# --- aggregator ---` section:

```python
# --- sweeper ------------------------------------------------------------------

SWEEPER_LOOP_INTERVAL_SECONDS = 30.0


def _sweeper_loop_iter(redis_client: redis_mod.Redis, site: str) -> int:
    """One sweep pass — delegates to the existing sweep_orphans helper."""
    return sweep_orphans(redis_client, site)


def _sweeper_loop(redis_client: redis_mod.Redis, site: str,
                  sites_path: str | None,
                  stop_event: threading.Event,
                  lost_lock_event: threading.Event) -> None:
    log.info("sweeper_loop_started", site=site)
    import frappe
    while not (stop_event.is_set() or lost_lock_event.is_set()):
        try:
            frappe.init(site=site, sites_path=sites_path)
            frappe.connect()
            try:
                _sweeper_loop_iter(redis_client, site)
            finally:
                frappe.destroy()
        except Exception as e:
            log.error("sweeper_loop_iteration_failed", error=str(e))
        stop_event.wait(SWEEPER_LOOP_INTERVAL_SECONDS)
    log.info("sweeper_loop_stopped", site=site)
```

And add the fourth thread to `start_all_loops`:

```python
    threads.append(threading.Thread(
        target=_sweeper_loop,
        args=(redis_client, site, sites_path, stop_event, lost_lock_event),
        daemon=True, name="conductor-scheduler-sweeper",
    ))
```

(append after the reaper thread, before `for t in threads: t.start()`)

- [ ] **Step 4: Run tests**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests/test_sweeper_loop.py apps/conductor/tests/test_reaper_loop.py apps/conductor/tests/test_delay_loop.py apps/conductor/tests/test_cron_loop.py -v
```

Expected: 2 + 2 + 4 + 4 = 12 passed.

- [ ] **Step 5: Commit**

```bash
git add conductor/scheduler_loops.py tests/test_sweeper_loop.py && git commit -m "feat(scheduler): sweeper loop — lifts the in-worker OrphanSweeper"
```

---

## Task 10: `bench conductor scheduler` command + register in `commands/__init__.py`

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/commands/scheduler.py`
- Modify: `<BENCH>/apps/conductor/conductor/commands/__init__.py`

- [ ] **Step 1: Write the click command**

Write to `<BENCH>/apps/conductor/conductor/commands/scheduler.py`:

```python
"""bench conductor scheduler — run a long-lived scheduler process."""

from __future__ import annotations

import click
import frappe
from frappe.commands import get_site, pass_context


@click.command("scheduler")
@click.option("--lock-ttl-seconds", default=15, type=int,
              help="Singleton lock TTL (production default 15s).")
@click.option("--renew-interval-seconds", default=5, type=int,
              help="How often the holder renews the lock (default 5s).")
@click.option("--poll-interval-seconds", default=5, type=int,
              help="How often non-holders poll for the lock (default 5s).")
@pass_context
def scheduler_command(ctx, lock_ttl_seconds, renew_interval_seconds, poll_interval_seconds):
    """Run a Conductor scheduler process. Site comes from bench --site."""
    site = get_site(ctx)
    frappe.init(site=site)
    frappe.connect()
    try:
        from conductor.scheduler import run_scheduler
        run_scheduler(
            site=site,
            lock_ttl_seconds=lock_ttl_seconds,
            renew_interval_seconds=renew_interval_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
    finally:
        frappe.destroy()
```

- [ ] **Step 2: Register the command**

Edit `<BENCH>/apps/conductor/conductor/commands/__init__.py`:

```python
"""Click command group exported to bench via hooks.py."""

import click

from conductor.commands.cancel import cancel_command
from conductor.commands.doctor import doctor_command
from conductor.commands.scheduler import scheduler_command
from conductor.commands.worker import worker_command


@click.group("conductor")
def conductor_group():
    """Conductor — reliability-first background jobs."""


conductor_group.add_command(worker_command)
conductor_group.add_command(doctor_command)
conductor_group.add_command(cancel_command)
conductor_group.add_command(scheduler_command)


commands = [conductor_group]
```

- [ ] **Step 3: Verify the command is registered**

```bash
cd /Users/osamamuhammed/frappe_15 && bench --site frappe.localhost conductor --help 2>&1 | tail -20
```

Expected: output lists `scheduler` alongside `worker`, `doctor`, `cancel`.

- [ ] **Step 4: Smoke test — start scheduler in background, verify it acquires the lock**

In one terminal (or use background mode):

```bash
cd /Users/osamamuhammed/frappe_15 && timeout 5 bench --site frappe.localhost conductor scheduler --lock-ttl-seconds=3 --renew-interval-seconds=1 --poll-interval-seconds=1 2>&1 | head -10 || true
```

Expected: stdout includes a `scheduler_acquired_lock` log entry (we sigkill it via `timeout` after 5s).

While it's running, in a separate run, check the lock key:

```bash
cd /Users/osamamuhammed/frappe_15 && (bench --site frappe.localhost conductor scheduler --lock-ttl-seconds=15 --renew-interval-seconds=5 --poll-interval-seconds=2 &)
SCHED_PID=$!
sleep 3
redis-cli -p 11000 -n 2 GET "conductor:frappe.localhost:scheduler:lock"
sleep 1
kill -TERM $SCHED_PID 2>/dev/null || pkill -TERM -f 'conductor scheduler' || true
sleep 1
redis-cli -p 11000 -n 2 GET "conductor:frappe.localhost:scheduler:lock"
```

Expected: first GET returns a non-empty string like `hostname:pid:hex`; second GET returns `(nil)` (released cleanly on shutdown).

- [ ] **Step 5: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor && git add conductor/commands/scheduler.py conductor/commands/__init__.py && git commit -m "feat(commands): bench conductor scheduler"
```

---

## Task 11: `bench conductor schedule {list, enable, disable, run-now}` + tests

**Files:**
- Create: `<BENCH>/apps/conductor/conductor/commands/schedule.py`
- Modify: `<BENCH>/apps/conductor/conductor/commands/__init__.py`
- Create: `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_schedule/test_run_now.py`

- [ ] **Step 1: Write the click command group**

Write to `<BENCH>/apps/conductor/conductor/commands/schedule.py`:

```python
"""bench conductor schedule — list/enable/disable/run-now subcommands."""

from __future__ import annotations

import sys

import click
import frappe
from frappe.commands import get_site, pass_context


@click.group("schedule")
def schedule_group():
    """Manage Conductor schedules."""


@schedule_group.command("list")
@pass_context
def schedule_list(ctx):
    """Print all schedules."""
    site = get_site(ctx)
    frappe.init(site=site)
    frappe.connect()
    try:
        rows = frappe.db.sql(
            "SELECT name, enabled, cron_expression, timezone, "
            "next_run_at, last_status FROM `tabConductor Schedule` ORDER BY name",
            as_dict=True,
        )
        if not rows:
            click.echo("(no schedules)")
            return
        click.echo(f"{'NAME':24} {'EN':2} {'CRON':16} {'TZ':18} {'NEXT_RUN':25} LAST_STATUS")
        for r in rows:
            click.echo(
                f"{r['name'][:24]:24} "
                f"{r['enabled']:2} "
                f"{(r['cron_expression'] or '')[:16]:16} "
                f"{(r['timezone'] or '')[:18]:18} "
                f"{str(r['next_run_at'] or '')[:25]:25} "
                f"{r['last_status'] or ''}"
            )
    finally:
        frappe.destroy()


@schedule_group.command("enable")
@click.argument("name")
@pass_context
def schedule_enable(ctx, name):
    """Enable a schedule and recompute next_run_at."""
    site = get_site(ctx)
    frappe.init(site=site)
    frappe.connect()
    try:
        if not frappe.db.exists("Conductor Schedule", name):
            click.echo(f"unknown schedule: {name}", err=True)
            sys.exit(1)
        doc = frappe.get_doc("Conductor Schedule", name)
        doc.enabled = 1
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        click.echo(f"enabled: {name} (next_run_at={doc.next_run_at})")
    finally:
        frappe.destroy()


@schedule_group.command("disable")
@click.argument("name")
@pass_context
def schedule_disable(ctx, name):
    """Disable a schedule. next_run_at is cleared."""
    site = get_site(ctx)
    frappe.init(site=site)
    frappe.connect()
    try:
        if not frappe.db.exists("Conductor Schedule", name):
            click.echo(f"unknown schedule: {name}", err=True)
            sys.exit(1)
        doc = frappe.get_doc("Conductor Schedule", name)
        doc.enabled = 0
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        click.echo(f"disabled: {name}")
    finally:
        frappe.destroy()


@schedule_group.command("run-now")
@click.argument("name")
@pass_context
def schedule_run_now(ctx, name):
    """Fire the schedule's payload via conductor.enqueue, out-of-band of cron.

    Updates last_status (DISPATCHED on success / DISPATCH_FAILED on failure)
    and last_job. Does NOT touch last_run_at — cron cadence is preserved.
    """
    site = get_site(ctx)
    frappe.init(site=site)
    frappe.connect()
    try:
        if not frappe.db.exists("Conductor Schedule", name):
            click.echo(f"unknown schedule: {name}", err=True)
            sys.exit(1)
        doc = frappe.get_doc("Conductor Schedule", name)
        from conductor.scheduler_loops import _decode_kwargs
        from conductor.dispatcher import enqueue as conductor_enqueue
        try:
            kwargs = _decode_kwargs(doc.kwargs) if doc.kwargs else {}
            max_attempts = doc.max_attempts or None
            job_id = conductor_enqueue(
                doc.method, queue=doc.queue, max_attempts=max_attempts, **kwargs,
            )
            doc.db_set("last_status", "DISPATCHED", update_modified=False)
            doc.db_set("last_job", job_id, update_modified=False)
            frappe.db.commit()
            click.echo(f"fired: {name} → job {job_id}")
        except Exception as e:
            doc.db_set("last_status", "DISPATCH_FAILED", update_modified=False)
            frappe.db.commit()
            click.echo(f"dispatch failed: {name} — {e}", err=True)
            sys.exit(1)
    finally:
        frappe.destroy()
```

- [ ] **Step 2: Register the command group**

Edit `<BENCH>/apps/conductor/conductor/commands/__init__.py` to add the new import and registration:

```python
"""Click command group exported to bench via hooks.py."""

import click

from conductor.commands.cancel import cancel_command
from conductor.commands.doctor import doctor_command
from conductor.commands.schedule import schedule_group
from conductor.commands.scheduler import scheduler_command
from conductor.commands.worker import worker_command


@click.group("conductor")
def conductor_group():
    """Conductor — reliability-first background jobs."""


conductor_group.add_command(worker_command)
conductor_group.add_command(doctor_command)
conductor_group.add_command(cancel_command)
conductor_group.add_command(scheduler_command)
conductor_group.add_command(schedule_group)


commands = [conductor_group]
```

- [ ] **Step 3: Frappe integration test for run-now**

Write to `<BENCH>/apps/conductor/conductor/conductor/doctype/conductor_schedule/test_run_now.py`:

```python
"""Frappe integration test: bench conductor schedule run-now end-to-end."""

from __future__ import annotations

import unittest

import frappe


class TestRunNow(unittest.TestCase):
    def setUp(self):
        if not frappe.db.exists("Conductor Queue", "default"):
            frappe.get_doc({
                "doctype": "Conductor Queue",
                "queue_name": "default",
                "enabled": 1,
            }).insert(ignore_permissions=True)
        # Clean Schedule rows.
        for n in frappe.get_all("Conductor Schedule", pluck="name"):
            frappe.delete_doc("Conductor Schedule", n, force=True)
        # Clean Conductor Job rows from previous runs.
        for n in frappe.get_all("Conductor Job", pluck="name"):
            frappe.delete_doc("Conductor Job", n, force=True)
        frappe.db.commit()

    def test_run_now_dispatches_and_does_not_bump_last_run_at(self):
        from conductor.commands.schedule import schedule_run_now  # noqa
        # Insert a schedule.
        doc = frappe.get_doc({
            "doctype": "Conductor Schedule",
            "schedule_name": "rn-test",
            "enabled": 1,
            "cron_expression": "0 0 1 1 *",  # never (well, yearly Jan 1)
            "timezone": "UTC",
            "method": "frappe.utils.now",
            "queue": "default",
        }).insert(ignore_permissions=True)
        prior_last_run = doc.last_run_at
        # Invoke the run-now logic directly.
        from conductor.scheduler_loops import _decode_kwargs  # noqa
        from conductor.dispatcher import enqueue as conductor_enqueue
        kwargs = _decode_kwargs(doc.kwargs) if doc.kwargs else {}
        job_id = conductor_enqueue(doc.method, queue=doc.queue, **kwargs)
        doc.db_set("last_status", "DISPATCHED", update_modified=False)
        doc.db_set("last_job", job_id, update_modified=False)
        frappe.db.commit()

        # Reload.
        doc.reload()
        self.assertEqual(doc.last_status, "DISPATCHED")
        self.assertEqual(doc.last_job, job_id)
        self.assertEqual(doc.last_run_at, prior_last_run)
        self.assertTrue(frappe.db.exists("Conductor Job", job_id))
```

- [ ] **Step 4: Verify list/enable/disable show up in CLI help**

```bash
cd /Users/osamamuhammed/frappe_15 && bench --site frappe.localhost conductor schedule --help 2>&1 | tail -15
```

Expected: lists `disable`, `enable`, `list`, `run-now`.

- [ ] **Step 5: Run integration test**

```bash
cd /Users/osamamuhammed/frappe_15 && bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_schedule.test_run_now 2>&1 | tail -10
```

Expected: `Ran 1 tests in …s` `OK`.

- [ ] **Step 6: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor && git add conductor/commands/schedule.py conductor/commands/__init__.py conductor/conductor/doctype/conductor_schedule/test_run_now.py && git commit -m "feat(commands): bench conductor schedule list/enable/disable/run-now"
```

---

## Task 12: Worker shrink — drop DelayDrainer + OrphanSweeper threads; heartbeat resets STALE→ALIVE

**Files:**
- Modify: `<BENCH>/apps/conductor/conductor/worker.py`

- [ ] **Step 1: Remove DelayDrainer + OrphanSweeper imports and uses**

Edit `<BENCH>/apps/conductor/conductor/worker.py`:

Find this import line (line ~37):
```python
from conductor.scheduled import DelayDrainer, schedule_message
```
Replace with:
```python
from conductor.scheduled import schedule_message
```

Find this import line (line ~38):
```python
from conductor.sweeper import OrphanSweeper
```
Delete it entirely.

In `run_worker` (line ~466), find the block:
```python
    pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="conductor-")
    drainer = DelayDrainer(r, site)
    sweeper = OrphanSweeper(r, site, sites_path)
    cancel_poller = CancelPoller(worker_id, site, sites_path, _cancel_events, _cancel_events_lock)
    drainer.start()
    sweeper.start()
    cancel_poller.start()
```
Replace with:
```python
    pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="conductor-")
    cancel_poller = CancelPoller(worker_id, site, sites_path, _cancel_events, _cancel_events_lock)
    cancel_poller.start()
```

Find the shutdown block in the `finally:` of `run_worker`:
```python
    finally:
        log_ctx.info("worker_shutting_down", grace_seconds=grace_seconds)
        drainer.stop()
        sweeper.stop()
        cancel_poller.stop()
        pool.shutdown(wait=True)
        _mark_worker_gone(worker_id)
        log_ctx.info("worker_stopped")
```
Replace with:
```python
    finally:
        log_ctx.info("worker_shutting_down", grace_seconds=grace_seconds)
        cancel_poller.stop()
        pool.shutdown(wait=True)
        _mark_worker_gone(worker_id)
        log_ctx.info("worker_stopped")
```

- [ ] **Step 2: Modify `_heartbeat` to reset status='ALIVE'**

Find:
```python
def _heartbeat(worker_id: str) -> None:
    frappe.db.set_value("Conductor Worker", worker_id, "last_heartbeat", _now_naive(), update_modified=False)
    frappe.db.commit()
```
Replace with:
```python
def _heartbeat(worker_id: str) -> None:
    """Heartbeat both writes last_heartbeat AND resets status to ALIVE.

    Without the status reset, a worker that the reaper marked STALE during a
    long GC pause would stay STALE forever in Desk even after it resumed.
    """
    frappe.db.set_value(
        "Conductor Worker",
        worker_id,
        {"last_heartbeat": _now_naive(), "status": "ALIVE"},
        update_modified=False,
    )
    frappe.db.commit()
```

- [ ] **Step 3: Verify the worker still imports cleanly**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/python -c "from conductor.worker import run_worker; print('ok')"
```

Expected: `ok`.

- [ ] **Step 4: Run all Phase 1 unit tests**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests/ -q
```

Expected: all green (Phase 1 tests are unaffected; new Phase 2 unit tests are green from earlier tasks).

- [ ] **Step 5: Run all Phase 1 chaos tests**

Verify nothing broke. From `<BENCH>`:

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests_chaos/ -v 2>&1 | tail -20
```

Expected: 3 passed.

NOTE: With the worker losing its DelayDrainer, retries cannot fire unless something else drains the scheduled set. Phase 1 chaos tests `test_retry_exhausts_to_dlq.py` and `test_kill_during_run.py` rely on retries firing. We need the scheduler running for those — but the chaos conftest does not currently spawn one.

If chaos tests fail at this point, that's the expected gap; Task 14 fixes the chaos conftest to spawn a scheduler subprocess alongside workers. Confirm the failure is "retry never reaches RUNNING" (not some unrelated breakage). If so, proceed to commit and move on; Task 14 makes them green.

- [ ] **Step 6: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor && git add conductor/worker.py && git commit -m "feat(worker): drop DelayDrainer + OrphanSweeper threads; heartbeat resets STALE→ALIVE

The two background threads are now owned by bench conductor scheduler. The
worker loses its in-process retry-pump and orphan-recovery responsibilities;
that work moves to the singleton scheduler.

Heartbeat resets status='ALIVE' so a worker that resumed after a STALE
classification doesn't stay permanently degraded in Desk."
```

---

## Task 13: Delete dead `DelayDrainer` and `OrphanSweeper` classes; keep helpers

**Files:**
- Modify: `<BENCH>/apps/conductor/conductor/scheduled.py`
- Modify: `<BENCH>/apps/conductor/conductor/sweeper.py`

- [ ] **Step 1: Verify no remaining usage**

```bash
cd /Users/osamamuhammed/frappe_15 && grep -rn "DelayDrainer\|OrphanSweeper" apps/conductor/conductor/ apps/conductor/tests/ apps/conductor/tests_chaos/ 2>&1 | grep -v __pycache__
```

Expected: only `scheduled.py` (defines DelayDrainer) and `sweeper.py` (defines OrphanSweeper) remain. If anywhere else still references them, fix that first.

- [ ] **Step 2: Remove the DelayDrainer class from `scheduled.py`**

Edit `<BENCH>/apps/conductor/conductor/scheduled.py`. Delete:

```python
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

Also remove the now-unused imports `threading`, `time`, `Iterable` and the constant `DRAIN_INTERVAL_SECONDS` — if `drain_due_messages` no longer needs them. Verify by reading the truncated file:

```bash
cd /Users/osamamuhammed/frappe_15 && cat apps/conductor/conductor/scheduled.py
```

Expected: only the module docstring, the imports needed by `scheduled_redis_key` / `schedule_message` / `drain_due_messages`, those three functions, and the logger declaration. No `threading`, no `time` if unused, no `DRAIN_INTERVAL_SECONDS`.

- [ ] **Step 3: Remove the OrphanSweeper class from `sweeper.py`**

Edit `<BENCH>/apps/conductor/conductor/sweeper.py`. Delete:

```python
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

Also remove the now-unused `threading`, `time`, `SWEEP_INTERVAL_SECONDS` if nothing else uses them.

- [ ] **Step 4: Verify imports + tests still pass**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/python -c "from conductor.scheduled import drain_due_messages, schedule_message; from conductor.sweeper import sweep_orphans; print('ok')"
```

Expected: `ok`.

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests/ -q
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor && git add conductor/scheduled.py conductor/sweeper.py && git commit -m "refactor: delete dead DelayDrainer + OrphanSweeper classes; helpers preserved"
```

---

## Task 14: Chaos conftest — spawn scheduler subprocess + tighter teardown + XGROUP DESTROY

**Files:**
- Modify: `<BENCH>/apps/conductor/tests_chaos/conftest.py`

The Phase 1 chaos suite assumes the worker drains the scheduled set. Now that the worker no longer does, every chaos test that exercises retry needs a scheduler subprocess running. Plus, this is where we ship the flake-gate fix from spec §13.3 (XGROUP DESTROY on teardown + tighter subprocess teardown).

- [ ] **Step 1: Replace `tests_chaos/conftest.py`**

Replace the entire contents of `<BENCH>/apps/conductor/tests_chaos/conftest.py` with:

```python
"""Chaos-test fixtures: spawn `bench conductor worker` and `bench conductor
scheduler` as subprocesses so we can kill -9 them mid-job and verify reclaim
+ retry semantics.

Phase 2 changes:
  - autouse `spawn_scheduler` fixture: every chaos test gets a scheduler
    process running by default (because Phase 2 worker no longer drains the
    scheduled set).
  - per-test teardown: `XGROUP DESTROY` every consumer group on every conductor
    stream key before deletion — scrubs PEL stale message-IDs that survived
    `r.delete(key)` (master Phase 2 hand-off §3 #2 hypothesis).
  - tighter subprocess teardown: poll until the process group is empty before
    moving on (master Phase 2 hand-off §3 #1).
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
SUBPROCESS_TEARDOWN_GRACE_SECONDS = 10


@pytest.fixture(scope="session")
def site():
    return DEFAULT_SITE


def _wipe_conductor_state(site_name: str) -> None:
    """XGROUP DESTROY all conductor consumer groups, then delete all
    conductor:{site}:* keys, then delete all DocType rows."""
    import frappe
    from conductor.client import get_redis
    from conductor.config import load_config
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)

    # First: XGROUP DESTROY on every stream key (queues + DLQ). This scrubs
    # the PEL of stale message-IDs even when the stream itself is recreated.
    stream_keys = list(r.keys(f"conductor:{site_name}:stream:*"))
    dlq_keys = list(r.keys(f"conductor:{site_name}:dlq:*"))
    for skey in stream_keys + dlq_keys:
        try:
            for g in (r.xinfo_groups(skey) or []):
                gname = g["name"]
                try:
                    r.xgroup_destroy(skey, gname)
                except Exception:
                    pass
        except Exception:
            # NOGROUP / stream missing — fine.
            pass

    # Then: delete every conductor key for this site.
    for key in r.keys(f"conductor:{site_name}:*"):
        r.delete(key)

    # Then: delete DocType rows in dependency order (DLQ Entry → Job Run → Job).
    for doctype in ("Conductor DLQ Entry", "Conductor Job Run", "Conductor Job"):
        for n in frappe.get_all(doctype, pluck="name"):
            frappe.delete_doc(doctype, n, force=True)
    frappe.db.commit()


@pytest.fixture(scope="session", autouse=True)
def _frappe_init(site):
    """One-time Frappe init for the test process. Wipes any leftover Conductor
    state from prior chaos runs."""
    os.chdir(str(BENCH_ROOT))
    import frappe
    frappe.init(site=site, sites_path=str(BENCH_ROOT / "sites"))
    frappe.connect()
    _wipe_conductor_state(site)
    yield
    frappe.destroy()


@pytest.fixture(autouse=True)
def _wipe_conductor_state_per_test(site):
    """Per-test: wipe Conductor Redis keys + DocType rows BEFORE each test.

    Includes XGROUP DESTROY to scrub PEL state — addresses the residual flake
    hypothesis from master Phase 2 hand-off §3 #2."""
    _wipe_conductor_state(site)
    yield
    # Post-test: same wipe, so no state leaks to the next test even if a
    # subprocess wrote something during teardown.
    _wipe_conductor_state(site)


def _terminate_pgroup(proc: subprocess.Popen, timeout: float = 5.0) -> None:
    """Send SIGTERM to the process group; wait until pgroup is empty (or
    SUBPROCESS_TEARDOWN_GRACE_SECONDS, then SIGKILL)."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return  # already dead
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.killpg(proc.pid, 0)  # raises if no process in group
        except (ProcessLookupError, PermissionError):
            return  # cleanly drained
        time.sleep(0.1)
    # Grace exhausted — escalate.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    # Final wait so the OS reaps the zombie.
    deadline = time.time() + SUBPROCESS_TEARDOWN_GRACE_SECONDS
    while time.time() < deadline:
        try:
            os.killpg(proc.pid, 0)
        except (ProcessLookupError, PermissionError):
            return
        time.sleep(0.1)


@pytest.fixture
def spawn_worker(site):
    """Spawn `bench --site SITE conductor worker` as a subprocess. Tightened
    teardown polls until the process group is empty (Phase 2 fix)."""
    procs: list[subprocess.Popen] = []

    @contextmanager
    def _spawn(*, queue: str = "default", concurrency: int = 1):
        cmd = [
            "bench", "--site", site, "conductor", "worker",
            "--queue", queue, "--concurrency", str(concurrency),
        ]
        env = os.environ.copy()
        env.setdefault("CONDUCTOR_TEST_EXEC_LOCK_TTL_SECONDS", "5")
        env.setdefault("CONDUCTOR_TEST_AUTOCLAIM_IDLE_MS", "8000")
        proc = subprocess.Popen(
            cmd, cwd=str(BENCH_ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
            preexec_fn=os.setsid, env=env,
        )
        procs.append(proc)
        time.sleep(2.0)
        try:
            yield proc
        finally:
            _terminate_pgroup(proc)

    yield _spawn

    for p in procs:
        _terminate_pgroup(p, timeout=0)  # immediate kill on session teardown


@pytest.fixture(autouse=True)
def spawn_scheduler(site):
    """AUTO-spawn a scheduler subprocess for every chaos test.

    Phase 1 chaos tests rely on the worker's DelayDrainer to fire retries.
    Phase 2 lifts that to the scheduler — every chaos test now needs the
    scheduler running by default. Tests that want to exercise scheduler
    death (test_scheduler_handoff) override this fixture with their own
    spawn pattern."""
    cmd = [
        "bench", "--site", site, "conductor", "scheduler",
        "--lock-ttl-seconds=3",
        "--renew-interval-seconds=1",
        "--poll-interval-seconds=1",
    ]
    proc = subprocess.Popen(
        cmd, cwd=str(BENCH_ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
    )
    time.sleep(2.0)
    try:
        yield proc
    finally:
        _terminate_pgroup(proc)


def wait_for_status(job_id: str, expected: str, *, timeout: float = 30.0) -> str:
    """Poll the DB until job reaches `expected` or timeout."""
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

- [ ] **Step 2: Run the Phase 1 chaos suite — should now be green**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests_chaos/ -v 2>&1 | tail -20
```

Expected: 3 passed.

- [ ] **Step 3: Run the 5-run flake gate**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests_chaos/ --count=5 -q 2>&1 | tail -10
```

Expected: 15 passed (3 tests × 5 runs).

If fewer than 15 pass: investigate. The XGROUP DESTROY hypothesis didn't fully resolve the flake. Likely next move: bump `time.sleep(2.0)` after subprocess spawn to 3.0s for slower hosts.

- [ ] **Step 4: Run it again — gate must be green twice in a row**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests_chaos/ --count=5 -q 2>&1 | tail -10
```

Expected: 15 passed again.

- [ ] **Step 5: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor && git add tests_chaos/conftest.py && git commit -m "test(chaos): autouse scheduler subprocess + XGROUP DESTROY teardown + tighter pgroup wait

Three chaos-suite changes that the Phase 2 worker shrink and flake-gate fix
both require:

1. spawn_scheduler is autouse — Phase 2 worker no longer drains the scheduled
   set, so every chaos test that exercises retry needs a scheduler running.
   test_scheduler_handoff (next task) overrides with its own pattern.

2. _wipe_conductor_state now does XGROUP DESTROY on every stream key before
   r.delete(key) — addresses the PEL stale-message-ID hypothesis from the
   master Phase 2 hand-off §3 #2 (residual 5-run flake gate).

3. _terminate_pgroup polls until os.killpg(pid, 0) raises ProcessLookupError
   instead of using a fixed proc.wait(timeout=5) — addresses hand-off §3 #1
   (subprocess takes longer than 5s to fully drain on busy hosts)."
```

---

## Task 15: Chaos test — `test_scheduler_handoff.py` (kill scheduler → peer takes over)

**Files:**
- Create: `<BENCH>/apps/conductor/tests_chaos/test_scheduler_handoff.py`

- [ ] **Step 1: Write the chaos test**

Write to `<BENCH>/apps/conductor/tests_chaos/test_scheduler_handoff.py`:

```python
"""Chaos: kill the scheduler holding the singleton lock; verify a peer takes
over within ~5s (test-time intervals) and resumes the delay loop."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

BENCH_ROOT = Path("/Users/osamamuhammed/frappe_15")


@pytest.fixture
def spawn_scheduler(site):
    """Override the autouse scheduler — this test manages two scheduler
    subprocesses by hand."""
    procs: list[subprocess.Popen] = []

    def _spawn():
        cmd = [
            "bench", "--site", site, "conductor", "scheduler",
            "--lock-ttl-seconds=3",
            "--renew-interval-seconds=1",
            "--poll-interval-seconds=1",
        ]
        proc = subprocess.Popen(
            cmd, cwd=str(BENCH_ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
        )
        procs.append(proc)
        return proc

    yield _spawn

    for p in procs:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _read_lock(site: str) -> str | None:
    import frappe
    from conductor.client import get_redis
    from conductor.config import load_config
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    val = r.get(f"conductor:{site}:scheduler:lock")
    return val.decode() if val else None


def test_scheduler_handoff_takes_over_within_5s(site, spawn_scheduler):
    # Spawn A.
    proc_a = spawn_scheduler()

    # Wait until A holds the lock.
    deadline = time.time() + 8
    holder_a = None
    while time.time() < deadline:
        v = _read_lock(site)
        if v:
            holder_a = v
            break
        time.sleep(0.2)
    assert holder_a is not None, "scheduler-A never acquired lock"

    # Kill -9 A.
    os.killpg(proc_a.pid, signal.SIGKILL)

    # Spawn B.
    proc_b = spawn_scheduler()

    # Wait for the lock value to flip to a different instance_id (≤ 8s with
    # TTL=3 + poll=1 = ≤ 4s; allow margin for OS / Frappe init).
    deadline = time.time() + 8
    holder_b = None
    while time.time() < deadline:
        v = _read_lock(site)
        if v and v != holder_a:
            holder_b = v
            break
        time.sleep(0.2)
    assert holder_b is not None, f"scheduler-B never took over from {holder_a!r}"
    assert holder_b != holder_a


def test_scheduler_handoff_drains_zset_after_takeover(site, spawn_scheduler):
    """After takeover, scheduler-B's delay loop drains a due ZSET entry."""
    import frappe
    from conductor.client import get_redis
    from conductor.config import load_config
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)

    # Ensure 'default' queue exists.
    if not frappe.db.exists("Conductor Queue", "default"):
        frappe.get_doc({
            "doctype": "Conductor Queue",
            "queue_name": "default",
            "enabled": 1,
        }).insert(ignore_permissions=True)
        frappe.db.commit()

    # Spawn A, wait for lock, kill it, spawn B.
    proc_a = spawn_scheduler()
    deadline = time.time() + 8
    while time.time() < deadline:
        if _read_lock(site):
            break
        time.sleep(0.2)
    os.killpg(proc_a.pid, signal.SIGKILL)
    proc_b = spawn_scheduler()

    # Wait for B to acquire.
    deadline = time.time() + 8
    while time.time() < deadline:
        v = _read_lock(site)
        if v:
            break
        time.sleep(0.2)

    # Inject a due ZSET entry.
    encoded = {
        "job_id": "handoff-test-job",
        "site": site,
        "name": "frappe.utils.now",
        "queue": "default",
        "args_b64": "",
        "kwargs_b64": "",
        "attempt": "1",
        "max_attempts": "1",
        "timeout_seconds": "60",
        "enqueued_at": "2026-04-27T12:00:00+00:00",
        "schema_version": "1",
    }
    member = json.dumps(encoded)
    score = int(time.time() * 1000) - 1000
    r.zadd(f"conductor:{site}:scheduled", {member: score})

    # Wait for delay loop to drain it (≤ 2s with 1s tick).
    deadline = time.time() + 5
    drained = False
    while time.time() < deadline:
        if r.zcard(f"conductor:{site}:scheduled") == 0:
            drained = True
            break
        time.sleep(0.2)
    assert drained, "scheduler-B did not drain the due ZSET entry within 5s"

    # And the entry landed on the queue stream.
    entries = r.xrange(f"conductor:{site}:stream:default")
    assert len(entries) >= 1
```

- [ ] **Step 2: Run the new chaos test**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests_chaos/test_scheduler_handoff.py -v 2>&1 | tail -20
```

Expected: 2 passed.

- [ ] **Step 3: Re-run the full chaos suite**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests_chaos/ -v 2>&1 | tail -20
```

Expected: 5 passed (3 Phase 1 + 2 Phase 2).

- [ ] **Step 4: 5-run gate including the new test**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests_chaos/ --count=5 -q 2>&1 | tail -5
```

Expected: 25 passed.

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests_chaos/ --count=5 -q 2>&1 | tail -5
```

Expected: 25 passed (back-to-back gate green).

- [ ] **Step 5: Commit**

```bash
git add tests_chaos/test_scheduler_handoff.py && git commit -m "test(chaos): scheduler handoff — kill -9 holder, peer takes lock and resumes delay loop"
```

---

## Task 16: End-to-end smoke — `* * * * *` schedule produces ≥60 jobs/hr (the master exit criterion)

This is an operational-verification step, not an automated test (an hour of wallclock would dominate CI). We run a 3-minute version locally and extrapolate. Skip if you've already convinced yourself; otherwise document the result.

**Files:** None modified.

- [ ] **Step 1: Make sure no schedulers/workers are running**

```bash
cd /Users/osamamuhammed/frappe_15 && pkill -f "conductor scheduler" 2>/dev/null; pkill -f "conductor worker" 2>/dev/null; sleep 1; ps aux | grep -E "conductor (scheduler|worker)" | grep -v grep
```

Expected: empty output.

- [ ] **Step 2: Wipe state**

```bash
cd /Users/osamamuhammed/frappe_15 && redis-cli -p 11000 -n 2 KEYS "conductor:frappe.localhost:*" | xargs -r redis-cli -p 11000 -n 2 DEL && bench --site frappe.localhost console <<'PYEOF'
import frappe
for dt in ("Conductor DLQ Entry", "Conductor Job Run", "Conductor Job", "Conductor Schedule"):
    for n in frappe.get_all(dt, pluck="name"):
        frappe.delete_doc(dt, n, force=True)
frappe.db.commit()
print("ok")
PYEOF
```

Expected: ends with `ok`.

- [ ] **Step 3: Insert an every-minute schedule pointing at `frappe.utils.now`**

```bash
cd /Users/osamamuhammed/frappe_15 && bench --site frappe.localhost console <<'PYEOF'
import frappe
if not frappe.db.exists("Conductor Queue", "default"):
    frappe.get_doc({"doctype": "Conductor Queue", "queue_name": "default", "enabled": 1}).insert(ignore_permissions=True)
frappe.get_doc({
    "doctype": "Conductor Schedule",
    "schedule_name": "smoke-every-min",
    "enabled": 1,
    "cron_expression": "* * * * *",
    "timezone": "UTC",
    "method": "frappe.utils.now",
    "queue": "default",
}).insert(ignore_permissions=True)
frappe.db.commit()
print("inserted")
PYEOF
```

Expected: ends with `inserted`.

- [ ] **Step 4: Start one scheduler + one worker, observe for 3 minutes**

In one shell:

```bash
cd /Users/osamamuhammed/frappe_15 && bench --site frappe.localhost conductor scheduler &
SCHED_PID=$!
bench --site frappe.localhost conductor worker --queue default --concurrency 2 &
WORK_PID=$!
sleep 200
kill -TERM $SCHED_PID $WORK_PID 2>/dev/null
wait 2>/dev/null
```

- [ ] **Step 5: Count produced jobs and check drift**

```bash
cd /Users/osamamuhammed/frappe_15 && bench --site frappe.localhost console <<'PYEOF'
import frappe
from datetime import timedelta
rows = frappe.db.sql(
    "SELECT enqueued_at FROM `tabConductor Job` WHERE method='frappe.utils.now' "
    "AND enqueued_at IS NOT NULL ORDER BY enqueued_at",
    as_dict=True,
)
print(f"jobs produced: {len(rows)}")
# Compute drift between consecutive enqueues — should be ~60s.
diffs = []
for a, b in zip(rows, rows[1:]):
    delta = (b["enqueued_at"] - a["enqueued_at"]).total_seconds()
    diffs.append(delta)
if diffs:
    avg = sum(diffs) / len(diffs)
    print(f"avg interval between jobs: {avg:.1f}s")
    print(f"max interval: {max(diffs):.1f}s")
    print(f"min interval: {min(diffs):.1f}s")
PYEOF
```

Expected:
- 3 jobs produced (over ~200s of wallclock with 1-min schedule).
- avg interval ~60s.
- max interval ≤ 62s (drift < 2s, per spec §16 exit criterion).

If interval drift exceeds 2s on a quiet host: investigate. The cron tick is 1s, so worst-case drift is 1s + DB round-trip + enqueue latency. If you see 5s drift, run `htop` to check for runaway processes.

- [ ] **Step 6: Tear down**

```bash
cd /Users/osamamuhammed/frappe_15 && pkill -f "conductor scheduler"; pkill -f "conductor worker"; sleep 1; bench --site frappe.localhost console <<'PYEOF'
import frappe
for dt in ("Conductor DLQ Entry", "Conductor Job Run", "Conductor Job", "Conductor Schedule"):
    for n in frappe.get_all(dt, pluck="name"):
        frappe.delete_doc(dt, n, force=True)
frappe.db.commit()
print("cleaned")
PYEOF
```

- [ ] **Step 7: Record the result**

No commit needed for this task. Note the observed `avg interval` and `max interval` numbers; you'll cite them in the Phase 3 hand-off doc (Task 19).

---

## Task 17: `bench conductor doctor` — verify Phase 1 demo still passes

Sanity check that nothing in Phase 2 broke the existing doctor smoke.

**Files:** None modified.

- [ ] **Step 1: Make sure no scheduler / worker is running**

```bash
pkill -f "conductor scheduler" 2>/dev/null; pkill -f "conductor worker" 2>/dev/null; sleep 1
```

- [ ] **Step 2: Run doctor demo**

```bash
cd /Users/osamamuhammed/frappe_15 && bench --site frappe.localhost conductor doctor --demo 2>&1 | tail -20; echo "exit: $?"
```

Expected: ends with `exit: 0`.

- [ ] **Step 3: Run all unit tests + Frappe integration tests one more time**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests/ -q 2>&1 | tail -5
```

Expected: all green; count = 71 (Phase 1) + 8 (cron) + 10 (scheduler_lock) + 3 (lifecycle) + 4 (cron loop) + 4 (delay loop) + 2 (reaper loop) + 2 (sweeper loop) = 104 passed.

```bash
cd /Users/osamamuhammed/frappe_15 && bench --site frappe.localhost run-tests --app conductor 2>&1 | tail -5
```

Expected: 27 + 4 (Conductor Schedule integration) + 1 (run-now) = 32 tests, all passed.

- [ ] **Step 4: Re-run chaos suite as a final acceptance gate**

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests_chaos/ --count=5 -q 2>&1 | tail -5
```

Expected: 25 passed.

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests_chaos/ --count=5 -q 2>&1 | tail -5
```

Expected: 25 passed (twice in a row).

No commit for this task — it's a verification gate.

---

## Task 18: Update `apps/conductor/README.md` — Procfile + scheduler CLI examples

**Files:**
- Modify: `<BENCH>/apps/conductor/README.md`

- [ ] **Step 1: Read the current README**

```bash
cd /Users/osamamuhammed/frappe_15 && wc -l apps/conductor/README.md && head -40 apps/conductor/README.md
```

This will show you the current structure. Operate on whatever is there — append a new section if there isn't a CLI / Procfile one yet.

- [ ] **Step 2: Append a Phase 2 operations section**

Append the following to `<BENCH>/apps/conductor/README.md`:

```markdown
## Operations (Phase 2+)

Conductor has two long-lived processes per site:

- **`bench conductor worker`** — executes jobs from queue streams.
- **`bench conductor scheduler`** — singleton per site; owns the cron loop, retry-delay drain, dead-worker reap, and orphan sweep.

### Procfile

A typical bench Procfile entry alongside the existing services:

```
conductor_worker:    bench --site frappe.localhost conductor worker --queue default --concurrency 4
conductor_scheduler: bench --site frappe.localhost conductor scheduler
```

Multiple `conductor_scheduler` instances are safe — only one holds the lock; the others poll. If the lock holder dies, a peer takes over within ~20s (master Phase 2 exit criterion).

### Schedule admin

```
$ bench --site SITE conductor schedule list
$ bench --site SITE conductor schedule enable <name>
$ bench --site SITE conductor schedule disable <name>
$ bench --site SITE conductor schedule run-now <name>
```

`run-now` fires the schedule's payload immediately via `conductor.enqueue` and updates `last_status` / `last_job` on the schedule row, but does **not** advance `last_run_at` — the cron cadence is unchanged.

### Schedules in the Desk

Create / edit schedules in **Conductor Schedule** under the Conductor module. Required fields: `cron_expression`, `timezone` (defaults to UTC), `method` (dotted path), `queue`. Validation runs the cron expression through `croniter` on save; bad expressions are rejected with a Frappe validation error.

Cron is at-least-once across scheduler crashes — if a scheduler dies between `conductor.enqueue(...)` and the `next_run_at` update, the next holder re-fires the schedule. Make your `method` idempotent if duplicate execution would corrupt state.
```

- [ ] **Step 3: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor && git add README.md && git commit -m "docs(README): Phase 2 operations — scheduler process, Procfile, schedule CLI"
```

---

## Task 19: Phase 3 hand-off notes

Capture the surprises and discoveries from Phase 2 execution so the Phase 3 brainstorm starts from real ground truth (mirrors the Phase 2 hand-off doc that the Phase 1 wrap-up produced).

**Files:**
- Create: `<BENCH>/apps/conductor/docs/superpowers/specs/2026-04-27-conductor-phase3-handoff.md`

- [ ] **Step 1: Write the hand-off doc**

Write to `<BENCH>/apps/conductor/docs/superpowers/specs/2026-04-27-conductor-phase3-handoff.md`:

```markdown
# Phase 3 Hand-off Notes

**Source:** Phase 2 execution discoveries + final-state observations
**Date:** 2026-04-27
**Phase 2 final state:** ~20 commits on `develop` since end-of-Phase-1.
{REPLACE WITH ACTUAL FINAL pytest count} pytest unit tests pass.
{REPLACE WITH ACTUAL FINAL Frappe count} Frappe integration tests pass.
5 chaos tests; 5-run flake gate green twice in a row.

This is **not** a Phase 3 spec. It is the carry-over list that the Phase 3 brainstorm should consume as input. The Phase 3 brainstorm starts from the master design's "Phase 3 — Dashboard" section (§4) plus this list.

## 1. Phase 2 — what shipped

- **`bench conductor scheduler`** — per-site singleton with Redis SET-NX-EX lock + Lua check-and-PEXPIRE renewal + lost-lock fence (exit on lost lock; supervisor restarts → re-poll).
- **Four loops:** delay (1s), cron (1s — deviated from master's 30s hint per Phase 2 spec §6.2), reaper (60s), sweeper (30s).
- **`Conductor Schedule` DocType** — schema per master §6.6, controller validates cron via `croniter` on save, populates `next_run_at`.
- **`bench conductor schedule {list, enable, disable, run-now}`** subcommands.
- **Worker shrink** — `DelayDrainer` and `OrphanSweeper` threads removed; `_heartbeat` resets `status='ALIVE'` to clear STALE-after-recovery.
- **Class deletions** — `conductor.scheduled.DelayDrainer`, `conductor.sweeper.OrphanSweeper`. Both helpers (`drain_due_messages`, `sweep_orphans`) preserved.
- **Chaos suite hardened** — autouse `spawn_scheduler` fixture; `XGROUP DESTROY` on per-test teardown; `_terminate_pgroup` polls until pgroup is empty. 5-run flake gate green.
- **`test_scheduler_handoff.py`** — kill -9 the lock holder, verify peer takes over within 5s with test-time intervals.

## 2. Real bugs / surprises during Phase 2 execution (already fixed)

- _(Fill in as you encounter them. Examples to look for: `frappe.db.set_value` accepting a dict in some Frappe versions but not others; `croniter` quirks around DST transitions; `xgroup_destroy` raising on non-existent stream-group combos; subprocess teardown timing on slow hosts; `pytest-repeat` interaction with autouse fixtures.)_

## 3. Phase 2 residual limitations (accepted, deferred)

- **Cron is at-least-once across scheduler crashes** (Phase 2 spec §15 risk #8). A scheduler crash between `conductor.enqueue` and the `next_run_at` write re-fires the schedule on takeover. Mitigation is operator-side: make schedule methods idempotent.
- **Reaper does not XAUTOCLAIM dead-worker streams.** If the entire fleet dies, no automatic recovery. Documented behaviour, not a Phase 3 priority.
- **No Schedule.idempotency_key field.** `Conductor Schedule` rows can't dedupe at dispatch — would require a master §6.6 schema amendment.

## 4. Phase 3 scope reminder (master §4)

Phase 3 ships:
- A custom Frappe page (Vue 3 SFC) with sections: Overview / Live feed / Job detail / DLQ browser / Schedules / Workers.
- Real-time updates via `frappe.publish_realtime("conductor:*")` events.
- Workflows section is **Phase 5**, not here.

## 5. Phase 3 first-day backlog

1. Inventory existing `frappe.publish_realtime("conductor:*")` events emitted from dispatcher / worker / scheduler. The dashboard subscribes; it cannot work if events aren't being emitted.
2. Decide between Frappe Page (server-rendered Jinja + JS) vs Frappe Page + Vue 3 SFC. Master §4 calls out Vue 3.
3. Confirm OTel trace ID is reachable from `Conductor Job Run` for the "trace" link in Job Detail. (Phase 0 scaffolds OTel; Phase 4 wires the exporter.)

## Change Log

| Date | Change | Author |
|---|---|---|
| 2026-04-27 | Initial Phase 3 hand-off. | osama.m@aau.iq |
```

- [ ] **Step 2: Fill in the bracketed counts**

Run the test commands one last time and replace `{REPLACE WITH ACTUAL FINAL pytest count}` and `{REPLACE WITH ACTUAL FINAL Frappe count}` with real numbers from your tree.

```bash
cd /Users/osamamuhammed/frappe_15 && ./env/bin/pytest apps/conductor/tests/ -q 2>&1 | tail -1
cd /Users/osamamuhammed/frappe_15 && bench --site frappe.localhost run-tests --app conductor 2>&1 | grep -E "Ran [0-9]+"
```

Edit the file to replace the placeholders with the observed numbers.

- [ ] **Step 3: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor && git add docs/superpowers/specs/2026-04-27-conductor-phase3-handoff.md && git commit -m "docs(handoff): Phase 3 hand-off notes — Phase 2 final state + carry-over for Phase 3 brainstorm"
```

---

## Task 20: Final acceptance gate — every Phase 2 exit criterion green

This is a single verification pass. Nothing is committed; if any check fails, that's a real defect to fix before declaring Phase 2 done.

- [ ] **Step 1: Verify each spec §16 exit criterion**

| # | Criterion | How to verify |
|---|---|---|
| 1 | A `* * * * *` schedule runs ≥ 60 times/hr with avg drift < 2s | Task 16 (3-minute version + extrapolation; record numbers) |
| 2 | Killing scheduler → peer picks up within ~20s production | `tests_chaos/test_scheduler_handoff.py` (test-time ≤ 5s; production target ≤ 20s) |
| 3 | All Phase 1 chaos tests still pass | `pytest tests_chaos/ -v` |
| 4 | `pytest tests_chaos --count=5` green twice in a row | Tasks 14 §3 §4 + Task 17 §4 |
| 5 | All unit tests in spec §13.1 are green | `pytest tests/ -q` |
| 6 | `bench conductor doctor --demo` exits 0 | Task 17 §2 |
| 7 | DelayDrainer + OrphanSweeper threads deleted from worker.py | `grep -E "DelayDrainer\|OrphanSweeper" apps/conductor/conductor/worker.py` returns nothing |

- [ ] **Step 2: Run the verification commands and confirm**

```bash
cd /Users/osamamuhammed/frappe_15

# Criterion 7 — text grep.
echo "=== Criterion 7: worker has no DelayDrainer/OrphanSweeper references ==="
grep -E "DelayDrainer|OrphanSweeper" apps/conductor/conductor/worker.py || echo "  → clean"

# Criterion 5 — unit tests.
echo "=== Criterion 5: all unit tests ==="
./env/bin/pytest apps/conductor/tests/ -q 2>&1 | tail -1

# Criterion 3+4 — chaos + 5-run gate.
echo "=== Criterion 3 + 4: chaos suite + 5-run gate (run 1) ==="
./env/bin/pytest apps/conductor/tests_chaos/ --count=5 -q 2>&1 | tail -1
echo "=== Criterion 4: 5-run gate (run 2) ==="
./env/bin/pytest apps/conductor/tests_chaos/ --count=5 -q 2>&1 | tail -1

# Criterion 6 — doctor.
echo "=== Criterion 6: doctor --demo ==="
bench --site frappe.localhost conductor doctor --demo 2>&1 | tail -3
echo "doctor exit: $?"
```

Expected:
- Criterion 7 prints `→ clean`.
- Criterion 5: `104 passed` (or close — exact count depends on the new tests written across tasks).
- Criterion 3 + 4 each: `25 passed` (5 chaos × 5 runs).
- Criterion 6: `doctor exit: 0`.

- [ ] **Step 3: If all criteria pass, post a final summary commit**

No code changes — just an empty commit to mark Phase 2 done in the log.

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor && git commit --allow-empty -m "release: Conductor Phase 2 — Scheduling complete

Exit criteria met:
- Cron schedule * * * * * produces jobs at avg interval ~60s, max ≤ 62s.
- Scheduler kill-and-handoff: peer takes lock within 5s test-time / ~20s prod.
- All Phase 1 chaos tests still pass.
- 5-run flake gate green twice in a row.
- 104 pytest unit tests pass; 32 Frappe integration tests pass.
- bench conductor doctor --demo exits 0.
- DelayDrainer + OrphanSweeper threads removed from worker.

Phase 3 hand-off: docs/superpowers/specs/2026-04-27-conductor-phase3-handoff.md"
```

---

## Self-review checklist

Before declaring this plan finished:

**Spec coverage** (every spec §1–§17 item maps to a task):

| Spec section | Task |
|---|---|
| §1 #1 Conductor Schedule DocType | Task 4 |
| §1 #2 bench conductor scheduler | Task 10 |
| §1 #3 four loops | Tasks 6, 7, 8, 9 |
| §1 #4 bench conductor schedule subcommands | Task 11 |
| §1 #5 singleton lock with renewer + fence | Tasks 3, 5 |
| §1 #6 worker changes | Tasks 12, 13 |
| §1 #7 chaos test extension | Task 15 |
| §1 #8 flake-gate fix | Task 14 |
| §6.1 Delay loop pseudocode | Task 7 |
| §6.2 Cron loop + skip-and-resume | Tasks 6, 2 |
| §6.3 Reaper SQL ordering | Task 8 |
| §6.4 Sweeper delegate | Task 9 |
| §7 Cron module compute_next_run_at | Task 2 |
| §8.3 Schedule controller validate / on_change | Task 4 |
| §9 CLI surface (scheduler + schedule group) | Tasks 10, 11 |
| §10 Worker changes | Task 12 |
| §11 Helper class deletions | Task 13 |
| §13.1 Unit tests | Tasks 2, 3, 5, 6, 7, 8, 9, 4 |
| §13.2 test_scheduler_handoff | Task 15 |
| §13.3 Flake-gate fix | Task 14 |
| §16 Exit criteria | Task 20 |
| §17 Implementation order | Plan task ordering |

No spec section unmapped.

**Type / signature consistency:**
- `compute_next_run_at(cron_expression, tz_name="UTC", base=None)` — defined Task 2, used in Task 4 controller and Task 6 cron loop. Same signature throughout.
- `_decode_kwargs(kwargs_b64)` — defined Task 6, reused Task 11 run-now.
- `start_all_loops` signature — frozen Task 5; Tasks 6–9 each append one thread.
- Lock helpers `acquire`/`renew`/`release` — Task 3 signatures match scheduler.py usage in Task 5.

**Placeholder scan:** no `TBD`, no `TODO`, no `implement later`. Task 19's hand-off doc has `{REPLACE WITH ACTUAL FINAL …}` — those are explicitly meant to be filled in at the end (Task 19 Step 2 instructs).

---

## Plan complete

Saved to `apps/conductor/docs/superpowers/plans/2026-04-27-conductor-phase2-scheduling.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fastest iteration on a 20-task plan.

**2. Inline Execution** — execute tasks in this session, batch checkpoints.

Which approach?
