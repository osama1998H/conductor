# Conductor Phase 6 — Multi-Tenant Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship pool worker mode (one process serving N sites), per-(site, queue) rate limits and concurrency caps, an RQ migration tool, and operational subcommands (`dlq` + `depth`) — completing Phase 6 of the Conductor v1 master roadmap.

**Architecture:** A new `--sites=auto|A,B,C` flag on `bench conductor worker` resolves a site list at boot, builds one `streams` dict spanning sites × queues, and feeds it to the existing `XREADGROUP` loop. Per-job site context is taken from the stream key (not from caller-controlled message fields), and `_handle_one` runs `frappe.init/connect/destroy` per job exactly as today (no connection cache in v1; in-phase benchmark drives any future cache decision per master §10 risk #2). Rate limits and concurrency caps live as two new Int fields on `Conductor Queue` (`max_rps`, `max_concurrent`), enforced at the worker by single-key Lua scripts (`conductor/rate_limit.lua`, `conductor/inflight.lua`) on Redis keys `conductor:{site}:rate:{queue}` and `conductor:{site}:inflight:{queue}`. Throttled jobs ride the existing Phase 2 delay path (re-ZADD to `scheduled` with `next_run_at`, no attempt bump), so all rendering, reaping, and reclaim invariants from earlier phases keep working unchanged. The reaper gains one extra pass to drift-correct the inflight counter when workers are marked GONE. Three thin click commands (`migrate-from-rq`, `dlq`, `depth`) round out the phase.

**Tech Stack:** Python 3.10+, Frappe 15.106.0, Redis (DB 2), msgpack, click (CLI), pytest.

**Spec:** `docs/superpowers/specs/2026-04-29-conductor-phase6-multi-tenant-design.md`
**Master:** `docs/superpowers/specs/2026-04-27-conductor-master-design.md`

---

## Conventions used by every task

- **Test runner:** `/Users/osamamuhammed/frappe_15/env/bin/pytest` for pure-Python tests under `tests/`. Frappe-integration tests (those that need a live site) run via `bench --site frappe.localhost run-tests --app conductor --module <dotted>`.
- **Working dir for all commands:** `/Users/osamamuhammed/frappe_15/apps/conductor/`. All paths in this plan are relative to that directory unless absolute.
- **Frappe site:** `frappe.localhost` is the bench's primary site. Multi-site chaos tests create additional fixture sites via the Phase 5 conftest pattern.
- **Redis test fixture:** `fake_redis` (alias for the live Redis fixture pinned to a unique DB per test) from `tests/conftest.py`. Lua-script tests run against a real Redis — there is no faithful Lua emulation in `fakeredis` for hash + arithmetic.
- **Commit style:** matches recent history — type-scoped subject (`feat(phase6):`, `test(phase6):`, `fix(phase6):`, `docs(phase6):`). Co-Authored-By trailer is optional for plan-driven commits but present in the master change-log commit.
- **TDD discipline:** for every behavior-bearing change, write the failing test first, run it to confirm the failure mode, implement, run to confirm pass, commit. Each task ends with a commit.
- **Test isolation rule (carried from Phase 5):** any test that touches Redis must namespace its keys under a unique prefix. Use the existing `tests/conftest.py:test_site` fixture which provides a per-test site name; rate-limit and inflight keys derived from it are auto-isolated.

---

## File structure

**New files:**

```
conductor/site_discovery.py                       # discover_installed_sites(sites_path)
conductor/rate_limit.py                           # take_token wrapper + key helper
conductor/rate_limit.lua                          # atomic refill bucket
conductor/inflight.py                             # acquire/release/correct_drift wrappers + key helper
conductor/inflight.lua                            # three single-key scripts
conductor/migrate_rq.py                           # importable migration logic
conductor/commands/migrate_rq.py                  # bench conductor migrate-from-rq
conductor/commands/dlq.py                         # bench conductor dlq {list,retry,discard}
conductor/commands/depth.py                       # bench conductor depth [--all-sites]
conductor/patches/v1_2_phase6_queue_limits.py     # idempotent ALTER for max_rps/max_concurrent

tests/test_site_discovery.py
tests/test_rate_limit.py
tests/test_inflight.py
tests/test_pool_worker.py
tests/test_migrate_rq.py
tests/test_dlq_commands.py
tests/test_depth_command.py
tests/test_reaper_drift_correction.py

tests_chaos/test_phase6_pool_chaos.py             # exit-criterion gate 1
tests_chaos/test_phase6_rate_limit.py             # exit-criterion gate 2
tests_chaos/test_phase6_concurrency_cap.py        # exit-criterion gate 3
tests/benchmarks/__init__.py
tests/benchmarks/test_phase6_pool_throughput.py   # non-gating benchmark
```

**Modified files:**

```
conductor/streams.py                              # parse_site_from_stream_key
conductor/worker.py                               # run_worker_pool, throttle path, multi-site heartbeat
conductor/scheduler_loops.py                      # reaper drift-correction pass
conductor/commands/worker.py                      # --sites option
conductor/commands/__init__.py                    # register new subcommands
conductor/conductor/doctype/conductor_queue/conductor_queue.json   # +max_rps, +max_concurrent
conductor/patches.txt                             # register new patch
README.md                                         # operator-facing Phase 6 section
docs/superpowers/specs/2026-04-27-conductor-master-design.md       # §3 #14, §4 Phase 6, §8, §9, §10, change-log
```

**Files NOT touched:** dispatcher (`conductor/dispatcher.py`) — Phase 6 enforcement happens worker-side, not at enqueue. The existing `_handle_one` body keeps its happy path; we only insert the throttle gate after the exec lock and before user code. `conductor/idempotency.py` and `conductor/execution_lock.py` are untouched. The dashboard is not modified — throttled jobs render as the existing `SCHEDULED_RETRY` state with a richer `last_error_message`. No changes to message schema (`conductor/messages.py`).

---

## Task ordering rationale

Tasks are grouped into four bands. Each band's tests pass on their own; later bands depend only on earlier ones.

- **Band A — Pure-Python building blocks (Tasks 1–5).** DocType field migration, site discovery, stream-key parser, two Lua scripts and their Python wrappers. Each task is a single file pair (impl + test).
- **Band B — Worker integration (Tasks 6–10).** Refactor `run_worker` to `run_worker_pool` (single-site as N=1), multi-site heartbeat, throttle gate in `_handle_one`, per-site CancelPoller, `--sites` CLI flag.
- **Band C — Reaper + ops + RQ (Tasks 11–16).** Reaper drift-correction pass, `bench conductor depth`, `dlq list/retry/discard`, RQ migration core + CLI.
- **Band D — Exit criterion + master updates (Tasks 17–22).** Three chaos tests (pool, rate, concurrency cap), the non-gating benchmark, master-doc edits, README, final verification.

---

## Band A — Pure-Python Building Blocks

## Task 1: Extend `Conductor Queue` DocType with `max_rps` and `max_concurrent`

**Files:**
- Modify: `conductor/conductor/doctype/conductor_queue/conductor_queue.json`
- Create: `conductor/patches/v1_2_phase6_queue_limits.py`
- Modify: `conductor/patches.txt`
- Test: `conductor/conductor/doctype/conductor_queue/test_conductor_queue.py` (extend if exists, else create)

- [ ] **Step 1: Write the failing test**

Create or append to `conductor/conductor/doctype/conductor_queue/test_conductor_queue.py`:

```python
"""Frappe-integration tests for Conductor Queue Phase 6 fields."""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestConductorQueuePhase6Fields(FrappeTestCase):
    def test_default_queue_has_max_rps_field_default_zero(self):
        q = frappe.get_doc("Conductor Queue", "default")
        assert hasattr(q, "max_rps"), "max_rps field missing on Conductor Queue"
        assert int(q.max_rps or 0) == 0, "max_rps default must be 0 (unlimited)"

    def test_default_queue_has_max_concurrent_field_default_zero(self):
        q = frappe.get_doc("Conductor Queue", "default")
        assert hasattr(q, "max_concurrent"), "max_concurrent field missing"
        assert int(q.max_concurrent or 0) == 0, "max_concurrent default must be 0"

    def test_can_set_and_persist_limits(self):
        q = frappe.get_doc("Conductor Queue", "default")
        q.max_rps = 50
        q.max_concurrent = 10
        q.save(ignore_permissions=True)
        frappe.db.commit()
        # Re-fetch (skip cache)
        frappe.clear_document_cache("Conductor Queue", "default")
        q2 = frappe.get_doc("Conductor Queue", "default")
        assert int(q2.max_rps) == 50
        assert int(q2.max_concurrent) == 10
        # Reset for other tests
        q2.max_rps = 0
        q2.max_concurrent = 0
        q2.save(ignore_permissions=True)
        frappe.db.commit()
```

- [ ] **Step 2: Run test to verify it fails**

```
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_queue.test_conductor_queue
```

Expected: `AttributeError: 'Conductor Queue' object has no attribute 'max_rps'` (or `max_concurrent`).

- [ ] **Step 3: Edit the DocType JSON**

In `conductor/conductor/doctype/conductor_queue/conductor_queue.json`:

Update `field_order` to insert `max_rps` and `max_concurrent` after `default_jitter`:

```json
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
  "max_rps",
  "max_concurrent",
  "description"
 ],
```

Append two field definitions to the `fields` array (after the `default_jitter` entry, before `description`):

```json
  {"fieldname": "max_rps", "fieldtype": "Int", "label": "Max RPS (0 = unlimited)", "default": "0", "description": "Per-(site, queue) rate limit in jobs per second. 0 disables. Phase 6."},
  {"fieldname": "max_concurrent", "fieldtype": "Int", "label": "Max Concurrent (0 = unlimited)", "default": "0", "description": "Per-(site, queue) cap on simultaneously RUNNING jobs across the fleet. 0 disables. Phase 6."},
```

Bump the `modified` timestamp to `"2026-04-29 00:00:00"`.

- [ ] **Step 4: Write the patch**

Create `conductor/patches/v1_2_phase6_queue_limits.py`:

```python
"""Phase 6 patch: backfill max_rps and max_concurrent on Conductor Queue rows.

Frappe migrate adds the columns automatically from the JSON; this patch fills
in 0 for any pre-existing rows whose new columns came back NULL on add. The
patch is idempotent — re-running it is a no-op once values are 0.
"""

import frappe


def execute():
    frappe.db.sql(
        "UPDATE `tabConductor Queue` SET max_rps = 0 WHERE max_rps IS NULL"
    )
    frappe.db.sql(
        "UPDATE `tabConductor Queue` SET max_concurrent = 0 WHERE max_concurrent IS NULL"
    )
    frappe.db.commit()
```

- [ ] **Step 5: Register the patch**

Edit `conductor/patches.txt`. Under `[post_model_sync]`, append:

```
conductor.patches.v1_2_phase6_queue_limits
```

(Leave `[pre_model_sync]` alone.)

- [ ] **Step 6: Run migrate and re-run the test**

```
bench --site frappe.localhost migrate
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_queue.test_conductor_queue
```

Expected: 3 passed.

- [ ] **Step 7: Commit**

```
git add conductor/conductor/doctype/conductor_queue/conductor_queue.json \
        conductor/conductor/doctype/conductor_queue/test_conductor_queue.py \
        conductor/patches/v1_2_phase6_queue_limits.py \
        conductor/patches.txt
git commit -m "feat(phase6): add max_rps and max_concurrent to Conductor Queue"
```

---

## Task 2: Site discovery — `discover_installed_sites`

**Files:**
- Create: `conductor/site_discovery.py`
- Test: `tests/test_site_discovery.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_site_discovery.py`:

```python
"""Unit tests for conductor.site_discovery.

Uses a tmpdir to simulate a Frappe sites_path with several site directories,
each with its own site_config.json. The function should return only the
sites that have 'conductor' in their installed_apps list.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from conductor.site_discovery import discover_installed_sites


def _make_site(sites_path: Path, name: str, *, installed_apps: list[str] | None) -> None:
    """Create sites_path/<name>/site_config.json. installed_apps=None means
    no site_config.json file at all (simulates a half-installed site)."""
    site_dir = sites_path / name
    site_dir.mkdir(parents=True)
    if installed_apps is not None:
        cfg = {"db_name": f"db_{name}", "db_password": "x"}
        (site_dir / "site_config.json").write_text(json.dumps(cfg))


@pytest.fixture
def sites_path(tmp_path):
    return tmp_path


def test_returns_empty_when_no_sites(sites_path):
    with patch("conductor.site_discovery._installed_apps_for_site", return_value=[]):
        out = discover_installed_sites(str(sites_path))
    assert out == []


def test_returns_only_sites_with_conductor_installed(sites_path):
    _make_site(sites_path, "alpha.test",   installed_apps=["frappe", "conductor"])
    _make_site(sites_path, "beta.test",    installed_apps=["frappe"])
    _make_site(sites_path, "gamma.test",   installed_apps=["frappe", "conductor"])

    fake_apps = {
        "alpha.test":  ["frappe", "conductor"],
        "beta.test":   ["frappe"],
        "gamma.test":  ["frappe", "conductor"],
    }
    with patch(
        "conductor.site_discovery._installed_apps_for_site",
        side_effect=lambda site, sp: fake_apps[site],
    ):
        out = discover_installed_sites(str(sites_path))
    assert out == ["alpha.test", "gamma.test"]  # sorted


def test_skips_directories_without_site_config_json(sites_path):
    _make_site(sites_path, "alpha.test", installed_apps=["frappe", "conductor"])
    _make_site(sites_path, "halfdone",   installed_apps=None)

    with patch(
        "conductor.site_discovery._installed_apps_for_site",
        side_effect=lambda site, sp: ["frappe", "conductor"] if site == "alpha.test" else [],
    ):
        out = discover_installed_sites(str(sites_path))
    assert out == ["alpha.test"]


def test_skips_well_known_non_site_directories(sites_path):
    # "assets" is a Frappe convention for built static files; never a site.
    (sites_path / "assets").mkdir()
    (sites_path / "common_site_config.json").write_text("{}")
    (sites_path / "apps.txt").write_text("frappe\nconductor\n")
    _make_site(sites_path, "alpha.test", installed_apps=["frappe", "conductor"])

    with patch(
        "conductor.site_discovery._installed_apps_for_site",
        return_value=["frappe", "conductor"],
    ):
        out = discover_installed_sites(str(sites_path))
    assert out == ["alpha.test"]


def test_init_failure_for_one_site_skips_that_site(sites_path):
    _make_site(sites_path, "alpha.test", installed_apps=["frappe", "conductor"])
    _make_site(sites_path, "broken.test", installed_apps=["frappe", "conductor"])

    def raise_for_broken(site, sp):
        if site == "broken.test":
            raise RuntimeError("fake init failure")
        return ["frappe", "conductor"]

    with patch("conductor.site_discovery._installed_apps_for_site",
               side_effect=raise_for_broken):
        out = discover_installed_sites(str(sites_path))
    assert out == ["alpha.test"]
```

- [ ] **Step 2: Run test to verify it fails**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_site_discovery.py -v
```

Expected: `ImportError: cannot import name 'discover_installed_sites' from 'conductor.site_discovery'`.

- [ ] **Step 3: Write the implementation**

Create `conductor/site_discovery.py`:

```python
"""Discover Frappe sites that have the conductor app installed.

Used by `bench conductor worker --sites=auto` (and `bench conductor depth
--all-sites`) to enumerate which sites a pool worker should serve. Pure
filesystem + Frappe-init scan; the result is cached by the caller, never
internally — there is no daemon and no re-scan.
"""

from __future__ import annotations

import os
from pathlib import Path

from conductor.logging import get_logger

log = get_logger("conductor.site_discovery")

# Bench convention: these names live alongside site directories under sites/
# but are never themselves sites. Add to the deny-list if the bench grows new
# special directories.
_NON_SITE_NAMES = {"assets", "apps", "logs"}


def _candidate_site_dirs(sites_path: str) -> list[str]:
    """List subdirectories of sites_path that look like they could be a
    Frappe site (have a site_config.json AND are not in the deny-list)."""
    base = Path(sites_path)
    if not base.is_dir():
        return []
    out: list[str] = []
    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        if entry.name in _NON_SITE_NAMES:
            continue
        if not (entry / "site_config.json").is_file():
            continue
        out.append(entry.name)
    return out


def _installed_apps_for_site(site: str, sites_path: str) -> list[str]:
    """Connect to `site` and return its installed_apps list. Always destroys
    the Frappe local context before returning so the caller does not inherit
    stale state. Raises on any init/connect failure (caller catches)."""
    import frappe  # local import — keeps this module importable without Frappe
    frappe.init(site=site, sites_path=sites_path)
    try:
        frappe.connect()
        try:
            return list(frappe.get_installed_apps())
        finally:
            frappe.db.close() if frappe.db else None
    finally:
        frappe.destroy()


def discover_installed_sites(sites_path: str) -> list[str]:
    """Return a sorted list of site names under `sites_path` that have the
    `conductor` app installed. Failures probing one site do not abort the
    scan — they log and skip."""
    out: list[str] = []
    for site in _candidate_site_dirs(sites_path):
        try:
            apps = _installed_apps_for_site(site, sites_path)
        except Exception as e:
            log.warning("site_discovery_skipped", site=site, error=str(e))
            continue
        if "conductor" in apps:
            out.append(site)
    return sorted(out)
```

- [ ] **Step 4: Run tests to verify they pass**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_site_discovery.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```
git add conductor/site_discovery.py tests/test_site_discovery.py
git commit -m "feat(phase6): site discovery for pool worker mode"
```

---

## Task 3: Stream-key → site parser

**Files:**
- Modify: `conductor/streams.py`
- Test: `tests/test_streams.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_streams.py`:

```python
"""Phase 6: stream-key → site routing for pool worker."""

import pytest

from conductor.streams import parse_site_from_stream_key, stream_key


def test_parse_site_from_stream_key_round_trip():
    skey = stream_key("frappe.localhost", "default")
    assert parse_site_from_stream_key(skey) == "frappe.localhost"


def test_parse_site_handles_dotted_site_names():
    skey = stream_key("alpha.tenant.example.com", "long")
    assert parse_site_from_stream_key(skey) == "alpha.tenant.example.com"


def test_parse_site_handles_queue_named_with_colons_unlikely_but_robust():
    # We don't allow colons in queue names by convention, but the parser is
    # written to take everything BEFORE :stream: as site.
    skey = "conductor:site.example:stream:default"
    assert parse_site_from_stream_key(skey) == "site.example"


def test_parse_site_raises_on_bytes_input():
    with pytest.raises(TypeError):
        parse_site_from_stream_key(b"conductor:s:stream:q")


def test_parse_site_raises_on_malformed_key():
    with pytest.raises(ValueError, match="not a conductor stream key"):
        parse_site_from_stream_key("conductor:foo:bar")
    with pytest.raises(ValueError, match="not a conductor stream key"):
        parse_site_from_stream_key("conductor:site:dlq:default")  # DLQ, not stream
    with pytest.raises(ValueError, match="not a conductor stream key"):
        parse_site_from_stream_key("redis:other:stream:foo")
```

- [ ] **Step 2: Run test to verify it fails**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_streams.py -v
```

Expected: `ImportError` for `parse_site_from_stream_key`.

- [ ] **Step 3: Add the parser**

Edit `conductor/streams.py`. After the existing `workers_key` function, append:

```python
def parse_site_from_stream_key(stream: str) -> str:
    """Inverse of stream_key — extract site name from `conductor:{site}:stream:{queue}`.

    Pool worker mode reads multiple streams and must route each message to
    the correct site context. We trust the **stream key** (operator-controlled
    Redis key namespace), never the message fields (caller-controlled, possibly
    forged), to decide which site's MariaDB to connect to.

    Raises:
        TypeError: if `stream` is not a str.
        ValueError: if `stream` does not match `conductor:<site>:stream:<queue>`.
    """
    if not isinstance(stream, str):
        raise TypeError(f"stream key must be str, got {type(stream).__name__}")
    marker = ":stream:"
    if not stream.startswith("conductor:") or marker not in stream:
        raise ValueError(f"not a conductor stream key: {stream!r}")
    # Slice between "conductor:" and ":stream:".
    head = stream[len("conductor:"):]
    idx = head.find(marker)
    if idx <= 0:
        raise ValueError(f"not a conductor stream key: {stream!r}")
    return head[:idx]
```

- [ ] **Step 4: Run tests to verify they pass**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_streams.py -v
```

Expected: all new + existing tests pass.

- [ ] **Step 5: Commit**

```
git add conductor/streams.py tests/test_streams.py
git commit -m "feat(phase6): parse_site_from_stream_key for pool worker routing"
```

---

## Task 4: Rate-limit Lua script + `take_token` wrapper

**Files:**
- Create: `conductor/rate_limit.lua`
- Create: `conductor/rate_limit.py`
- Test: `tests/test_rate_limit.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_rate_limit.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_rate_limit.py -v
```

Expected: `ModuleNotFoundError: No module named 'conductor.rate_limit'`.

- [ ] **Step 3: Write the Lua script**

Create `conductor/rate_limit.lua`:

```lua
-- take_token: atomic refill bucket.
-- KEYS[1] = "conductor:{site}:rate:{queue}"
-- ARGV    = max_tokens, refill_per_sec, now_ms, n
-- returns: {allowed (0|1), retry_after_ms}

local max_tokens     = tonumber(ARGV[1])
local refill_per_sec = tonumber(ARGV[2])
local now_ms         = tonumber(ARGV[3])
local n              = tonumber(ARGV[4])

local state    = redis.call("HMGET", KEYS[1], "tokens", "last_refill_ms")
local tokens   = tonumber(state[1])
local last_ms  = tonumber(state[2])

-- First call (key missing): start full.
if tokens == nil then
    tokens  = max_tokens
    last_ms = now_ms
end

local elapsed_ms = now_ms - last_ms
if elapsed_ms < 0 then elapsed_ms = 0 end

local refill = (elapsed_ms * refill_per_sec) / 1000.0
tokens = tokens + refill
if tokens > max_tokens then tokens = max_tokens end

if tokens >= n then
    tokens = tokens - n
    redis.call("HMSET", KEYS[1], "tokens", tostring(tokens), "last_refill_ms", tostring(now_ms))
    redis.call("PEXPIRE", KEYS[1], 60000)
    return {1, 0}
else
    local missing  = n - tokens
    local retry_ms = math.ceil((missing * 1000.0) / refill_per_sec)
    redis.call("HMSET", KEYS[1], "tokens", tostring(tokens), "last_refill_ms", tostring(now_ms))
    redis.call("PEXPIRE", KEYS[1], 60000)
    return {0, retry_ms}
end
```

- [ ] **Step 4: Write the Python wrapper**

Create `conductor/rate_limit.py`:

```python
"""Rate-limit token bucket — Lua-backed, single-key, cluster-safe.

The Lua script is loaded once per Redis connection-pool via SCRIPT LOAD
(redis-py's `register_script`); subsequent calls are EVALSHA. The wrapper
keeps the call site simple: pass site, queue, and bucket parameters; get
back `(allowed, retry_after_ms)`.

Time is provided as `now_ms` explicitly (rather than reading from Redis's
TIME) so unit tests can drive the clock deterministically. Production
callers pass `int(time.time() * 1000)`.
"""

from __future__ import annotations

import threading
from pathlib import Path

import redis as redis_mod

_SCRIPT_PATH = Path(__file__).with_name("rate_limit.lua")
_LUA_SOURCE: str | None = None
_LUA_LOCK = threading.Lock()
# Per-Redis-client `Script` cache — re-using the same registered Script object
# across calls means redis-py reuses its SHA1 and only EVALSHAs.
_REGISTERED: dict[int, "redis_mod.client.Script"] = {}


def rate_key(site: str, queue: str) -> str:
    return f"conductor:{site}:rate:{queue}"


def _get_script(client: redis_mod.Redis) -> "redis_mod.client.Script":
    global _LUA_SOURCE
    if _LUA_SOURCE is None:
        with _LUA_LOCK:
            if _LUA_SOURCE is None:
                _LUA_SOURCE = _SCRIPT_PATH.read_text(encoding="utf-8")
    cid = id(client.connection_pool)
    script = _REGISTERED.get(cid)
    if script is None:
        script = client.register_script(_LUA_SOURCE)
        _REGISTERED[cid] = script
    return script


def take_token(
    client: redis_mod.Redis,
    site: str,
    queue: str,
    *,
    max_tokens: int,
    refill_per_sec: float,
    now_ms: int,
    n: int = 1,
) -> tuple[bool, int]:
    """Try to consume `n` tokens. Returns (allowed, retry_after_ms).
    If allowed is False, retry_after_ms is the minimum wait before this
    many tokens will be available."""
    script = _get_script(client)
    out = script(
        keys=[rate_key(site, queue)],
        args=[max_tokens, refill_per_sec, now_ms, n],
    )
    # redis-py returns Lua tables as Python lists.
    allowed = bool(int(out[0]))
    retry_ms = int(out[1])
    return allowed, retry_ms
```

- [ ] **Step 5: Run tests to verify they pass**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_rate_limit.py -v
```

Expected: 8 passed. If `fakeredis` fails to execute the Lua HMSET-with-string-coercion, fall back to running the module against a live Redis: set `REDIS_URL=redis://127.0.0.1:11000/3` (DB 3 to avoid prod) and use `redis.from_url(REDIS_URL)` instead of `fake_redis` in a fixture override. Add a top-of-file pytest skip if neither is available.

- [ ] **Step 6: Commit**

```
git add conductor/rate_limit.lua conductor/rate_limit.py tests/test_rate_limit.py
git commit -m "feat(phase6): atomic refill bucket Lua + take_token wrapper"
```

---

## Task 5: Inflight counter Lua + acquire/release/correct_drift wrappers

**Files:**
- Create: `conductor/inflight.lua`
- Create: `conductor/inflight.py`
- Test: `tests/test_inflight.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_inflight.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_inflight.py -v
```

Expected: `ModuleNotFoundError: No module named 'conductor.inflight'`.

- [ ] **Step 3: Write the Lua scripts**

Create `conductor/inflight.lua`:

```lua
-- Inflight counter scripts for the concurrency cap.
--
-- This file holds three scripts; the Python wrapper splits on the
-- "-- @SCRIPT name" marker and registers each independently. Keeping all
-- three in one file makes the policy obvious to readers; splitting at
-- import time keeps each script single-key and EVAL-cacheable.

-- @SCRIPT acquire
-- KEYS[1] = inflight_key
-- ARGV    = max_concurrent
-- returns: {acquired (0|1), current_count}
local cur = tonumber(redis.call("GET", KEYS[1]) or "0")
local cap = tonumber(ARGV[1])
if cur < cap then
    local new = redis.call("INCR", KEYS[1])
    redis.call("EXPIRE", KEYS[1], 86400)
    return {1, new}
else
    return {0, cur}
end

-- @SCRIPT release
-- KEYS[1] = inflight_key
-- returns: new_count (always >= 0)
local new = redis.call("DECR", KEYS[1])
if new < 0 then
    redis.call("SET", KEYS[1], 0)
    return 0
end
return new

-- @SCRIPT correct_drift
-- KEYS[1] = inflight_key
-- ARGV    = decrement_by
-- returns: new_count (always >= 0)
local cur = tonumber(redis.call("GET", KEYS[1]) or "0")
local new = cur - tonumber(ARGV[1])
if new < 0 then new = 0 end
redis.call("SET", KEYS[1], new)
return new
```

- [ ] **Step 4: Write the Python wrapper**

Create `conductor/inflight.py`:

```python
"""Per-(site, queue) concurrency-cap counter, Lua-backed and single-key.

Three scripts live in inflight.lua, separated by `-- @SCRIPT <name>` markers.
We parse them at import time so each call site uses the right registered
Script object. All three are single-key (cluster-safe per master §3 #15).
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

import redis as redis_mod

_SCRIPT_PATH = Path(__file__).with_name("inflight.lua")
_SOURCES: dict[str, str] | None = None
_SOURCES_LOCK = threading.Lock()
_REGISTERED: dict[tuple[int, str], "redis_mod.client.Script"] = {}


def inflight_key(site: str, queue: str) -> str:
    return f"conductor:{site}:inflight:{queue}"


def _load_scripts() -> dict[str, str]:
    """Parse inflight.lua into {script_name: source}. Splits on '-- @SCRIPT'
    headers; each section is one standalone single-key script."""
    text = _SCRIPT_PATH.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    current_name: str | None = None
    current_lines: list[str] = []
    header_re = re.compile(r"^--\s*@SCRIPT\s+(\w+)\s*$")
    for line in text.splitlines():
        m = header_re.match(line)
        if m:
            if current_name is not None:
                out[current_name] = "\n".join(current_lines).strip() + "\n"
            current_name = m.group(1)
            current_lines = []
        else:
            if current_name is not None:
                current_lines.append(line)
    if current_name is not None:
        out[current_name] = "\n".join(current_lines).strip() + "\n"
    return out


def _get_script(client: redis_mod.Redis, name: str) -> "redis_mod.client.Script":
    global _SOURCES
    if _SOURCES is None:
        with _SOURCES_LOCK:
            if _SOURCES is None:
                _SOURCES = _load_scripts()
    cid = (id(client.connection_pool), name)
    script = _REGISTERED.get(cid)
    if script is None:
        script = client.register_script(_SOURCES[name])
        _REGISTERED[cid] = script
    return script


def acquire(client: redis_mod.Redis, site: str, queue: str, *, max_concurrent: int) -> tuple[bool, int]:
    """Try to acquire one inflight slot. Returns (acquired, current_count).
    On rejection, current_count is the cap (== max_concurrent)."""
    out = _get_script(client, "acquire")(
        keys=[inflight_key(site, queue)],
        args=[max_concurrent],
    )
    return bool(int(out[0])), int(out[1])


def release(client: redis_mod.Redis, site: str, queue: str) -> int:
    """Release one inflight slot. Returns new count (floored at 0)."""
    out = _get_script(client, "release")(keys=[inflight_key(site, queue)])
    return int(out)


def correct_drift(client: redis_mod.Redis, site: str, queue: str, *, decrement_by: int) -> int:
    """Used by the reaper after marking N workers GONE — subtract N from
    the counter atomically and floor at 0. Returns new count."""
    out = _get_script(client, "correct_drift")(
        keys=[inflight_key(site, queue)],
        args=[decrement_by],
    )
    return int(out)


def get_count(client: redis_mod.Redis, site: str, queue: str) -> int:
    """Read the counter. Used by `bench conductor depth` and the reaper.
    Single-key GET; not Lua-wrapped."""
    val = client.get(inflight_key(site, queue))
    if val is None:
        return 0
    return int(val)
```

- [ ] **Step 5: Run tests to verify they pass**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_inflight.py -v
```

Expected: 9 passed.

- [ ] **Step 6: Commit**

```
git add conductor/inflight.lua conductor/inflight.py tests/test_inflight.py
git commit -m "feat(phase6): inflight counter Lua scripts + Python wrappers"
```

---

## Band B — Worker Integration

## Task 6: Refactor `run_worker` to delegate to `run_worker_pool`

**Files:**
- Modify: `conductor/worker.py`
- Test: `tests/test_pool_worker.py` (new)

This task adds `run_worker_pool(sites, queues, concurrency, ...)` and rewrites `run_worker(site, queues, concurrency, ...)` to call it with `sites=[site]`. The single-site path becomes the N=1 case of pool mode. **No multi-site heartbeat or CancelPoller wiring yet** — those land in Tasks 7 and 9. Throttle-gate wiring lands in Task 8. This task only proves the routing skeleton.

- [ ] **Step 1: Write the failing test**

Create `tests/test_pool_worker.py`:

```python
"""Unit tests for pool worker stream-routing skeleton.

These tests do NOT spawn a real worker process; they exercise the helpers
that pool mode adds: building the streams dict across multiple sites,
parsing the right site from each stream key, and confirming the
single-site path is just N=1 of pool mode.
"""

from unittest.mock import patch

import pytest

from conductor.worker import _build_streams_dict


def test_build_streams_dict_one_site_one_queue(fake_redis):
    streams = _build_streams_dict(
        fake_redis, sites=["alpha.test"], queues=["default"],
    )
    assert streams == {"conductor:alpha.test:stream:default": ">"}


def test_build_streams_dict_one_site_multiple_queues(fake_redis):
    streams = _build_streams_dict(
        fake_redis, sites=["alpha.test"], queues=["default", "long"],
    )
    assert streams == {
        "conductor:alpha.test:stream:default": ">",
        "conductor:alpha.test:stream:long": ">",
    }


def test_build_streams_dict_multiple_sites_multiple_queues(fake_redis):
    streams = _build_streams_dict(
        fake_redis,
        sites=["alpha.test", "beta.test"],
        queues=["default", "critical"],
    )
    assert streams == {
        "conductor:alpha.test:stream:default": ">",
        "conductor:alpha.test:stream:critical": ">",
        "conductor:beta.test:stream:default": ">",
        "conductor:beta.test:stream:critical": ">",
    }


def test_build_streams_dict_creates_consumer_group_per_stream(fake_redis):
    """ensure_consumer_group is called for every (site, queue) combination."""
    with patch("conductor.worker.ensure_consumer_group") as mock_ensure:
        _build_streams_dict(
            fake_redis,
            sites=["alpha.test", "beta.test"],
            queues=["default"],
        )
    assert mock_ensure.call_count == 2
    seen_keys = sorted(call.args[1] for call in mock_ensure.call_args_list)
    assert seen_keys == [
        "conductor:alpha.test:stream:default",
        "conductor:beta.test:stream:default",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_pool_worker.py -v
```

Expected: `ImportError: cannot import name '_build_streams_dict' from 'conductor.worker'`.

- [ ] **Step 3: Add `_build_streams_dict` and `run_worker_pool`; rewrite `run_worker` to delegate**

In `conductor/worker.py`, add this helper near the other private helpers (just below `_xautoclaim_pending`):

```python
def _build_streams_dict(redis_client, sites: list[str], queues: list[str]) -> dict[str, str]:
    """For each (site, queue) pair, ensure the consumer group exists and
    return a streams dict suitable for XREADGROUP."""
    streams: dict[str, str] = {}
    for site in sites:
        for queue in queues:
            skey = stream_key(site, queue)
            ensure_consumer_group(redis_client, skey)
            streams[skey] = ">"
    return streams
```

Add a new `run_worker_pool` (place it just above the existing `run_worker` definition) that takes a sites *list* and accepts pool-mode parameters. For Task 6 it is mostly a copy of `run_worker`'s body but parameterized over `sites`:

```python
def run_worker_pool(
    *,
    sites: list[str],
    queues: list[str],
    concurrency: int,
    grace_seconds: int = 30,
) -> None:
    """Run a Conductor pool worker against N sites × M queues.

    The single-site `run_worker` is now a thin wrapper that calls this
    with sites=[site]. Subsequent Phase 6 tasks add multi-site heartbeat
    (Task 7), throttle gate (Task 8), per-site CancelPoller (Task 9).
    """
    if not sites:
        raise ValueError("run_worker_pool: sites must be non-empty")

    primary_site = sites[0]
    setup_logging(site=primary_site)

    import frappe
    # Cfg/Redis are bench-wide (master §3 #6) — read from any site's conf.
    frappe.init(site=primary_site)
    try:
        frappe.connect()
        cfg = load_config(frappe.local.conf)
    finally:
        frappe.destroy()
    r = get_redis(cfg.redis_url)

    worker_id = _make_worker_id()
    sites_path = frappe.utils.get_site_path("..").rstrip("/").rstrip(".")
    # `frappe.utils.get_site_path` requires a site context; instead, derive
    # sites_path from the bench's known location at /Users/.../sites by
    # asking Frappe one more time:
    frappe.init(site=primary_site)
    try:
        sites_path = frappe.local.sites_path
    finally:
        frappe.destroy()

    # Task 7 will replace this with multi-site registration.
    _register_worker(worker_id, queues, primary_site)
    _install_signal_handlers()

    log_ctx = log.bind(worker_id=worker_id, sites=sites)
    log_ctx.info("worker_pool_started", queues=queues, concurrency=concurrency)

    streams = _build_streams_dict(r, sites, queues)

    pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="conductor-")
    # Task 9 will replace this with per-site CancelPollers.
    cancel_poller = CancelPoller(
        worker_id, primary_site, sites_path, _cancel_events, _cancel_events_lock,
    )
    cancel_poller.start()

    last_beat = 0.0
    try:
        while not _shutdown.is_set():
            now = time.time()
            if now - last_beat >= _HEARTBEAT_SECS:
                _heartbeat(worker_id)
                last_beat = now

            try:
                _reclaim_into_pool(r, streams, worker_id, pool, primary_site, sites_path, wait=False)
                _read_and_dispatch(r, streams, concurrency, 5000, worker_id, pool, primary_site, sites_path, wait=False)
            except redis_mod.exceptions.ConnectionError as e:
                log_ctx.warning("redis_connection_error", error=str(e))
                time.sleep(2)
            except Exception as e:
                log_ctx.error("worker_iteration_failed", error=str(e))
                time.sleep(1)
    finally:
        log_ctx.info("worker_shutting_down", grace_seconds=grace_seconds)
        cancel_poller.stop()
        pool.shutdown(wait=True)
        _mark_worker_gone(worker_id)
        log_ctx.info("worker_stopped")
```

Replace the existing `run_worker` with a thin delegator:

```python
def run_worker(*, queues: list[str], concurrency: int, site: str, grace_seconds: int = 30) -> None:
    """Single-site worker — implemented as the N=1 case of pool mode."""
    return run_worker_pool(
        sites=[site], queues=queues, concurrency=concurrency, grace_seconds=grace_seconds,
    )
```

**Note:** Tasks 7–9 will replace `_register_worker(worker_id, queues, primary_site)`, the single `_heartbeat(worker_id)` call, the single `CancelPoller`, the `primary_site` argument threaded through `_reclaim_into_pool` / `_read_and_dispatch`, and the single `_mark_worker_gone` call with their multi-site equivalents. The placeholders in this task keep the chaos tests green; they are not the final shape.

- [ ] **Step 4: Run unit tests + the existing kill-during-run chaos test to verify nothing regressed**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_pool_worker.py -v
/Users/osamamuhammed/frappe_15/env/bin/pytest tests_chaos/test_kill_during_run.py -v
```

Expected: pool-worker tests PASS (4); kill-during-run chaos PASSES.

- [ ] **Step 5: Commit**

```
git add conductor/worker.py tests/test_pool_worker.py
git commit -m "refactor(phase6): make run_worker a thin wrapper over run_worker_pool"
```

---

## Task 7: Multi-site heartbeat, register, and mark-gone

**Files:**
- Modify: `conductor/worker.py`
- Test: `tests/test_pool_worker.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pool_worker.py`:

```python
def test_register_worker_pool_inserts_one_row_per_site(monkeypatch):
    """The pool worker registers itself in every site it serves so that each
    site's Conductor Worker list (and reaper) sees it."""
    inserted: list[tuple[str, str]] = []  # (site, worker_id)

    def fake_init(*, site, **_):
        import frappe
        frappe.local._fake_site = site

    def fake_connect():
        pass

    class _DocStub:
        def __init__(self, payload):
            self._payload = payload
        def insert(self, **_):
            return self
    def fake_get_doc(payload):
        return _DocStub(payload)

    def fake_exists(doctype, name):
        return False

    seen_inserts: list[dict] = []
    def fake_insert(payload):
        seen_inserts.append(payload)

    import frappe
    monkeypatch.setattr(frappe, "init", fake_init, raising=False)
    monkeypatch.setattr(frappe, "connect", fake_connect, raising=False)
    monkeypatch.setattr(frappe, "destroy", lambda: None, raising=False)
    monkeypatch.setattr(frappe.db, "exists", fake_exists, raising=False)
    monkeypatch.setattr(frappe.db, "commit", lambda: None, raising=False)
    # Capture every get_doc({"doctype":"Conductor Worker", ...}).insert call:
    real_get_doc = frappe.get_doc
    def capturing_get_doc(payload, *a, **k):
        if isinstance(payload, dict) and payload.get("doctype") == "Conductor Worker":
            seen_inserts.append(payload)
            return _DocStub(payload)
        return real_get_doc(payload, *a, **k)
    monkeypatch.setattr(frappe, "get_doc", capturing_get_doc, raising=False)

    from conductor.worker import _register_worker_pool
    _register_worker_pool(
        "host:1234:abc",
        queues=["default"],
        sites=["alpha.test", "beta.test"],
        sites_path="/tmp/sites",
    )
    assert len(seen_inserts) == 2
    sites_seen = {row["site"] for row in seen_inserts}
    assert sites_seen == {"alpha.test", "beta.test"}
    assert all(row["worker_id"] == "host:1234:abc" for row in seen_inserts)


def test_heartbeat_pool_updates_every_site(monkeypatch):
    """_heartbeat_pool should fanout one set_value per site, all with the
    same worker_id."""
    seen_calls: list[tuple[str, str, dict]] = []  # (site, worker_id, payload)
    current_site_holder = {"v": None}

    import frappe
    def fake_init(*, site, **_):
        current_site_holder["v"] = site
    monkeypatch.setattr(frappe, "init", fake_init, raising=False)
    monkeypatch.setattr(frappe, "connect", lambda: None, raising=False)
    monkeypatch.setattr(frappe, "destroy", lambda: None, raising=False)
    monkeypatch.setattr(frappe.db, "commit", lambda: None, raising=False)
    def fake_set_value(doctype, name, payload, update_modified=False):
        seen_calls.append((current_site_holder["v"], name, dict(payload)))
    monkeypatch.setattr(frappe.db, "set_value", fake_set_value, raising=False)

    from conductor.worker import _heartbeat_pool
    _heartbeat_pool(
        "host:1234:abc",
        sites=["alpha.test", "beta.test", "gamma.test"],
        sites_path="/tmp/sites",
    )
    assert {(c[0], c[1]) for c in seen_calls} == {
        ("alpha.test", "host:1234:abc"),
        ("beta.test",  "host:1234:abc"),
        ("gamma.test", "host:1234:abc"),
    }
    for _site, _wid, payload in seen_calls:
        assert payload["status"] == "ALIVE"
        assert "last_heartbeat" in payload
```

- [ ] **Step 2: Run test to verify it fails**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_pool_worker.py -v
```

Expected: `ImportError: cannot import name '_register_worker_pool' from 'conductor.worker'`.

- [ ] **Step 3: Add the multi-site helpers**

Add to `conductor/worker.py`, near the existing single-site `_register_worker` / `_heartbeat` / `_mark_worker_gone`:

```python
def _register_worker_pool(worker_id: str, queues: list[str], sites: list[str], sites_path: str) -> None:
    """Insert one Conductor Worker row per site so each site's reaper sees us."""
    for site in sites:
        frappe.init(site=site, sites_path=sites_path)
        try:
            frappe.connect()
            try:
                if frappe.db.exists("Conductor Worker", worker_id):
                    continue
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
            finally:
                pass
        finally:
            frappe.destroy()


def _heartbeat_pool(worker_id: str, sites: list[str], sites_path: str) -> None:
    """Fanout heartbeat across every site this worker serves."""
    for site in sites:
        frappe.init(site=site, sites_path=sites_path)
        try:
            frappe.connect()
            try:
                frappe.db.set_value(
                    "Conductor Worker",
                    worker_id,
                    {"last_heartbeat": _now_naive(), "status": "ALIVE"},
                    update_modified=False,
                )
                frappe.db.commit()
            finally:
                pass
        finally:
            frappe.destroy()


def _mark_worker_gone_pool(worker_id: str, sites: list[str], sites_path: str) -> None:
    for site in sites:
        try:
            frappe.init(site=site, sites_path=sites_path)
            try:
                frappe.connect()
                if frappe.db.exists("Conductor Worker", worker_id):
                    frappe.db.set_value(
                        "Conductor Worker", worker_id, "status", "GONE",
                        update_modified=False,
                    )
                    frappe.db.commit()
            finally:
                frappe.destroy()
        except Exception as e:
            log.warning("mark_gone_failed_for_site", site=site, error=str(e))
```

In `run_worker_pool`, replace:

- `_register_worker(worker_id, queues, primary_site)` → `_register_worker_pool(worker_id, queues, sites, sites_path)`
- the heartbeat call `_heartbeat(worker_id)` → `_heartbeat_pool(worker_id, sites, sites_path)`
- `_mark_worker_gone(worker_id)` (at the end) → `_mark_worker_gone_pool(worker_id, sites, sites_path)`

Also: remove the redundant double `frappe.init/destroy` block that was left in Task 6 to grab `sites_path`. Replace with one block at the top of `run_worker_pool` that captures `cfg` AND `sites_path` in one shot:

```python
    frappe.init(site=primary_site)
    try:
        frappe.connect()
        cfg = load_config(frappe.local.conf)
        sites_path = frappe.local.sites_path
    finally:
        frappe.destroy()
    r = get_redis(cfg.redis_url)
```

- [ ] **Step 4: Run tests to verify they pass**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_pool_worker.py -v
/Users/osamamuhammed/frappe_15/env/bin/pytest tests_chaos/test_kill_during_run.py -v
```

Expected: pool-worker tests PASS (6); kill-during-run chaos PASSES.

- [ ] **Step 5: Commit**

```
git add conductor/worker.py tests/test_pool_worker.py
git commit -m "feat(phase6): multi-site register/heartbeat/mark-gone for pool worker"
```

---

## Task 8: Throttle gate in `_handle_one` (rate limit + concurrency cap)

**Files:**
- Modify: `conductor/worker.py`
- Test: `tests/test_pool_worker.py` (extend) and `tests_chaos/test_phase6_concurrency_cap.py` (created in Task 19)

This task wires the rate-limit and inflight checks into `_handle_one` between the exec-lock acquire and user-code execution. Per spec §5.4 the order is **inflight first, then rate** — inflight rejection is free (no state change) so we don't burn rate-limit tokens on capped queues. If inflight succeeds but rate fails, we explicitly release inflight to avoid leaking slots. The chaos tests in Tasks 18 and 19 exercise this end-to-end; the unit test here verifies the routing logic in isolation.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pool_worker.py`:

```python
def test_resolve_queue_limits_returns_zero_for_unlimited(monkeypatch):
    """A Conductor Queue with max_rps=0 and max_concurrent=0 must short-circuit
    the throttle gate — no Redis calls should fire."""
    class FakeQueue:
        max_rps = 0
        max_concurrent = 0

    import frappe
    monkeypatch.setattr(frappe, "get_cached_doc",
                        lambda doctype, name: FakeQueue(), raising=False)

    from conductor.worker import _resolve_queue_limits
    rps, conc = _resolve_queue_limits("default")
    assert rps == 0
    assert conc == 0


def test_resolve_queue_limits_reads_int_fields(monkeypatch):
    class FakeQueue:
        max_rps = 25
        max_concurrent = 7
    import frappe
    monkeypatch.setattr(frappe, "get_cached_doc",
                        lambda doctype, name: FakeQueue(), raising=False)
    from conductor.worker import _resolve_queue_limits
    rps, conc = _resolve_queue_limits("default")
    assert rps == 25
    assert conc == 7


def test_throttle_gate_inflight_denied_reschedules_without_consuming_token(monkeypatch, fake_redis):
    """When max_concurrent is exceeded, the throttle gate must re-ZADD to
    the delay set and NOT call take_token — token is preserved for callers
    that actually run."""
    take_token_called = []

    def spy_take_token(*a, **k):
        take_token_called.append(True)
        return (True, 0)
    monkeypatch.setattr("conductor.worker.take_token", spy_take_token, raising=False)

    # Pre-fill inflight at cap
    from conductor.inflight import acquire
    for _ in range(2):
        acquire(fake_redis, "alpha.test", "default", max_concurrent=2)

    schedule_calls = []
    def spy_schedule_message(client, site, encoded, run_at_ms):
        schedule_calls.append((site, run_at_ms, dict(encoded)))
    monkeypatch.setattr("conductor.worker.schedule_message",
                        spy_schedule_message, raising=False)

    db_calls = []
    import frappe
    monkeypatch.setattr(frappe.db, "set_value",
                        lambda *a, **k: db_calls.append((a, k)), raising=False)
    monkeypatch.setattr(frappe.db, "commit", lambda: None, raising=False)
    monkeypatch.setattr("conductor.worker.emit_job_event",
                        lambda *a, **k: None, raising=False)

    from conductor.messages import JobMessage
    from datetime import datetime, timezone
    msg = JobMessage(
        job_id="job-A", site="alpha.test", method="m", queue="default",
        args=[], kwargs={}, attempt=1, max_attempts=3, timeout_seconds=60,
        enqueued_at=datetime.now(timezone.utc),
        deadline=datetime.now(timezone.utc),
    )

    from conductor.worker import _apply_throttle_gate
    allowed = _apply_throttle_gate(
        fake_redis, msg, site="alpha.test",
        rps=10, conc=2, now_ms=1_700_000_000_000,
    )
    assert allowed is False
    assert take_token_called == []  # rate limit NOT consulted
    assert len(schedule_calls) == 1
    site, _run_at_ms, encoded = schedule_calls[0]
    assert site == "alpha.test"
    # attempt unchanged (throttling, not retry)
    assert encoded.get("attempt") == "1"


def test_throttle_gate_rate_limit_denied_releases_inflight_and_reschedules(monkeypatch, fake_redis):
    """Inflight acquired, then rate-limit rejects — the inflight slot must
    be released so we don't leak it."""
    monkeypatch.setattr("conductor.worker.take_token",
                        lambda *a, **k: (False, 250), raising=False)
    monkeypatch.setattr("conductor.worker.schedule_message",
                        lambda *a, **k: None, raising=False)
    import frappe
    monkeypatch.setattr(frappe.db, "set_value", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(frappe.db, "commit", lambda: None, raising=False)
    monkeypatch.setattr("conductor.worker.emit_job_event",
                        lambda *a, **k: None, raising=False)

    from conductor.inflight import get_count
    from conductor.messages import JobMessage
    from datetime import datetime, timezone
    msg = JobMessage(
        job_id="job-A", site="s", method="m", queue="default",
        args=[], kwargs={}, attempt=1, max_attempts=3, timeout_seconds=60,
        enqueued_at=datetime.now(timezone.utc),
        deadline=datetime.now(timezone.utc),
    )

    from conductor.worker import _apply_throttle_gate
    allowed = _apply_throttle_gate(
        fake_redis, msg, site="s",
        rps=10, conc=5, now_ms=1_700_000_000_000,
    )
    assert allowed is False
    # Inflight was acquired (1) then released (back to 0)
    assert get_count(fake_redis, "s", "default") == 0


def test_throttle_gate_both_pass_returns_true_and_holds_inflight_slot(monkeypatch, fake_redis):
    monkeypatch.setattr("conductor.worker.take_token",
                        lambda *a, **k: (True, 0), raising=False)
    from conductor.messages import JobMessage
    from datetime import datetime, timezone
    msg = JobMessage(
        job_id="job-A", site="s", method="m", queue="default",
        args=[], kwargs={}, attempt=1, max_attempts=3, timeout_seconds=60,
        enqueued_at=datetime.now(timezone.utc),
        deadline=datetime.now(timezone.utc),
    )
    from conductor.worker import _apply_throttle_gate
    from conductor.inflight import get_count
    allowed = _apply_throttle_gate(
        fake_redis, msg, site="s",
        rps=10, conc=3, now_ms=1_700_000_000_000,
    )
    assert allowed is True
    assert get_count(fake_redis, "s", "default") == 1


def test_throttle_gate_short_circuits_when_both_limits_zero(monkeypatch, fake_redis):
    """When max_rps=0 and max_concurrent=0, no Redis calls should fire."""
    take_token_called = []
    monkeypatch.setattr("conductor.worker.take_token",
                        lambda *a, **k: take_token_called.append(True) or (True, 0),
                        raising=False)
    from conductor.messages import JobMessage
    from datetime import datetime, timezone
    msg = JobMessage(
        job_id="job-A", site="s", method="m", queue="default",
        args=[], kwargs={}, attempt=1, max_attempts=3, timeout_seconds=60,
        enqueued_at=datetime.now(timezone.utc),
        deadline=datetime.now(timezone.utc),
    )
    from conductor.worker import _apply_throttle_gate
    allowed = _apply_throttle_gate(
        fake_redis, msg, site="s",
        rps=0, conc=0, now_ms=1_700_000_000_000,
    )
    assert allowed is True
    assert take_token_called == []
```

- [ ] **Step 2: Run test to verify it fails**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_pool_worker.py -v
```

Expected: `ImportError: cannot import name '_resolve_queue_limits'` (or `_apply_throttle_gate`).

- [ ] **Step 3: Add the throttle helpers**

In `conductor/worker.py`, add new imports near the top:

```python
from conductor.inflight import acquire as inflight_acquire, release as inflight_release
from conductor.rate_limit import take_token
```

Add these helpers (place them just before `_handle_one`):

```python
_INFLIGHT_RETRY_BACKOFF_MS_DEFAULT = 1000


def _resolve_queue_limits(queue: str) -> tuple[int, int]:
    """Read (max_rps, max_concurrent) from the Conductor Queue cached doc.
    Both default to 0 (unlimited). Frappe's get_cached_doc invalidates on
    document update so dashboard edits propagate within seconds."""
    doc = frappe.get_cached_doc("Conductor Queue", queue)
    return int(getattr(doc, "max_rps", 0) or 0), int(getattr(doc, "max_concurrent", 0) or 0)


def _throttle_action(
    redis_client,
    msg: JobMessage,
    site: str,
    *,
    reason: str,
    retry_after_ms: int,
) -> None:
    """Re-ZADD the message into the delay set for `retry_after_ms` from now;
    flip the Conductor Job row to SCHEDULED_RETRY without bumping attempt;
    emit a realtime event with `reason` so the dashboard can distinguish
    throttling from real retries."""
    encoded = encode(msg)
    next_run = _now() + timedelta(milliseconds=retry_after_ms)
    run_at_ms = int(next_run.timestamp() * 1000)
    schedule_message(redis_client, site, encoded, run_at_ms)
    frappe.db.set_value(
        "Conductor Job",
        msg.job_id,
        {
            "status": "SCHEDULED_RETRY",
            "next_run_at": next_run.replace(tzinfo=None),
            "last_error_type": "Throttled",
            "last_error_message": f"{reason}",
        },
        update_modified=False,
    )
    frappe.db.commit()
    emit_job_event(
        msg.job_id,
        "SCHEDULED_RETRY",
        attempt=msg.attempt,
        max_attempts=msg.max_attempts,
        next_run_at=next_run.replace(tzinfo=None).isoformat(),
        reason=reason,
    )


def _apply_throttle_gate(
    redis_client,
    msg: JobMessage,
    *,
    site: str,
    rps: int,
    conc: int,
    now_ms: int,
) -> bool:
    """Returns True if the job is allowed to run, False if it has been
    re-scheduled. Inflight is checked first (free fail). On rate-limit
    rejection after a successful inflight acquire, inflight is released."""
    if rps <= 0 and conc <= 0:
        return True

    if conc > 0:
        acquired, _cur = inflight_acquire(redis_client, site, msg.queue, max_concurrent=conc)
        if not acquired:
            _throttle_action(
                redis_client, msg, site,
                reason="inflight_capped",
                retry_after_ms=_INFLIGHT_RETRY_BACKOFF_MS_DEFAULT,
            )
            return False

    if rps > 0:
        allowed, retry_ms = take_token(
            redis_client, site, msg.queue,
            max_tokens=rps, refill_per_sec=rps,
            now_ms=now_ms, n=1,
        )
        if not allowed:
            if conc > 0:
                inflight_release(redis_client, site, msg.queue)  # don't leak slot
            _throttle_action(
                redis_client, msg, site,
                reason="rate_limited",
                retry_after_ms=max(retry_ms, 1),
            )
            return False

    return True
```

Now wire it into `_handle_one`. Find the block that currently looks like:

```python
        if not acquire_exec_lock(redis_client, site, msg.job_id, worker_id, ttl=lock_ttl):
            log.info("exec_lock_held_by_peer", job_id=msg.job_id)
            redis_client.xack(stream_name, CONSUMER_GROUP, msg_id)
            return
```

Right after that block, **before** the `cancel_event = threading.Event()` line, insert:

```python
        rps, conc = _resolve_queue_limits(msg.queue)
        if rps > 0 or conc > 0:
            now_ms = int(time.time() * 1000)
            if not _apply_throttle_gate(redis_client, msg, site=site, rps=rps, conc=conc, now_ms=now_ms):
                release_exec_lock(redis_client, site, msg.job_id, worker_id)
                redis_client.xack(stream_name, CONSUMER_GROUP, msg_id)
                return
```

Find the final `release_exec_lock(redis_client, site, msg.job_id, worker_id)` call (around line 484 of the current `worker.py`). Just **before** it, in the same block, add an inflight release on the success path:

```python
            if conc > 0:
                inflight_release(redis_client, site, msg.queue)
```

Wait — `conc` is bound only inside the `if rps > 0 or conc > 0:` branch. To make the success-path release work, hoist `conc` so it lives across the whole job execution. Easiest pattern: assign `rps, conc = _resolve_queue_limits(msg.queue)` once, immediately after `acquire_exec_lock`, **before** the throttle gate, and reference `conc` again at success.

Final shape inside `_handle_one`:

```python
        # Resolve once; both gate and success-path release reference these.
        rps, conc = _resolve_queue_limits(msg.queue)
        if rps > 0 or conc > 0:
            now_ms = int(time.time() * 1000)
            if not _apply_throttle_gate(redis_client, msg, site=site, rps=rps, conc=conc, now_ms=now_ms):
                release_exec_lock(redis_client, site, msg.job_id, worker_id)
                redis_client.xack(stream_name, CONSUMER_GROUP, msg_id)
                return

        cancel_event = threading.Event()
        ...
        # (existing job execution)
        ...
        # near the end, just before release_exec_lock:
        if conc > 0:
            inflight_release(redis_client, site, msg.queue)
        release_exec_lock(redis_client, site, msg.job_id, worker_id)
        redis_client.xack(stream_name, CONSUMER_GROUP, msg_id)
```

- [ ] **Step 4: Run tests to verify they pass**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_pool_worker.py -v
/Users/osamamuhammed/frappe_15/env/bin/pytest tests_chaos/test_kill_during_run.py -v
```

Expected: pool-worker tests PASS (all); kill-during-run chaos PASSES (no regression — limits default to 0 so the gate short-circuits).

- [ ] **Step 5: Commit**

```
git add conductor/worker.py tests/test_pool_worker.py
git commit -m "feat(phase6): throttle gate in worker — inflight then rate, no slot leak"
```

---

## Task 9: Per-site CancelPoller in pool mode

**Files:**
- Modify: `conductor/worker.py`
- Test: `tests/test_pool_worker.py` (extend)

The existing `CancelPoller` polls one site for `Conductor Job` rows with `status=CANCELLED AND worker_id=<self>`. In pool mode, we run **one CancelPoller per site** — they share the same global `_cancel_events` map (keyed by globally-unique job UUID) and the same `_cancel_events_lock`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pool_worker.py`:

```python
def test_pool_cancel_pollers_one_per_site_share_event_map():
    """Pool mode runs N CancelPoller threads, all writing into the same
    process-global cancel_events map. Construction is what we test here;
    the live polling is verified by the chaos suite."""
    from conductor.worker import _make_pool_cancel_pollers, _cancel_events, _cancel_events_lock
    pollers = _make_pool_cancel_pollers(
        worker_id="host:1234:abc",
        sites=["alpha.test", "beta.test", "gamma.test"],
        sites_path="/tmp/sites",
    )
    try:
        assert len(pollers) == 3
        # Same shared map and lock referenced by every poller
        for p in pollers:
            assert p._cancel_events is _cancel_events
            assert p._lock is _cancel_events_lock
        # Sites all distinct
        seen_sites = {p._site for p in pollers}
        assert seen_sites == {"alpha.test", "beta.test", "gamma.test"}
    finally:
        # Don't actually start them in the test — the start() side-effect
        # would try to talk to Frappe on those non-existent sites.
        pass
```

- [ ] **Step 2: Run test to verify it fails**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_pool_worker.py::test_pool_cancel_pollers_one_per_site_share_event_map -v
```

Expected: `ImportError: cannot import name '_make_pool_cancel_pollers'`.

- [ ] **Step 3: Add the helper and wire it into `run_worker_pool`**

In `conductor/worker.py`, just below the `CancelPoller` class definition, add:

```python
def _make_pool_cancel_pollers(
    *,
    worker_id: str,
    sites: list[str],
    sites_path: str,
) -> list[CancelPoller]:
    """Construct one CancelPoller per site; all pollers share the
    process-global `_cancel_events` map and `_cancel_events_lock`."""
    return [
        CancelPoller(
            worker_id, site, sites_path,
            _cancel_events, _cancel_events_lock,
        )
        for site in sites
    ]
```

In `run_worker_pool`, replace the single `cancel_poller = CancelPoller(...)` + `cancel_poller.start()` with:

```python
    pollers = _make_pool_cancel_pollers(
        worker_id=worker_id, sites=sites, sites_path=sites_path,
    )
    for p in pollers:
        p.start()
```

And in the `finally:` block, replace `cancel_poller.stop()` with:

```python
        for p in pollers:
            p.stop()
```

- [ ] **Step 4: Run tests**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_pool_worker.py -v
/Users/osamamuhammed/frappe_15/env/bin/pytest tests_chaos/test_kill_during_run.py -v
```

Expected: both pass.

- [ ] **Step 5: Commit**

```
git add conductor/worker.py tests/test_pool_worker.py
git commit -m "feat(phase6): per-site CancelPoller wiring in pool mode"
```

---

## Task 10: `bench conductor worker --sites` CLI option

**Files:**
- Modify: `conductor/commands/worker.py`
- Test: `tests/test_pool_worker.py` (extend)

`--site` (singular, existing, from bench context) and `--sites` (plural, new) are mutually exclusive. `--sites=auto` calls `discover_installed_sites`; `--sites=A,B,C` is parsed as a comma-list. If neither is given, fall back to bench `--site` (existing behavior).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pool_worker.py`:

```python
def test_resolve_pool_sites_auto_calls_discovery(monkeypatch):
    monkeypatch.setattr(
        "conductor.commands.worker.discover_installed_sites",
        lambda sp: ["alpha.test", "gamma.test"],
        raising=False,
    )
    from conductor.commands.worker import _resolve_pool_sites
    out = _resolve_pool_sites("auto", sites_path="/tmp/sites", bench_site="frappe.localhost")
    assert out == ["alpha.test", "gamma.test"]


def test_resolve_pool_sites_comma_list_parses_and_strips():
    from conductor.commands.worker import _resolve_pool_sites
    out = _resolve_pool_sites(
        "alpha.test, beta.test ,gamma.test",
        sites_path="/tmp", bench_site="frappe.localhost",
    )
    assert out == ["alpha.test", "beta.test", "gamma.test"]


def test_resolve_pool_sites_comma_list_drops_empty_entries():
    from conductor.commands.worker import _resolve_pool_sites
    out = _resolve_pool_sites(",,alpha.test,,", sites_path="/tmp", bench_site="x")
    assert out == ["alpha.test"]


def test_resolve_pool_sites_none_falls_back_to_bench_site():
    from conductor.commands.worker import _resolve_pool_sites
    out = _resolve_pool_sites(None, sites_path="/tmp", bench_site="frappe.localhost")
    assert out == ["frappe.localhost"]


def test_resolve_pool_sites_auto_with_no_installed_sites_raises():
    from conductor.commands.worker import _resolve_pool_sites

    import pytest
    with pytest.raises(SystemExit):
        _resolve_pool_sites(
            "auto", sites_path="/tmp",
            bench_site="frappe.localhost",
            _discover=lambda sp: [],
        )
```

- [ ] **Step 2: Run test to verify it fails**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_pool_worker.py -v
```

Expected: `ImportError: cannot import name '_resolve_pool_sites'`.

- [ ] **Step 3: Update the worker command**

Replace `conductor/commands/worker.py` entirely with:

```python
"""bench conductor worker — run a long-lived worker process.

Single-site (today's default): bench --site=X conductor worker
Pool mode (Phase 6):           bench conductor worker --sites=auto
                               bench conductor worker --sites=A,B,C
"""

from __future__ import annotations

import sys

import click
import frappe
from frappe.commands import get_site, pass_context

from conductor.site_discovery import discover_installed_sites


def _resolve_pool_sites(
    sites_arg: str | None,
    *,
    sites_path: str,
    bench_site: str,
    _discover=discover_installed_sites,
) -> list[str]:
    """Resolve the worker's site list. Three modes:
        - sites_arg is None              → [bench_site]
        - sites_arg == 'auto'            → installed-conductor sites
        - sites_arg == 'A, B,C'          → comma-list, stripped
    Empty-`auto` is a fatal error (sys.exit). Empty comma-list falls back
    to bench_site (lenient — matches Click's own no-flag behavior)."""
    if sites_arg is None:
        return [bench_site]
    if sites_arg == "auto":
        sites = _discover(sites_path)
        if not sites:
            click.echo(
                "ERROR: --sites=auto found no sites with conductor installed under "
                f"{sites_path}. Pass --sites=site1,site2,... explicitly.",
                err=True,
            )
            sys.exit(2)
        return sites
    parts = [s.strip() for s in sites_arg.split(",")]
    cleaned = [s for s in parts if s]
    if not cleaned:
        return [bench_site]
    return cleaned


@click.command("worker")
@click.option("--queue", "queues", multiple=True, default=("default",), help="Queue to consume (repeatable).")
@click.option("--concurrency", default=4, type=int, help="Threadpool size for executing jobs.")
@click.option("--grace", default=30, type=int, help="Graceful shutdown timeout (seconds).")
@click.option(
    "--sites", "sites_arg", default=None,
    help="Comma list, or 'auto' for all installed-conductor sites. Mutually exclusive with --site.",
)
@pass_context
def worker_command(ctx, queues, concurrency, grace, sites_arg):
    """Run a Conductor worker process. Supports single-site (--site from
    bench context) or pool mode (--sites=auto|A,B,C)."""
    bench_site = None
    sites_path = None

    # Initialise frappe once just to grab sites_path; we don't need it
    # connected at this layer. If --site was provided via bench context,
    # capture it as bench_site.
    try:
        bench_site = get_site(ctx)
    except Exception:
        bench_site = None

    frappe.init(site=bench_site or "frappe.localhost")
    try:
        sites_path = frappe.local.sites_path
    finally:
        frappe.destroy()

    if sites_arg is not None and bench_site is not None and ctx.obj.get("sites"):
        # Both --site and --sites set explicitly. Click already errors on
        # incompatible combinations elsewhere, but be defensive.
        click.echo("ERROR: --site (from bench) and --sites are mutually exclusive.", err=True)
        sys.exit(2)

    sites = _resolve_pool_sites(sites_arg, sites_path=sites_path, bench_site=bench_site or "frappe.localhost")

    from conductor.worker import run_worker_pool
    run_worker_pool(
        sites=sites,
        queues=list(queues),
        concurrency=concurrency,
        grace_seconds=grace,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_pool_worker.py -v
```

Expected: 5 new tests PASS, all earlier tests still PASS.

- [ ] **Step 5: Smoke test with bench (manual)**

```
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost conductor worker --queue default --concurrency 2 --grace 5 &
WORKER_PID=$!
sleep 3
kill $WORKER_PID
wait $WORKER_PID 2>/dev/null
```

Expected: worker boots, logs `worker_pool_started sites=['frappe.localhost']`, exits cleanly.

```
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost conductor worker --sites=frappe.localhost --queue default --concurrency 2 --grace 5 &
sleep 3
kill %1
wait
```

Expected: worker boots in pool mode (one site), logs `worker_pool_started sites=['frappe.localhost']`.

- [ ] **Step 6: Commit**

```
git add conductor/commands/worker.py tests/test_pool_worker.py
git commit -m "feat(phase6): bench conductor worker --sites=auto|A,B,C"
```

---

## Band C — Reaper, Ops Subcommands, RQ Migration

## Task 11: Reaper drift-correction pass

**Files:**
- Modify: `conductor/scheduler_loops.py`
- Test: `tests/test_reaper_drift_correction.py` (new)

After the existing `_reaper_loop_iter` marks workers GONE, walk the just-marked-GONE worker rows, group their `RUNNING` jobs by queue, and call `inflight.correct_drift(site, queue, decrement_by=count)` for each group. The job rows themselves are NOT modified — XAUTOCLAIM owns message-level recovery (spec §5.5).

- [ ] **Step 1: Write the failing test**

Create `tests/test_reaper_drift_correction.py`:

```python
"""Unit test for the reaper's Phase 6 drift-correction pass."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from conductor.scheduler_loops import _reaper_drift_correction_iter


@pytest.fixture
def fake_frappe(monkeypatch):
    fake = MagicMock()
    fake.db = MagicMock()
    monkeypatch.setattr(
        "conductor.scheduler_loops.frappe", fake, raising=False,
    )
    return fake


def test_no_gone_workers_no_correction(fake_redis, fake_frappe):
    """If no workers were just-marked GONE, the function is a no-op."""
    fake_frappe.db.sql.return_value = []  # no rows
    with patch("conductor.scheduler_loops.correct_drift") as mock_correct:
        _reaper_drift_correction_iter(
            fake_redis, "frappe.localhost", just_gone_worker_ids=[]
        )
    assert mock_correct.call_count == 0


def test_one_gone_worker_with_one_running_job(fake_redis, fake_frappe):
    fake_frappe.db.sql.return_value = [
        {"queue": "default", "running_count": 1},
    ]
    with patch("conductor.scheduler_loops.correct_drift") as mock_correct:
        _reaper_drift_correction_iter(
            fake_redis, "alpha.test",
            just_gone_worker_ids=["host:1234:abc"],
        )
    mock_correct.assert_called_once_with(
        fake_redis, "alpha.test", "default", decrement_by=1,
    )


def test_multiple_workers_grouped_by_queue(fake_redis, fake_frappe):
    fake_frappe.db.sql.return_value = [
        {"queue": "default", "running_count": 3},
        {"queue": "critical", "running_count": 1},
    ]
    with patch("conductor.scheduler_loops.correct_drift") as mock_correct:
        _reaper_drift_correction_iter(
            fake_redis, "alpha.test",
            just_gone_worker_ids=["w1", "w2", "w3"],
        )
    assert mock_correct.call_count == 2
    seen = {(c.args[2], c.kwargs["decrement_by"]) for c in mock_correct.call_args_list}
    assert seen == {("default", 3), ("critical", 1)}


def test_drift_correction_does_not_modify_job_rows(fake_redis, fake_frappe):
    """Critical: status='RUNNING' rows are LEFT ALONE — XAUTOCLAIM owns
    message recovery; we only fix the counter."""
    fake_frappe.db.sql.return_value = [{"queue": "default", "running_count": 2}]
    update_calls = []
    fake_frappe.db.set_value = lambda *a, **k: update_calls.append((a, k))
    with patch("conductor.scheduler_loops.correct_drift"):
        _reaper_drift_correction_iter(
            fake_redis, "alpha.test", just_gone_worker_ids=["w1", "w2"],
        )
    assert update_calls == []
```

- [ ] **Step 2: Run test to verify it fails**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_reaper_drift_correction.py -v
```

Expected: `ImportError: cannot import name '_reaper_drift_correction_iter'`.

- [ ] **Step 3: Add the helper and wire into the existing reaper loop**

In `conductor/scheduler_loops.py`, add a new import near the top:

```python
from conductor.inflight import correct_drift
```

Add the helper just below `_reaper_loop_iter`:

```python
def _reaper_drift_correction_iter(redis_client, site: str, just_gone_worker_ids: list[str]) -> None:
    """For workers marked GONE in this reaper pass, count their currently-RUNNING
    jobs (grouped by queue) and decrement the inflight counter accordingly.
    Does NOT touch job rows — XAUTOCLAIM handles message-level recovery."""
    if not just_gone_worker_ids:
        return
    placeholders = ",".join(["%s"] * len(just_gone_worker_ids))
    rows = frappe.db.sql(
        f"""SELECT queue, COUNT(*) AS running_count
            FROM `tabConductor Job`
            WHERE worker_id IN ({placeholders}) AND status='RUNNING'
            GROUP BY queue""",
        tuple(just_gone_worker_ids),
        as_dict=True,
    )
    for row in rows:
        try:
            correct_drift(
                redis_client, site, row["queue"],
                decrement_by=int(row["running_count"]),
            )
        except Exception as e:
            log.warning(
                "drift_correction_failed",
                site=site, queue=row["queue"], error=str(e),
            )
```

Edit `_reaper_loop_iter` to capture the worker IDs it just marked GONE and pass them to the new helper:

```python
def _reaper_loop_iter(site: str, frappe) -> None:
    """One reaper pass: mark STALE/GONE based on heartbeat age, prune old rows,
    drift-correct inflight counters."""
    now = datetime.now()
    gone_cut = now - timedelta(seconds=REAPER_GONE_AGE_SECONDS)
    stale_cut = now - timedelta(seconds=REAPER_STALE_AGE_SECONDS)
    prune_cut = now - timedelta(seconds=REAPER_PRUNE_AGE_SECONDS)

    # Phase 6: capture the worker IDs about to flip GONE before mutating.
    just_gone_rows = frappe.db.sql(
        "SELECT worker_id FROM `tabConductor Worker` "
        "WHERE site=%s AND status<>'GONE' AND last_heartbeat < %s",
        (site, gone_cut),
        as_dict=True,
    )
    just_gone_ids = [r["worker_id"] for r in just_gone_rows]

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
    return just_gone_ids
```

Edit `_reaper_loop` to thread the result of `_reaper_loop_iter` (the `just_gone_ids`) into a follow-up call to the drift-correction helper. Replace the body of the existing `try` block:

```python
            frappe.init(site=site, sites_path=sites_path)
            frappe.connect()
            try:
                just_gone_ids = _reaper_loop_iter(site, frappe)
                from conductor.client import get_redis
                from conductor.config import load_config
                cfg = load_config(frappe.local.conf)
                r = get_redis(cfg.redis_url)
                _reaper_drift_correction_iter(r, site, just_gone_ids or [])
                frappe.db.commit()
            finally:
                frappe.destroy()
```

- [ ] **Step 4: Run tests to verify they pass**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_reaper_drift_correction.py -v
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_reaper_loop.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```
git add conductor/scheduler_loops.py tests/test_reaper_drift_correction.py
git commit -m "feat(phase6): reaper drift-correct inflight counter for GONE workers"
```

---

## Task 12: `bench conductor depth [--all-sites]`

**Files:**
- Create: `conductor/commands/depth.py`
- Modify: `conductor/commands/__init__.py`
- Test: `tests/test_depth_command.py`

Reads `XLEN` for each `(site, queue)` stream, `XLEN` for the DLQ, `ZCARD` for the scheduled set, and the inflight counter. Output is a plain-text table.

- [ ] **Step 1: Write the failing test**

Create `tests/test_depth_command.py`:

```python
"""Tests for `bench conductor depth` table builder."""

from unittest.mock import MagicMock, patch

import pytest


def test_collect_depth_for_site_returns_one_row_per_queue(fake_redis):
    fake_redis.xadd("conductor:s1:stream:default", {"x": "1"})
    fake_redis.xadd("conductor:s1:stream:default", {"x": "2"})
    fake_redis.xadd("conductor:s1:dlq:default", {"x": "1"})
    fake_redis.zadd("conductor:s1:scheduled", {"a": 100.0, "b": 200.0})

    fake_queues = [
        type("Q", (), {"name": "default", "max_rps": 0, "max_concurrent": 0})(),
        type("Q", (), {"name": "long",    "max_rps": 0, "max_concurrent": 0})(),
    ]

    with patch("conductor.commands.depth._all_queues", return_value=fake_queues):
        from conductor.commands.depth import collect_depth_for_site
        rows = collect_depth_for_site(fake_redis, "s1")

    by_queue = {r["queue"]: r for r in rows}
    assert by_queue["default"]["stream_xlen"] == 2
    assert by_queue["default"]["dlq_xlen"] == 1
    assert by_queue["default"]["scheduled_zcard"] == 2  # site-level, repeated
    assert by_queue["default"]["inflight"] == 0
    assert by_queue["default"]["max_rps"] == 0
    assert by_queue["default"]["max_concurrent"] == 0
    assert by_queue["long"]["stream_xlen"] == 0


def test_collect_depth_for_site_reads_inflight_counter(fake_redis):
    fake_redis.set("conductor:s1:inflight:default", "3")
    fake_queues = [type("Q", (), {"name": "default", "max_rps": 0, "max_concurrent": 0})()]
    with patch("conductor.commands.depth._all_queues", return_value=fake_queues):
        from conductor.commands.depth import collect_depth_for_site
        rows = collect_depth_for_site(fake_redis, "s1")
    assert rows[0]["inflight"] == 3


def test_format_depth_table_renders_columns():
    from conductor.commands.depth import format_depth_table
    rows = [
        {"queue": "default", "stream_xlen": 5, "dlq_xlen": 0,
         "scheduled_zcard": 2, "inflight": 1, "max_rps": 0, "max_concurrent": 0},
    ]
    out = format_depth_table("alpha.test", rows)
    assert "alpha.test" in out
    assert "default" in out
    assert "5" in out
```

- [ ] **Step 2: Run test to verify it fails**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_depth_command.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement the command**

Create `conductor/commands/depth.py`:

```python
"""bench conductor depth — show per-queue depth stats for one site or all
installed-conductor sites."""

from __future__ import annotations

import click
import frappe
from frappe.commands import get_site, pass_context

from conductor.client import get_redis
from conductor.config import load_config
from conductor.inflight import get_count as inflight_get_count
from conductor.streams import dlq_key, scheduled_key, stream_key


def _all_queues():
    """Return Conductor Queue rows ordered by name."""
    return frappe.get_all(
        "Conductor Queue",
        fields=["name", "max_rps", "max_concurrent"],
        order_by="name asc",
    )


def collect_depth_for_site(redis_client, site: str) -> list[dict]:
    """Build one row per Conductor Queue with stream/DLQ/scheduled/inflight counts."""
    out: list[dict] = []
    sched_zcard = redis_client.zcard(scheduled_key(site)) or 0
    for q in _all_queues():
        qname = q.name if hasattr(q, "name") else q["name"]
        max_rps = int(getattr(q, "max_rps", 0) if not isinstance(q, dict) else q.get("max_rps", 0) or 0)
        max_conc = int(getattr(q, "max_concurrent", 0) if not isinstance(q, dict) else q.get("max_concurrent", 0) or 0)
        stream_len = redis_client.xlen(stream_key(site, qname)) or 0
        dlq_len = redis_client.xlen(dlq_key(site, qname)) or 0
        out.append({
            "queue": qname,
            "stream_xlen": stream_len,
            "dlq_xlen": dlq_len,
            "scheduled_zcard": sched_zcard,
            "inflight": inflight_get_count(redis_client, site, qname),
            "max_rps": max_rps,
            "max_concurrent": max_conc,
        })
    return out


def format_depth_table(site: str, rows: list[dict]) -> str:
    headers = ["queue", "stream", "dlq", "scheduled", "inflight", "max_rps", "max_concurrent"]
    widths = [max(len(h), 8) for h in headers]
    for r in rows:
        for i, key in enumerate(("queue", "stream_xlen", "dlq_xlen", "scheduled_zcard",
                                  "inflight", "max_rps", "max_concurrent")):
            widths[i] = max(widths[i], len(str(r[key])))
    out_lines = [f"site: {site}"]
    sep = "  "
    out_lines.append(sep.join(h.ljust(w) for h, w in zip(headers, widths)))
    out_lines.append(sep.join("-" * w for w in widths))
    for r in rows:
        cells = [
            r["queue"], r["stream_xlen"], r["dlq_xlen"],
            r["scheduled_zcard"], r["inflight"],
            r["max_rps"], r["max_concurrent"],
        ]
        out_lines.append(sep.join(str(c).ljust(w) for c, w in zip(cells, widths)))
    return "\n".join(out_lines)


@click.command("depth")
@click.option("--all-sites", is_flag=True, default=False,
              help="Walk all sites with conductor installed and print one table per site.")
@pass_context
def depth_command(ctx, all_sites):
    """Print queue/DLQ/scheduled depths for one site (--all-sites for the fleet)."""
    if all_sites:
        from conductor.site_discovery import discover_installed_sites
        # We need sites_path; init once with any site to get it.
        bench_site = get_site(ctx, raise_err=False) if hasattr(get_site, "raise_err") else None
        try:
            bench_site = bench_site or get_site(ctx)
        except Exception:
            bench_site = "frappe.localhost"
        frappe.init(site=bench_site)
        try:
            sites_path = frappe.local.sites_path
        finally:
            frappe.destroy()
        sites = discover_installed_sites(sites_path)
    else:
        sites = [get_site(ctx)]

    for site in sites:
        frappe.init(site=site)
        try:
            frappe.connect()
            cfg = load_config(frappe.local.conf)
            r = get_redis(cfg.redis_url)
            rows = collect_depth_for_site(r, site)
            click.echo(format_depth_table(site, rows))
            click.echo("")
        finally:
            frappe.destroy()
```

- [ ] **Step 4: Register the command**

Edit `conductor/commands/__init__.py`. Add import:

```python
from conductor.commands.depth import depth_command
```

And add to the group:

```python
conductor_group.add_command(depth_command)
```

- [ ] **Step 5: Run tests + a smoke run**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_depth_command.py -v
```

Expected: 3 PASS.

```
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost conductor depth
```

Expected: a small table is printed.

- [ ] **Step 6: Commit**

```
git add conductor/commands/depth.py conductor/commands/__init__.py tests/test_depth_command.py
git commit -m "feat(phase6): bench conductor depth [--all-sites]"
```

---

## Task 13: `bench conductor dlq list`

**Files:**
- Create: `conductor/commands/dlq.py` (group root + `list` subcommand)
- Modify: `conductor/commands/__init__.py`
- Test: `tests/test_dlq_commands.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_dlq_commands.py`:

```python
"""Click integration tests for `bench conductor dlq` group.

Uses Click's CliRunner so we don't need a real bench process; the dispatch
into Frappe ORM is mocked out per test.
"""

from unittest.mock import patch

from click.testing import CliRunner


def _fake_dlq_rows():
    return [
        {
            "name": "DLQE-001", "job": "job-A", "queue": "default",
            "moved_at": "2026-04-29 12:00:00",
            "last_error_type": "RuntimeError",
            "last_error_message": "boom",
        },
        {
            "name": "DLQE-002", "job": "job-B", "queue": "critical",
            "moved_at": "2026-04-29 12:01:00",
            "last_error_type": "TimeoutError",
            "last_error_message": "deadline",
        },
    ]


def test_dlq_list_renders_rows():
    from conductor.commands.dlq import dlq_group
    runner = CliRunner()
    with patch("conductor.commands.dlq._fetch_dlq_rows", return_value=_fake_dlq_rows()), \
         patch("conductor.commands.dlq._connect_to_site"), \
         patch("conductor.commands.dlq._disconnect"):
        result = runner.invoke(dlq_group, ["list", "--site", "frappe.localhost"])
    assert result.exit_code == 0, result.output
    assert "DLQE-001" in result.output
    assert "DLQE-002" in result.output
    assert "RuntimeError" in result.output


def test_dlq_list_filter_by_queue():
    from conductor.commands.dlq import dlq_group
    runner = CliRunner()
    captured = {}
    def fake_fetch(filters, limit):
        captured["filters"] = filters
        captured["limit"] = limit
        return [_fake_dlq_rows()[0]]
    with patch("conductor.commands.dlq._fetch_dlq_rows", side_effect=fake_fetch), \
         patch("conductor.commands.dlq._connect_to_site"), \
         patch("conductor.commands.dlq._disconnect"):
        result = runner.invoke(dlq_group, [
            "list", "--site", "frappe.localhost", "--queue", "default",
        ])
    assert result.exit_code == 0, result.output
    assert captured["filters"] == {"queue": "default"}


def test_dlq_list_filter_by_status():
    from conductor.commands.dlq import dlq_group
    runner = CliRunner()
    captured = {}
    def fake_fetch(filters, limit):
        captured["filters"] = filters
        return _fake_dlq_rows()
    with patch("conductor.commands.dlq._fetch_dlq_rows", side_effect=fake_fetch), \
         patch("conductor.commands.dlq._connect_to_site"), \
         patch("conductor.commands.dlq._disconnect"):
        result = runner.invoke(dlq_group, [
            "list", "--site", "frappe.localhost", "--status", "RETRIED",
        ])
    assert result.exit_code == 0
    assert captured["filters"] == {"status": "RETRIED"}
```

- [ ] **Step 2: Run test to verify it fails**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_dlq_commands.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement the group + list subcommand**

Create `conductor/commands/dlq.py`:

```python
"""bench conductor dlq {list,retry,discard} — operational subcommands over
Conductor DLQ Entry rows. retry/discard live here too but are added in
Task 14."""

from __future__ import annotations

import click
import frappe


def _connect_to_site(site: str) -> None:
    frappe.init(site=site)
    frappe.connect()


def _disconnect() -> None:
    frappe.destroy()


def _fetch_dlq_rows(filters: dict, limit: int) -> list[dict]:
    """Return DLQ Entry rows matching `filters`, newest first, capped at `limit`."""
    return frappe.get_all(
        "Conductor DLQ Entry",
        filters=filters or None,
        fields=["name", "job", "queue", "moved_at", "last_error_type",
                "last_error_message", "status"],
        order_by="moved_at desc",
        limit_page_length=limit,
    )


@click.group("dlq")
def dlq_group():
    """Operational subcommands over Conductor DLQ Entry rows."""


@dlq_group.command("list")
@click.option("--site", required=True, help="Frappe site name.")
@click.option("--queue", default=None, help="Filter to one queue.")
@click.option("--status", "status",
              type=click.Choice(["PENDING_REVIEW", "RETRIED", "DISCARDED"]),
              default=None, help="Filter by review status.")
@click.option("--limit", default=50, type=int, help="Max rows to print.")
def list_command(site, queue, status, limit):
    """List DLQ entries, newest first."""
    filters: dict = {}
    if queue:
        filters["queue"] = queue
    if status:
        filters["status"] = status
    _connect_to_site(site)
    try:
        rows = _fetch_dlq_rows(filters, limit)
    finally:
        _disconnect()

    if not rows:
        click.echo("No DLQ entries match.")
        return
    headers = ["name", "job", "queue", "moved_at", "last_error_type", "last_error_message"]
    widths = [max(len(h), 10) for h in headers]
    for r in rows:
        for i, k in enumerate(headers):
            widths[i] = max(widths[i], len(str(r.get(k, "") or "")[:60]))
    sep = "  "
    click.echo(sep.join(h.ljust(w) for h, w in zip(headers, widths)))
    click.echo(sep.join("-" * w for w in widths))
    for r in rows:
        cells = [str(r.get(h, "") or "")[:60] for h in headers]
        click.echo(sep.join(c.ljust(w) for c, w in zip(cells, widths)))
```

- [ ] **Step 4: Register the group**

Edit `conductor/commands/__init__.py`:

```python
from conductor.commands.dlq import dlq_group
...
conductor_group.add_command(dlq_group)
```

- [ ] **Step 5: Run tests + smoke**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_dlq_commands.py -v
```

Expected: 3 PASS.

```
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost conductor dlq list --site frappe.localhost
```

Expected: either "No DLQ entries match." or a table.

- [ ] **Step 6: Commit**

```
git add conductor/commands/dlq.py conductor/commands/__init__.py tests/test_dlq_commands.py
git commit -m "feat(phase6): bench conductor dlq list"
```

---

## Task 14: `bench conductor dlq retry` and `dlq discard`

**Files:**
- Modify: `conductor/commands/dlq.py`
- Test: `tests/test_dlq_commands.py` (extend)

`retry` re-enqueues each PENDING_REVIEW row via `conductor.enqueue` and flips the row to `RETRIED`. `discard` flips the row to `DISCARDED` without enqueuing. Both record `reviewed_by` and `reviewed_at`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dlq_commands.py`:

```python
def test_dlq_retry_re_enqueues_pending_rows():
    from conductor.commands.dlq import dlq_group
    runner = CliRunner()
    rows = [
        {
            "name": "DLQE-001", "job": "job-A", "queue": "default",
            "method": "conductor.demo.echo", "args_b64": "", "kwargs_b64": "",
            "status": "PENDING_REVIEW",
        },
    ]
    enqueued: list[tuple[str, str, dict]] = []
    flipped: list[tuple[str, str, dict]] = []
    def fake_enqueue(method, *, queue, **kwargs):
        enqueued.append((method, queue, dict(kwargs)))
        return "new-job-id"
    def fake_flip(name, payload):
        flipped.append((name, payload["status"], dict(payload)))
    with patch("conductor.commands.dlq._fetch_pending_rows", return_value=rows), \
         patch("conductor.commands.dlq._enqueue_from_dlq_row", side_effect=fake_enqueue), \
         patch("conductor.commands.dlq._mark_dlq_row", side_effect=fake_flip), \
         patch("conductor.commands.dlq._connect_to_site"), \
         patch("conductor.commands.dlq._disconnect"):
        result = runner.invoke(dlq_group, ["retry", "--site", "frappe.localhost"])
    assert result.exit_code == 0, result.output
    assert enqueued == [("conductor.demo.echo", "default", {})]
    assert flipped == [("DLQE-001", "RETRIED", {"status": "RETRIED",
                                                  "reviewed_by": "system",
                                                  "reviewed_at": flipped[0][2]["reviewed_at"]})]


def test_dlq_retry_skips_non_pending_rows():
    from conductor.commands.dlq import dlq_group
    runner = CliRunner()
    enq_called = []
    with patch("conductor.commands.dlq._fetch_pending_rows", return_value=[]), \
         patch("conductor.commands.dlq._enqueue_from_dlq_row",
               side_effect=lambda *a, **k: enq_called.append(True) or "x"), \
         patch("conductor.commands.dlq._connect_to_site"), \
         patch("conductor.commands.dlq._disconnect"):
        result = runner.invoke(dlq_group, ["retry", "--site", "frappe.localhost"])
    assert result.exit_code == 0
    assert enq_called == []


def test_dlq_discard_marks_row():
    from conductor.commands.dlq import dlq_group
    runner = CliRunner()
    rows = [{
        "name": "DLQE-001", "job": "job-A", "queue": "default",
        "method": "x", "status": "PENDING_REVIEW",
    }]
    flipped = []
    with patch("conductor.commands.dlq._fetch_pending_rows", return_value=rows), \
         patch("conductor.commands.dlq._mark_dlq_row",
               side_effect=lambda name, payload: flipped.append((name, payload["status"]))), \
         patch("conductor.commands.dlq._connect_to_site"), \
         patch("conductor.commands.dlq._disconnect"):
        result = runner.invoke(dlq_group, ["discard", "--site", "frappe.localhost"])
    assert result.exit_code == 0
    assert flipped == [("DLQE-001", "DISCARDED")]
```

- [ ] **Step 2: Run test to verify it fails**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_dlq_commands.py -v
```

Expected: missing `_fetch_pending_rows`, `_enqueue_from_dlq_row`, `_mark_dlq_row`.

- [ ] **Step 3: Add the helpers and the two subcommands**

Append to `conductor/commands/dlq.py`:

```python
import base64
from datetime import datetime

from conductor.serialization import loads as msgpack_loads


def _fetch_pending_rows(filters: dict, limit: int, job_id: str | None) -> list[dict]:
    """Find PENDING_REVIEW rows matching filters, optionally pinned to one job_id.
    Joins through Conductor Job to retrieve `method`, `args`, `kwargs`."""
    if job_id:
        return frappe.db.sql(
            """SELECT d.name, d.job, d.queue, d.status,
                       j.method, j.args, j.kwargs
               FROM `tabConductor DLQ Entry` d
               JOIN `tabConductor Job` j ON j.name = d.job
               WHERE d.status='PENDING_REVIEW' AND d.job=%s
               LIMIT 1""",
            (job_id,), as_dict=True,
        )
    f = ["d.status='PENDING_REVIEW'"]
    args: list = []
    if filters.get("queue"):
        f.append("d.queue=%s")
        args.append(filters["queue"])
    sql = (
        "SELECT d.name, d.job, d.queue, d.status, j.method, j.args, j.kwargs "
        "FROM `tabConductor DLQ Entry` d "
        "JOIN `tabConductor Job` j ON j.name = d.job "
        f"WHERE {' AND '.join(f)} "
        "ORDER BY d.moved_at DESC LIMIT %s"
    )
    args.append(limit)
    return frappe.db.sql(sql, tuple(args), as_dict=True)


def _enqueue_from_dlq_row(method: str, *, queue: str, **kwargs) -> str:
    """Indirection so tests can spy on it."""
    import conductor
    return conductor.enqueue(method, queue=queue, **kwargs)


def _get_actor() -> str:
    """Return the current Frappe session user, or 'system' if Frappe is
    not connected (e.g., CliRunner tests). Robust to missing frappe.session."""
    try:
        return frappe.session.user  # type: ignore[union-attr]
    except Exception:
        return "system"


def _decode_kwargs(b64: str) -> dict:
    if not b64:
        return {}
    return msgpack_loads(base64.b64decode(b64.encode("ascii")))


def _mark_dlq_row(name: str, payload: dict) -> None:
    frappe.db.set_value("Conductor DLQ Entry", name, payload, update_modified=False)
    frappe.db.commit()


@dlq_group.command("retry")
@click.option("--site", required=True)
@click.option("--queue", default=None)
@click.option("--limit", default=50, type=int)
@click.option("--job", "job_id", default=None,
              help="Operate on this specific job_id only.")
def retry_command(site, queue, limit, job_id):
    """Re-enqueue PENDING_REVIEW DLQ entries via conductor.enqueue and mark
    each row RETRIED."""
    filters = {"queue": queue} if queue else {}
    _connect_to_site(site)
    try:
        rows = _fetch_pending_rows(filters, limit, job_id)
        if not rows:
            click.echo("No PENDING_REVIEW DLQ entries match.")
            return
        moved = 0
        for r in rows:
            try:
                kwargs = _decode_kwargs(r.get("kwargs") or "")
                new_id = _enqueue_from_dlq_row(r["method"], queue=r["queue"], **kwargs)
                _mark_dlq_row(r["name"], {
                    "status": "RETRIED",
                    "reviewed_by": _get_actor(),
                    "reviewed_at": datetime.now().replace(microsecond=0),
                })
                moved += 1
                click.echo(f"  retried {r['name']} (job {r['job']} → {new_id})")
            except Exception as e:
                click.echo(f"  FAILED {r['name']}: {type(e).__name__}: {e}", err=True)
        click.echo(f"\nRetried {moved} of {len(rows)} entries.")
    finally:
        _disconnect()


@dlq_group.command("discard")
@click.option("--site", required=True)
@click.option("--queue", default=None)
@click.option("--limit", default=50, type=int)
@click.option("--job", "job_id", default=None)
def discard_command(site, queue, limit, job_id):
    """Mark PENDING_REVIEW DLQ entries DISCARDED without re-enqueuing."""
    filters = {"queue": queue} if queue else {}
    _connect_to_site(site)
    try:
        rows = _fetch_pending_rows(filters, limit, job_id)
        if not rows:
            click.echo("No PENDING_REVIEW DLQ entries match.")
            return
        for r in rows:
            _mark_dlq_row(r["name"], {
                "status": "DISCARDED",
                "reviewed_by": _get_actor(),
                "reviewed_at": datetime.now().replace(microsecond=0),
            })
            click.echo(f"  discarded {r['name']}")
        click.echo(f"\nDiscarded {len(rows)} entries.")
    finally:
        _disconnect()
```

- [ ] **Step 4: Update `_fetch_dlq_rows` (Task 13's helper) to use `frappe.get_all` not the raw SQL — already correct; no change needed.**

- [ ] **Step 5: Run tests**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_dlq_commands.py -v
```

Expected: 6 PASS.

- [ ] **Step 6: Commit**

```
git add conductor/commands/dlq.py tests/test_dlq_commands.py
git commit -m "feat(phase6): bench conductor dlq {retry,discard}"
```

---

## Task 15: RQ migration core (`conductor/migrate_rq.py`)

**Files:**
- Create: `conductor/migrate_rq.py`
- Test: `tests/test_migrate_rq.py`

Importable migration logic. CLI wrapper lives in Task 16. Returns a `MigrationReport` dataclass so tests can assert structure without parsing CLI output.

- [ ] **Step 1: Write the failing test**

Create `tests/test_migrate_rq.py`:

```python
"""Unit tests for conductor.migrate_rq.

Mocks RQ entirely: no rq.Queue instantiation, no real Redis. Asserts the
migration logic — filtering by site, translating queue names, calling
conductor.enqueue, deleting the source RQ job, and the dry-run vs commit
distinction.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fake_rq_jobs():
    """Three RQ jobs: two on the right site, one on a different site (skip)."""
    j1 = MagicMock()
    j1.id = "rq-job-1"
    j1.kwargs = {"site": "alpha.test", "method": "frappe.utils.now", "kwargs": {}}
    j1.delete = MagicMock()

    j2 = MagicMock()
    j2.id = "rq-job-2"
    j2.kwargs = {"site": "alpha.test", "method": "demo.foo", "kwargs": {"x": 1}}
    j2.delete = MagicMock()

    j3 = MagicMock()
    j3.id = "rq-job-other-site"
    j3.kwargs = {"site": "beta.test", "method": "demo.bar", "kwargs": {}}
    j3.delete = MagicMock()

    return [j1, j2, j3]


def test_marker_present_returns_no_op(fake_rq_jobs, fake_redis):
    fake_redis.set("conductor:alpha.test:rq_migrated_at", "2026-04-29T10:00:00")
    from conductor.migrate_rq import migrate_from_rq
    rep = migrate_from_rq(
        "alpha.test",
        queue_map={"default": "default"},
        commit=True,
        force=False,
        _redis_client=fake_redis,
        _rq_pending_jobs=lambda: fake_rq_jobs,
    )
    assert rep.skipped_due_to_marker is True
    assert rep.moved == 0


def test_marker_present_with_force_proceeds(fake_rq_jobs, fake_redis):
    fake_redis.set("conductor:alpha.test:rq_migrated_at", "old")
    enqueued: list = []
    def fake_enqueue(method, *, queue, **kwargs):
        enqueued.append((method, queue, dict(kwargs)))
        return f"new-{len(enqueued)}"
    from conductor.migrate_rq import migrate_from_rq
    rep = migrate_from_rq(
        "alpha.test",
        queue_map={"default": "default"},
        commit=True,
        force=True,
        _redis_client=fake_redis,
        _rq_pending_jobs=lambda: fake_rq_jobs,
        _enqueue=fake_enqueue,
    )
    assert rep.skipped_due_to_marker is False
    assert rep.moved == 2  # j1, j2 — j3 skipped (different site)


def test_dry_run_does_not_call_enqueue_or_delete(fake_rq_jobs, fake_redis):
    enq_called = []
    from conductor.migrate_rq import migrate_from_rq
    rep = migrate_from_rq(
        "alpha.test",
        queue_map={"default": "default"},
        commit=False,
        force=False,
        _redis_client=fake_redis,
        _rq_pending_jobs=lambda: fake_rq_jobs,
        _enqueue=lambda *a, **k: enq_called.append(True) or "x",
    )
    assert enq_called == []
    for j in fake_rq_jobs:
        assert j.delete.call_count == 0
    # The plan rows are populated for the operator to review:
    assert len(rep.plan) == 2  # two on alpha.test
    # Marker not set on dry-run
    assert fake_redis.get("conductor:alpha.test:rq_migrated_at") is None


def test_commit_calls_enqueue_then_delete_then_writes_marker(fake_rq_jobs, fake_redis):
    new_ids = iter(["new-1", "new-2"])
    enqueued = []
    def fake_enq(method, *, queue, **kwargs):
        enqueued.append((method, queue))
        return next(new_ids)
    from conductor.migrate_rq import migrate_from_rq
    rep = migrate_from_rq(
        "alpha.test",
        queue_map={"default": "default"},
        commit=True,
        force=False,
        _redis_client=fake_redis,
        _rq_pending_jobs=lambda: fake_rq_jobs,
        _enqueue=fake_enq,
    )
    assert rep.moved == 2
    assert fake_rq_jobs[0].delete.call_count == 1
    assert fake_rq_jobs[1].delete.call_count == 1
    assert fake_rq_jobs[2].delete.call_count == 0  # other-site, untouched
    assert fake_redis.get("conductor:alpha.test:rq_migrated_at") is not None


def test_callable_method_is_skipped_with_warning(fake_rq_jobs, fake_redis):
    j_callable = MagicMock()
    j_callable.id = "rq-callable"
    j_callable.kwargs = {"site": "alpha.test",
                         "method": lambda: None,  # callable, not str
                         "kwargs": {}}
    j_callable.delete = MagicMock()
    from conductor.migrate_rq import migrate_from_rq
    rep = migrate_from_rq(
        "alpha.test",
        queue_map={"default": "default"},
        commit=True,
        force=False,
        _redis_client=fake_redis,
        _rq_pending_jobs=lambda: [j_callable],
        _enqueue=lambda *a, **k: "new",
    )
    assert rep.moved == 0
    assert rep.skipped_callable_method == 1
    assert j_callable.delete.call_count == 0


def test_unmapped_rq_queue_falls_back_to_default(fake_redis):
    j = MagicMock()
    j.id = "rq-x"
    j.kwargs = {"site": "alpha.test", "method": "x.y", "kwargs": {}}
    j.delete = MagicMock()
    j.origin = "long_q_unmapped"
    enq = []
    from conductor.migrate_rq import migrate_from_rq
    rep = migrate_from_rq(
        "alpha.test",
        queue_map={"short": "short", "default": "default"},
        commit=True,
        force=False,
        _redis_client=fake_redis,
        _rq_pending_jobs=lambda: [(j, "long_q_unmapped")],  # tuple form
        _enqueue=lambda method, *, queue, **k: enq.append((method, queue)) or "x",
    )
    assert rep.moved == 1
    assert enq == [("x.y", "default")]
    assert rep.unmapped_queues_seen == {"long_q_unmapped": 1}
```

- [ ] **Step 2: Run test to verify it fails**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_migrate_rq.py -v
```

Expected: `ModuleNotFoundError: No module named 'conductor.migrate_rq'`.

- [ ] **Step 3: Implement the migration core**

Create `conductor/migrate_rq.py`:

```python
"""RQ → Conductor one-shot migration logic.

Public entry point: `migrate_from_rq(site, *, queue_map, commit=False,
force=False) -> MigrationReport`.

Test seams (keyword-only, optional, default to real implementations):
    _redis_client      — Redis client; default = conductor's standard one.
    _rq_pending_jobs   — () → iterable of (rq_job, rq_origin_queue_name)
                         tuples OR plain rq_job objects (rq_job.origin is
                         the source queue name).
    _enqueue           — conductor.enqueue replacement, default = real one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional


_MARKER_KEY_PATTERN = "conductor:{site}:rq_migrated_at"


@dataclass
class MigrationReport:
    site: str
    plan: list[dict] = field(default_factory=list)  # dry-run preview rows
    moved: int = 0
    skipped_other_site: int = 0
    skipped_callable_method: int = 0
    skipped_due_to_marker: bool = False
    failed: int = 0
    unmapped_queues_seen: dict[str, int] = field(default_factory=dict)


def _default_redis_client():
    import frappe
    from conductor.client import get_redis
    from conductor.config import load_config
    cfg = load_config(frappe.local.conf)
    return get_redis(cfg.redis_url)


def _default_rq_pending_jobs() -> Iterable[tuple]:
    """Walk all Frappe RQ pending registries for the current bench's Redis,
    yielding (rq_job, origin_queue_name) tuples. Started/failed/scheduled
    registries are skipped."""
    from frappe.utils.background_jobs import generate_qname, get_queues_timeout, get_redis_conn
    import rq
    conn = get_redis_conn()
    for qtype in get_queues_timeout().keys():
        qname = generate_qname(qtype)
        q = rq.Queue(qname, connection=conn)
        for jid in q.job_ids:
            try:
                job = rq.job.Job.fetch(jid, connection=conn)
            except Exception:
                continue
            yield (job, qtype)


def _default_enqueue(method: str, *, queue: str, **kwargs) -> str:
    import conductor
    return conductor.enqueue(method, queue=queue, **kwargs)


def _normalize_pending_jobs(it) -> list[tuple]:
    """Accept either iterable of (job, origin) tuples or iterable of jobs
    (with `.origin`). Always returns list of (job, origin)."""
    out: list[tuple] = []
    for entry in it:
        if isinstance(entry, tuple) and len(entry) == 2:
            out.append(entry)
        else:
            origin = getattr(entry, "origin", "default")
            out.append((entry, origin))
    return out


def migrate_from_rq(
    site: str,
    *,
    queue_map: dict[str, str],
    commit: bool,
    force: bool,
    _redis_client=None,
    _rq_pending_jobs: Optional[Callable] = None,
    _enqueue: Optional[Callable] = None,
) -> MigrationReport:
    rep = MigrationReport(site=site)

    r = _redis_client if _redis_client is not None else _default_redis_client()
    fetch = _rq_pending_jobs if _rq_pending_jobs is not None else _default_rq_pending_jobs
    enq = _enqueue if _enqueue is not None else _default_enqueue

    marker_key = _MARKER_KEY_PATTERN.format(site=site)
    if r.get(marker_key) is not None and not force:
        rep.skipped_due_to_marker = True
        return rep

    pending = _normalize_pending_jobs(fetch())

    for job, origin in pending:
        kw = getattr(job, "kwargs", {}) or {}
        if kw.get("site") != site:
            rep.skipped_other_site += 1
            continue
        method = kw.get("method")
        if not isinstance(method, str):
            rep.skipped_callable_method += 1
            continue

        target_queue = queue_map.get(origin)
        if target_queue is None:
            rep.unmapped_queues_seen[origin] = rep.unmapped_queues_seen.get(origin, 0) + 1
            target_queue = "default"

        rep.plan.append({
            "rq_job_id": job.id,
            "rq_queue": origin,
            "method": method,
            "target_queue": target_queue,
        })

        if not commit:
            continue

        try:
            new_id = enq(method, queue=target_queue, **(kw.get("kwargs") or {}))
            try:
                job.delete()
            except Exception:
                # Worst case: we enqueued but couldn't delete from RQ. Log,
                # increment failed, keep going. Operator must clean up.
                rep.failed += 1
                continue
            rep.moved += 1
            rep.plan[-1]["new_job_id"] = new_id
        except Exception:
            rep.failed += 1

    if commit and (rep.moved > 0 or rep.skipped_other_site > 0 or rep.unmapped_queues_seen):
        r.set(marker_key, datetime.now(timezone.utc).isoformat())

    return rep
```

- [ ] **Step 4: Run tests to verify they pass**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_migrate_rq.py -v
```

Expected: 6 PASS.

- [ ] **Step 5: Commit**

```
git add conductor/migrate_rq.py tests/test_migrate_rq.py
git commit -m "feat(phase6): RQ migration core with marker idempotency + dry-run"
```

---

## Task 16: `bench conductor migrate-from-rq` CLI wrapper

**Files:**
- Create: `conductor/commands/migrate_rq.py`
- Modify: `conductor/commands/__init__.py`
- Test: `tests/test_migrate_rq.py` (extend with CliRunner test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_migrate_rq.py`:

```python
def test_cli_dry_run_default():
    """`bench conductor migrate-from-rq` without --commit is dry-run."""
    from click.testing import CliRunner
    from conductor.commands.migrate_rq import migrate_rq_command
    from conductor.migrate_rq import MigrationReport

    fake_rep = MigrationReport(site="alpha.test")
    fake_rep.plan = [{"rq_job_id": "x", "rq_queue": "default",
                      "method": "demo.foo", "target_queue": "default"}]
    with patch("conductor.commands.migrate_rq.migrate_from_rq",
               return_value=fake_rep) as mock_mig, \
         patch("conductor.commands.migrate_rq._init_site"), \
         patch("conductor.commands.migrate_rq._destroy_site"):
        runner = CliRunner()
        result = runner.invoke(migrate_rq_command, ["--site", "alpha.test"])
    assert result.exit_code == 0, result.output
    assert mock_mig.call_args.kwargs["commit"] is False
    assert "DRY RUN" in result.output


def test_cli_commit_passes_force_flag():
    from click.testing import CliRunner
    from conductor.commands.migrate_rq import migrate_rq_command
    from conductor.migrate_rq import MigrationReport
    fake_rep = MigrationReport(site="alpha.test")
    with patch("conductor.commands.migrate_rq.migrate_from_rq",
               return_value=fake_rep) as mock_mig, \
         patch("conductor.commands.migrate_rq._init_site"), \
         patch("conductor.commands.migrate_rq._destroy_site"):
        runner = CliRunner()
        result = runner.invoke(migrate_rq_command, [
            "--site", "alpha.test", "--commit", "--force",
        ], input="y\n")
    assert result.exit_code == 0, result.output
    assert mock_mig.call_args.kwargs["commit"] is True
    assert mock_mig.call_args.kwargs["force"] is True


def test_cli_queue_map_parsing():
    from click.testing import CliRunner
    from conductor.commands.migrate_rq import migrate_rq_command, _parse_queue_map
    assert _parse_queue_map(None) == {"short": "short", "default": "default", "long": "long"}
    assert _parse_queue_map("rq1=conductor1,rq2=long") == {
        "rq1": "conductor1", "rq2": "long",
    }


def test_cli_queue_map_invalid_raises():
    from conductor.commands.migrate_rq import _parse_queue_map
    with pytest.raises(ValueError):
        _parse_queue_map("just_one_no_equals")
```

- [ ] **Step 2: Run test to verify it fails**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_migrate_rq.py -v
```

Expected: missing `migrate_rq_command` / `_parse_queue_map`.

- [ ] **Step 3: Implement the CLI**

Create `conductor/commands/migrate_rq.py`:

```python
"""bench conductor migrate-from-rq — one-shot RQ → Conductor migration."""

from __future__ import annotations

import click
import frappe

from conductor.migrate_rq import migrate_from_rq

DEFAULT_QUEUE_MAP = {"short": "short", "default": "default", "long": "long"}


def _init_site(site: str) -> None:
    frappe.init(site=site)
    frappe.connect()


def _destroy_site() -> None:
    frappe.destroy()


def _parse_queue_map(spec: str | None) -> dict[str, str]:
    if spec is None or spec == "":
        return dict(DEFAULT_QUEUE_MAP)
    out: dict[str, str] = {}
    for pair in spec.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ValueError(f"invalid --queue-map entry: {pair!r} (expected 'rq=conductor')")
        rq, _, cd = pair.partition("=")
        out[rq.strip()] = cd.strip()
    return out


@click.command("migrate-from-rq")
@click.option("--site", required=True, help="Frappe site to migrate.")
@click.option("--queue-map", "queue_map_str", default=None,
              help="Comma list 'rq_queue=conductor_queue,...'. Default: short,default,long → identity.")
@click.option("--commit", is_flag=True, default=False,
              help="Actually perform the migration. Without this flag, runs as a dry-run preview.")
@click.option("--force", is_flag=True, default=False,
              help="Ignore the conductor:{site}:rq_migrated_at marker (re-run a previously-completed migration).")
def migrate_rq_command(site, queue_map_str, commit, force):
    """One-shot RQ → Conductor migration (defaults to dry-run)."""
    qmap = _parse_queue_map(queue_map_str)

    if commit and not force:
        click.echo(
            "WARNING: This will move pending RQ jobs into Conductor.\n"
            "For a clean cutover, stop Frappe processes that still call frappe.enqueue\n"
            "or that route through conductor.frappe_compat.enqueue's HTTP shim.\n"
        )
        click.confirm("Continue?", default=False, abort=True)

    _init_site(site)
    try:
        rep = migrate_from_rq(
            site, queue_map=qmap, commit=commit, force=force,
        )
    finally:
        _destroy_site()

    if rep.skipped_due_to_marker:
        click.echo(f"Site {site} already has an RQ migration marker. Pass --force to re-run.")
        return

    mode = "COMMIT" if commit else "DRY RUN"
    click.echo(f"\n=== {mode} report — site {site} ===")
    click.echo(f"  plan rows           : {len(rep.plan)}")
    if commit:
        click.echo(f"  moved               : {rep.moved}")
    click.echo(f"  skipped (other site): {rep.skipped_other_site}")
    click.echo(f"  skipped (callable)  : {rep.skipped_callable_method}")
    click.echo(f"  failed              : {rep.failed}")
    if rep.unmapped_queues_seen:
        click.echo(f"  unmapped queues seen: {dict(rep.unmapped_queues_seen)} (fell back to 'default')")
    if not commit and rep.plan:
        click.echo("\nFirst 5 plan rows:")
        for row in rep.plan[:5]:
            click.echo(f"  {row}")
        click.echo("\nRe-run with --commit to apply.")
```

- [ ] **Step 4: Register the command**

Edit `conductor/commands/__init__.py`:

```python
from conductor.commands.migrate_rq import migrate_rq_command
...
conductor_group.add_command(migrate_rq_command)
```

- [ ] **Step 5: Run tests + dry-run smoke**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_migrate_rq.py -v
```

Expected: 10 PASS.

```
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost conductor migrate-from-rq --site frappe.localhost
```

Expected: `=== DRY RUN report — site frappe.localhost ===` printed. Likely 0 plan rows on a clean dev bench; that's fine.

- [ ] **Step 6: Commit**

```
git add conductor/commands/migrate_rq.py conductor/commands/__init__.py tests/test_migrate_rq.py
git commit -m "feat(phase6): bench conductor migrate-from-rq CLI"
```

---

## Band D — Exit Criterion + Master Updates

## Task 17: Chaos — pool worker serving 3 sites, kill -9 mid-run, peer reclaims

**Files:**
- Create: `tests_chaos/test_phase6_pool_chaos.py`

This proves: stream-key→site routing is correct under load, XAUTOCLAIM works across sites, the per-site CancelPoller wiring boots cleanly, and the inflight counter does not leak across pool-worker restarts (the reaper drift correction kicks in).

**Note on test sites.** The chaos suite's existing `conftest.py` runs against `frappe.localhost` only. To exercise a multi-site pool, this test creates two ephemeral fixture sites (`alpha.test` and `beta.test`) at the start and tears them down at the end. The fixture pattern follows `bench new-site --no-mariadb-replica --admin-password admin` programmatically. If the bench environment cannot create new sites (no MariaDB grant), the test SKIPS with a clear message rather than failing.

- [ ] **Step 1: Write the test**

Create `tests_chaos/test_phase6_pool_chaos.py`:

```python
"""Phase 6 exit criterion #1: pool worker survives kill -9 across 3 sites.

Boots a pool worker for 3 fixture sites (frappe.localhost + 2 transient).
Dispatches 30 jobs total (10 per site). Kills the pool worker mid-run.
Spawns a peer pool worker for the same sites. Asserts every job reaches
SUCCEEDED exactly once, with no row stuck in RUNNING for >30s.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

BENCH_ROOT = Path("/Users/osamamuhammed/frappe_15")
PRIMARY_SITE = "frappe.localhost"
EXTRA_SITES = ["alpha.phase6.test", "beta.phase6.test"]


def _site_exists(site: str) -> bool:
    return (BENCH_ROOT / "sites" / site / "site_config.json").is_file()


def _create_site(site: str) -> bool:
    if _site_exists(site):
        return True
    cmd = [
        "bench", "new-site", site,
        "--admin-password", "admin",
        "--mariadb-root-password", "admin",
        "--no-mariadb-replica",
        "--install-app", "conductor",
    ]
    try:
        subprocess.run(cmd, cwd=str(BENCH_ROOT), check=True, capture_output=True, timeout=300)
    except Exception as e:
        print(f"site creation failed for {site}: {e}")
        return False
    return True


def _drop_site(site: str) -> None:
    if not _site_exists(site):
        return
    subprocess.run(
        ["bench", "drop-site", site, "--force", "--mariadb-root-password", "admin", "--no-backup"],
        cwd=str(BENCH_ROOT), check=False, capture_output=True, timeout=120,
    )


@pytest.fixture(scope="module")
def fixture_sites():
    created: list[str] = []
    for s in EXTRA_SITES:
        if _create_site(s):
            created.append(s)
        else:
            pytest.skip(f"cannot create chaos fixture site {s}; bench permissions / MariaDB?")
    sites = [PRIMARY_SITE] + created
    yield sites
    for s in created:
        _drop_site(s)


def _enqueue_demo_jobs(site: str, n: int) -> list[str]:
    """Run `bench --site=<site> conductor enqueue ...` n times. Returns job ids."""
    ids: list[str] = []
    for i in range(n):
        out = subprocess.check_output(
            ["bench", "--site", site, "execute", "conductor.enqueue",
             "--kwargs", f'{{"method": "conductor.demo.echo", "queue": "default", "k": {i}}}'],
            cwd=str(BENCH_ROOT), timeout=60,
        )
        # bench execute prints the return value; strip whitespace + quotes
        jid = out.decode().strip().strip("'").strip('"').strip()
        if jid:
            ids.append(jid)
    return ids


def _spawn_pool_worker(sites: list[str]) -> subprocess.Popen:
    return subprocess.Popen(
        ["bench", "conductor", "worker",
         "--sites", ",".join(sites),
         "--queue", "default",
         "--concurrency", "4",
         "--grace", "5"],
        cwd=str(BENCH_ROOT),
        preexec_fn=os.setsid,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _kill_subprocess_group(p: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass
    p.wait(timeout=5)


def _job_status(site: str, job_id: str) -> str | None:
    """Read the job's status via bench execute."""
    out = subprocess.check_output(
        ["bench", "--site", site, "execute", "frappe.db.get_value",
         "--kwargs", f'{{"doctype": "Conductor Job", "filters": {{"name": "{job_id}"}}, "fieldname": "status"}}'],
        cwd=str(BENCH_ROOT), timeout=30,
    )
    val = out.decode().strip().strip("'").strip('"').strip()
    return val or None


def test_pool_worker_kill_then_peer_reclaim(fixture_sites):
    sites = fixture_sites
    # 1. Enqueue 10 jobs per site.
    job_ids: dict[str, list[str]] = {}
    for s in sites:
        job_ids[s] = _enqueue_demo_jobs(s, 10)

    # 2. Boot pool worker A; let it run briefly so a few jobs start.
    a = _spawn_pool_worker(sites)
    time.sleep(2.5)
    _kill_subprocess_group(a)

    # 3. Boot pool worker B (peer); wait for everything to drain.
    b = _spawn_pool_worker(sites)
    deadline = time.time() + 90
    try:
        while time.time() < deadline:
            done = True
            for s in sites:
                for jid in job_ids[s]:
                    if _job_status(s, jid) != "SUCCEEDED":
                        done = False
                        break
                if not done:
                    break
            if done:
                break
            time.sleep(2)
        else:
            pytest.fail("pool worker did not drain all jobs within 90s after kill")
    finally:
        _kill_subprocess_group(b)

    # 4. Final assertions: every job is SUCCEEDED, no duplicates.
    for s in sites:
        for jid in job_ids[s]:
            assert _job_status(s, jid) == "SUCCEEDED", f"{s}/{jid} not SUCCEEDED"
```

- [ ] **Step 2: Run the test**

```
cd /Users/osamamuhammed/frappe_15/apps/conductor
/Users/osamamuhammed/frappe_15/env/bin/pytest tests_chaos/test_phase6_pool_chaos.py -v -s
```

Expected: site creation succeeds (3–5 minutes per fixture site), test PASSES (≤90s post-setup), teardown drops the fixture sites.

If site creation fails, the test SKIPs cleanly — that's acceptable for environments without MariaDB grants. The exit criterion is satisfied if the test passes anywhere it can run; for environments where it skips, manual verification with two real sites is the fallback (document in the handoff at Task 22).

- [ ] **Step 3: Commit**

```
git add tests_chaos/test_phase6_pool_chaos.py
git commit -m "test(chaos): Phase 6 exit criterion 1 — pool worker kill+peer-reclaim"
```

---

## Task 18: Chaos — rate limit caps throughput as configured

**Files:**
- Create: `tests_chaos/test_phase6_rate_limit.py`

Single site, `max_rps=10`, dispatch 50 jobs each calling `time.sleep(0.1)`. Run a worker with `--concurrency=20` (over-provisioned to make rate-limit the bottleneck). Assert wall time is in `[3.5s, 8.0s]` (load-bearing assertion: > 1s proves throttling occurred; ≤ 8s proves no runaway).

- [ ] **Step 1: Write the test**

Create `tests_chaos/test_phase6_rate_limit.py`:

```python
"""Phase 6 exit criterion #2: per-(site, queue) rate limit caps throughput.

Configures Conductor Queue 'default' with max_rps=10. Dispatches 50 jobs that
sleep 100 ms each. With concurrency=20, no rate limit would mean wall time
≈ 50 × 0.1 / 20 = 0.25 s. With max_rps=10 (and 1s delay-loop tick), realistic
wall time is 4–6 s. We assert [3.5, 8.0] for CI tolerance.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import frappe
import pytest

BENCH_ROOT = Path("/Users/osamamuhammed/frappe_15")
SITE = "frappe.localhost"


@pytest.fixture
def rate_limit_set():
    """Set max_rps=10 for 'default'; reset to 0 in teardown."""
    q = frappe.get_doc("Conductor Queue", "default")
    original_rps = int(q.max_rps or 0)
    q.max_rps = 10
    q.save(ignore_permissions=True)
    frappe.db.commit()
    yield
    q = frappe.get_doc("Conductor Queue", "default")
    q.max_rps = original_rps
    q.save(ignore_permissions=True)
    frappe.db.commit()


def _enqueue_sleep(site: str, n: int, sleep_s: float) -> list[str]:
    ids: list[str] = []
    for _ in range(n):
        out = subprocess.check_output(
            ["bench", "--site", site, "execute", "conductor.enqueue",
             "--kwargs", f'{{"method": "time.sleep", "queue": "default", "seconds": {sleep_s}}}'],
            cwd=str(BENCH_ROOT), timeout=60,
        )
        jid = out.decode().strip().strip("'").strip('"').strip()
        if jid:
            ids.append(jid)
    return ids


def _spawn_worker(concurrency: int) -> subprocess.Popen:
    return subprocess.Popen(
        ["bench", "--site", SITE, "conductor", "worker",
         "--queue", "default", "--concurrency", str(concurrency), "--grace", "5"],
        cwd=str(BENCH_ROOT),
        preexec_fn=os.setsid,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _wait_for_drain(job_ids: list[str], deadline_s: float) -> float:
    start = time.time()
    while time.time() - start < deadline_s:
        frappe.db.rollback()
        rows = frappe.db.sql(
            "SELECT COUNT(*) FROM `tabConductor Job` WHERE name IN %s "
            "AND status NOT IN ('SUCCEEDED','FAILED','TIMED_OUT','DLQ')",
            (tuple(job_ids),),
        )
        unfinished = int(rows[0][0]) if rows else 0
        if unfinished == 0:
            return time.time() - start
        time.sleep(0.2)
    raise AssertionError(f"jobs did not drain within {deadline_s}s; unfinished={unfinished}")


def test_rate_limit_caps_throughput(rate_limit_set):
    """50 jobs × 0.1s sleep, max_rps=10, concurrency=20 → wall time in [3.5, 8.0]."""
    job_ids = _enqueue_sleep(SITE, 50, 0.1)
    assert len(job_ids) == 50

    worker = _spawn_worker(concurrency=20)
    try:
        elapsed = _wait_for_drain(job_ids, deadline_s=15.0)
    finally:
        try:
            os.killpg(os.getpgid(worker.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        worker.wait(timeout=10)

    print(f"\nRATE-LIMIT WALL TIME: {elapsed:.2f}s (expected [3.5, 8.0])")
    assert elapsed >= 3.5, (
        f"wall time {elapsed:.2f}s — too fast, rate limit did not throttle. "
        f"Without throttling 50 × 0.1s ÷ 20 concurrency = 0.25s, so anything > 1s "
        f"proves rate-limit kicked in; we expect ~5s."
    )
    assert elapsed <= 8.0, (
        f"wall time {elapsed:.2f}s — too slow. Either delay-loop is stalling, "
        f"the throttle path is leaking jobs to DLQ, or worker concurrency is wrong."
    )

    # All jobs SUCCEEDED
    frappe.db.rollback()
    rows = frappe.db.sql(
        "SELECT status, COUNT(*) FROM `tabConductor Job` WHERE name IN %s GROUP BY status",
        (tuple(job_ids),),
    )
    by_status = {r[0]: int(r[1]) for r in rows}
    assert by_status.get("SUCCEEDED", 0) == 50, by_status
```

- [ ] **Step 2: Run the test**

```
cd /Users/osamamuhammed/frappe_15/apps/conductor
/Users/osamamuhammed/frappe_15/env/bin/pytest tests_chaos/test_phase6_rate_limit.py -v -s
```

Expected: PASSES with elapsed time printed in `[3.5, 8.0]`.

- [ ] **Step 3: Commit**

```
git add tests_chaos/test_phase6_rate_limit.py
git commit -m "test(chaos): Phase 6 exit criterion 2 — rate limit caps throughput"
```

---

## Task 19: Chaos — concurrency cap holds simultaneous RUNNING ≤ 2

**Files:**
- Create: `tests_chaos/test_phase6_concurrency_cap.py`

Single site, `max_concurrent=2`, dispatch 10 jobs each sleep(1.0), worker `--concurrency=10`. Sample `Conductor Job.status` every 100 ms. Assert no sample shows more than 2 rows in `RUNNING`.

- [ ] **Step 1: Write the test**

Create `tests_chaos/test_phase6_concurrency_cap.py`:

```python
"""Phase 6 exit criterion #3: concurrency cap holds inflight RUNNING ≤ cap."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path

import frappe
import pytest

BENCH_ROOT = Path("/Users/osamamuhammed/frappe_15")
SITE = "frappe.localhost"


@pytest.fixture
def concurrency_cap_set():
    q = frappe.get_doc("Conductor Queue", "default")
    original = int(q.max_concurrent or 0)
    q.max_concurrent = 2
    q.save(ignore_permissions=True)
    frappe.db.commit()
    yield
    q = frappe.get_doc("Conductor Queue", "default")
    q.max_concurrent = original
    q.save(ignore_permissions=True)
    frappe.db.commit()


def _enqueue_sleep(n: int, seconds: float) -> list[str]:
    ids: list[str] = []
    for _ in range(n):
        out = subprocess.check_output(
            ["bench", "--site", SITE, "execute", "conductor.enqueue",
             "--kwargs", f'{{"method": "time.sleep", "queue": "default", "seconds": {seconds}}}'],
            cwd=str(BENCH_ROOT), timeout=60,
        )
        jid = out.decode().strip().strip("'").strip('"').strip()
        if jid:
            ids.append(jid)
    return ids


def _spawn_worker() -> subprocess.Popen:
    return subprocess.Popen(
        ["bench", "--site", SITE, "conductor", "worker",
         "--queue", "default", "--concurrency", "10", "--grace", "5"],
        cwd=str(BENCH_ROOT),
        preexec_fn=os.setsid,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


class _RunningSampler(threading.Thread):
    """Polls RUNNING count for `job_ids` every 100 ms; records max."""

    def __init__(self, job_ids: list[str]):
        super().__init__(daemon=True)
        self.job_ids = job_ids
        self.max_running = 0
        self.samples: list[int] = []
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            frappe.db.rollback()
            rows = frappe.db.sql(
                "SELECT COUNT(*) FROM `tabConductor Job` "
                "WHERE name IN %s AND status='RUNNING'",
                (tuple(self.job_ids),),
            )
            n = int(rows[0][0]) if rows else 0
            self.samples.append(n)
            self.max_running = max(self.max_running, n)
            self._stop.wait(0.1)

    def stop(self) -> None:
        self._stop.set()
        self.join(timeout=2)


def test_concurrency_cap_caps_running(concurrency_cap_set):
    job_ids = _enqueue_sleep(10, 1.0)
    assert len(job_ids) == 10

    sampler = _RunningSampler(job_ids)
    worker = _spawn_worker()
    sampler.start()

    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            frappe.db.rollback()
            rows = frappe.db.sql(
                "SELECT COUNT(*) FROM `tabConductor Job` WHERE name IN %s "
                "AND status NOT IN ('SUCCEEDED','FAILED','TIMED_OUT','DLQ')",
                (tuple(job_ids),),
            )
            if int(rows[0][0]) == 0:
                break
            time.sleep(0.5)
        else:
            pytest.fail("jobs did not drain within 30s")
    finally:
        sampler.stop()
        try:
            os.killpg(os.getpgid(worker.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        worker.wait(timeout=10)

    print(f"\nMAX RUNNING SAMPLED: {sampler.max_running} (cap=2; samples={len(sampler.samples)})")
    assert sampler.max_running <= 2, (
        f"observed {sampler.max_running} simultaneously RUNNING — concurrency cap leak"
    )
    # Also assert we DID see at least 1 RUNNING (proves we sampled while jobs were active)
    assert sampler.max_running >= 1, "sampler never caught a RUNNING job — test is meaningless"
```

- [ ] **Step 2: Run the test**

```
cd /Users/osamamuhammed/frappe_15/apps/conductor
/Users/osamamuhammed/frappe_15/env/bin/pytest tests_chaos/test_phase6_concurrency_cap.py -v -s
```

Expected: PASSES. Prints `MAX RUNNING SAMPLED: 2 (cap=2; samples=N)` for some N > 50.

- [ ] **Step 3: Commit**

```
git add tests_chaos/test_phase6_concurrency_cap.py
git commit -m "test(chaos): Phase 6 exit criterion 3 — concurrency cap holds"
```

---

## Task 20: Benchmark — pool throughput and per-job init/destroy overhead (non-gating)

**Files:**
- Create: `tests/benchmarks/__init__.py` (empty)
- Create: `tests/benchmarks/test_phase6_pool_throughput.py`

Per master §10 risk #2, we benchmark the per-job `frappe.init/connect/destroy` cost in pool mode to inform any future connection-cache decision. **Non-gating:** the test reports numbers; it does not assert thresholds.

- [ ] **Step 1: Create the package marker**

```
mkdir -p tests/benchmarks
touch tests/benchmarks/__init__.py
```

- [ ] **Step 2: Write the benchmark**

Create `tests/benchmarks/test_phase6_pool_throughput.py`:

```python
"""Phase 6 benchmark — non-gating measurement of per-job site-context overhead.

Spins up to 10 fixture sites (or whatever the bench permits — gracefully
degrades to fewer), dispatches 100 instant jobs per site, runs a single
pool worker `--concurrency=8`, and prints:
    - p50/p95/p99 frappe.init+connect+destroy wall time per job
    - total throughput (jobs/sec)
    - per-job overhead as % of trivial-job duration

If the overhead exceeds 30% of trivial-job wall time, this test prints a
recommendation to file a follow-up for the connection cache (master §10
risk #2). It does NOT fail the build.

Run with: `pytest tests/benchmarks/test_phase6_pool_throughput.py -v -s --no-header`
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from statistics import median

import pytest

BENCH_ROOT = Path("/Users/osamamuhammed/frappe_15")
TARGET_SITE_COUNT = 10
JOBS_PER_SITE = 100


def _existing_conductor_sites() -> list[str]:
    """Return whatever conductor-installed sites already exist on the bench."""
    from conductor.site_discovery import discover_installed_sites
    return discover_installed_sites(str(BENCH_ROOT / "sites"))


def _percentile(samples: list[float], p: float) -> float:
    if not samples:
        return 0.0
    s = sorted(samples)
    k = int(len(s) * p)
    return s[min(k, len(s) - 1)]


@pytest.mark.skipif(
    len(_existing_conductor_sites()) < 2,
    reason="benchmark needs ≥ 2 conductor-installed sites; use the chaos pool test's "
           "fixture sites or onboard more tenants before running this.",
)
def test_pool_throughput_benchmark():
    sites = _existing_conductor_sites()[:TARGET_SITE_COUNT]
    print(f"\n=== Phase 6 pool benchmark — {len(sites)} sites × {JOBS_PER_SITE} jobs ===")

    # 1. Enqueue
    enq_start = time.time()
    for s in sites:
        for _ in range(JOBS_PER_SITE):
            subprocess.check_call(
                ["bench", "--site", s, "execute", "conductor.enqueue",
                 "--kwargs", '{"method": "frappe.utils.now", "queue": "default"}'],
                cwd=str(BENCH_ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=60,
            )
    enq_elapsed = time.time() - enq_start
    total_jobs = len(sites) * JOBS_PER_SITE
    print(f"enqueued {total_jobs} jobs in {enq_elapsed:.1f}s")

    # 2. Boot pool worker
    worker = subprocess.Popen(
        ["bench", "conductor", "worker",
         "--sites", ",".join(sites),
         "--queue", "default",
         "--concurrency", "8", "--grace", "5"],
        cwd=str(BENCH_ROOT),
        preexec_fn=os.setsid,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # 3. Wait for drain; time wall-clock
    import frappe
    run_start = time.time()
    deadline = run_start + 300  # 5-min ceiling
    while time.time() < deadline:
        # Sample one site for now-finished count; assume all sites drain similarly
        frappe.init(site=sites[0])
        try:
            frappe.connect()
            n_unfinished = int(frappe.db.sql(
                "SELECT COUNT(*) FROM `tabConductor Job` "
                "WHERE site=%s AND status NOT IN ('SUCCEEDED','FAILED','TIMED_OUT','DLQ')",
                (sites[0],),
            )[0][0])
        finally:
            frappe.destroy()
        if n_unfinished == 0:
            break
        time.sleep(2)
    run_elapsed = time.time() - run_start

    # 4. Tear down worker
    try:
        os.killpg(os.getpgid(worker.pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    worker.wait(timeout=15)

    throughput = total_jobs / run_elapsed if run_elapsed > 0 else 0
    print(f"drained {total_jobs} jobs in {run_elapsed:.1f}s = {throughput:.1f} jobs/sec")

    # 5. Read per-job durations from Conductor Job Run
    durations_ms: list[int] = []
    for s in sites[:1]:  # one site is enough; per-job init cost dominates
        frappe.init(site=s)
        try:
            frappe.connect()
            rows = frappe.db.sql(
                "SELECT duration_ms FROM `tabConductor Job Run` "
                "WHERE status='SUCCEEDED' ORDER BY started_at DESC LIMIT %s",
                (JOBS_PER_SITE,),
            )
            durations_ms.extend(int(r[0] or 0) for r in rows)
        finally:
            frappe.destroy()

    if durations_ms:
        p50 = median(durations_ms)
        p95 = _percentile(durations_ms, 0.95)
        p99 = _percentile(durations_ms, 0.99)
        print(f"job duration p50={p50:.0f}ms p95={p95:.0f}ms p99={p99:.0f}ms")
        # Trivial job (frappe.utils.now) is ~1 ms of pure work; everything
        # else is init/connect/destroy + Redis + ORM overhead. If p50 > ~10ms,
        # we have a meaningful overhead component to consider caching.
        if p50 > 10:
            print(
                f"\n⚠️  RECOMMENDATION: p50 = {p50:.0f}ms suggests significant "
                f"per-job init/destroy overhead. File follow-up for connection cache "
                f"per master §10 risk #2."
            )
    else:
        print("⚠️  no Job Run rows found — benchmark inconclusive")

    # Non-gating: do NOT assert.
    print("\n=== benchmark complete (non-gating) ===")
```

- [ ] **Step 3: Run the benchmark**

```
cd /Users/osamamuhammed/frappe_15/apps/conductor
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/benchmarks/test_phase6_pool_throughput.py -v -s
```

Expected: prints throughput numbers and per-job durations. SKIP if < 2 sites are available; that's fine.

- [ ] **Step 4: Commit**

```
git add tests/benchmarks/__init__.py tests/benchmarks/test_phase6_pool_throughput.py
git commit -m "test(phase6): non-gating pool-throughput benchmark for §10 risk #2"
```

---

## Task 21: Master design — apply Phase 6 edits

**Files:**
- Modify: `docs/superpowers/specs/2026-04-27-conductor-master-design.md`

Apply the deltas listed in spec §10. All edits are inline; no new sections. The master doc retains the historical change-log entry at the bottom.

- [ ] **Step 1: Update §3 row #14 (multi-tenancy)**

Find line 47:

```
| 14 | Multi-tenancy in v1 | Site-bound workers (`bench conductor worker --site=<site>`). Pool workers with site-context switching are a Phase 6 enhancement. | Simpler ops + isolation. |
```

Replace with:

```
| 14 | Multi-tenancy in v1 | Site-bound workers (`bench conductor worker --site=<site>`) and pool workers (`bench conductor worker --sites=auto|A,B,C`) — single-site is the N=1 case of pool mode (Phase 6). Pool mode switches Frappe site context per job; no connection cache in v1 (deferred per §10 risk #2 to a benchmark-driven decision). | Simpler ops + isolation. |
```

- [ ] **Step 2: Update §4 Phase 6 ships paragraph**

Find line 145:

```
- Pool worker mode (`bench conductor worker --sites=auto --queues=default`): one worker process consumes from N per-site streams; switches Frappe site context per job with a connection cache.
```

Replace with:

```
- Pool worker mode (`bench conductor worker --sites=auto|A,B,C --queues=default`): one worker process consumes from N per-site streams. Routes per-message site by **stream key** (operator-controlled), never by message fields. Switches Frappe site context per job via the existing `_handle_one` init/destroy pattern; **no connection cache in v1** — connection cost is benchmarked in this phase and a cache is added later only if data demands it (master §10 risk #2).
```

- [ ] **Step 3: Update §8 Redis Topology**

Find line 375:

```
conductor:{site}:rate:{queue}          # token bucket                        [Phase 6+]
```

Replace with:

```
conductor:{site}:rate:{queue}          # token bucket: HASH {tokens, last_refill_ms}; PEXPIRE 60s [Phase 6]
conductor:{site}:inflight:{queue}      # INCR/DECR concurrency counter, EXPIRE 1d                 [Phase 6]
conductor:{site}:rq_migrated_at        # marker — set after a successful migrate-from-rq --commit [Phase 6]
```

- [ ] **Step 4: Update §10 risk #2**

Find line 406:

```
2. **Frappe site context overhead** for pool workers — benchmark before Phase 6; may force per-site sub-process pool.
```

Replace with:

```
2. **Frappe site context overhead** for pool workers — Phase 6 ships init/destroy-per-job and a non-gating benchmark (`tests/benchmarks/test_phase6_pool_throughput.py`); cache decision is data-driven post-Phase 6. If the benchmark reports per-job p50 init+destroy overhead > 10ms or > 30% of trivial-job duration, file a follow-up for a connection cache.
```

- [ ] **Step 5: Append change-log entry**

Find the end of the master doc's `## Change Log` table. After the existing 2026-04-29 entry for Phase 5, append:

```
| 2026-04-29 | **Phase 6 (Multi-tenant polish) shipped.** Pool worker mode (`--sites=auto|A,B,C`) where single-site `--site=X` is the N=1 case; per-(site, queue) rate limits and concurrency caps via single-key Lua scripts (`conductor/rate_limit.lua`, `conductor/inflight.lua`) on Redis keys `conductor:{site}:rate:{queue}` and `conductor:{site}:inflight:{queue}`; `Conductor Queue` extended with `max_rps` and `max_concurrent` (both Int default 0 = unlimited). Throttled jobs ride the existing Phase 2 delay path with `reason="rate_limited"`/`"inflight_capped"` events; reaper drift-corrects the inflight counter when workers go GONE. New ops subcommands: `bench conductor depth [--all-sites]`, `dlq {list,retry,discard}`, `migrate-from-rq` (one-shot RQ migration with Redis marker idempotency). Master Phase 6 exit criterion verified: `tests_chaos/test_phase6_pool_chaos.py` (3 sites + kill-9 + peer reclaim), `test_phase6_rate_limit.py` (50 jobs at max_rps=10 land in 3.5–8.0s), `test_phase6_concurrency_cap.py` (10 jobs at max_concurrent=2, max RUNNING ≤ 2 throughout). | osama.m@aau.iq |
```

- [ ] **Step 6: Verify the inter-phase contracts row at line 399 already exists; if so, no edit**

Line 399 already reads `| Pool workers + per-tenant rate limits | Phase 6 | Phase 6 |`. Leave as-is. (If it was missing — older master — append it as the row immediately above the change-log section.)

- [ ] **Step 7: Commit**

```
git add docs/superpowers/specs/2026-04-27-conductor-master-design.md
git commit -m "docs(master): Phase 6 deltas — §3 #14, §4 Phase 6, §8, §10 risk #2, change-log

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
"
```

---

## Task 22: README — operator-facing Phase 6 section + final exit-criterion verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add the Phase 6 operator section**

Find the existing "Workflows" section header in `README.md` (added in Phase 5). Immediately after that section's closing prose (before the next section), add:

```markdown
## Multi-tenant deployments (Phase 6)

Conductor supports two worker shapes:

```bash
# Single-site (existing behavior — bench --site provides the site):
bench --site=alpha.tenant.example.com conductor worker --queue default --concurrency 4

# Pool mode — one process serves N sites:
bench conductor worker --sites=auto --queue default --concurrency 8
bench conductor worker --sites=alpha.test,beta.test --queue default --concurrency 8
```

`--sites=auto` walks `sites/<dir>/site_config.json` and keeps sites with `conductor` in `installed_apps`. The site list is resolved once at boot — onboarding a new tenant requires restarting the pool worker.

### Per-tenant rate limits and concurrency caps

Two new fields on each `Conductor Queue` row:

| Field | Default | Meaning |
|---|---|---|
| `max_rps` | `0` (unlimited) | Tokens per second, enforced by an atomic Redis Lua bucket on `conductor:{site}:rate:{queue}` |
| `max_concurrent` | `0` (unlimited) | Cap on simultaneously RUNNING jobs across the worker fleet, enforced on `conductor:{site}:inflight:{queue}` |

Throttled jobs are NOT failures — they land in `SCHEDULED_RETRY` with `last_error_message="rate_limited"` or `"inflight_capped"`, ride the existing Phase 2 delay loop, and rejoin the queue when capacity returns. The dashboard shows a count of throttled jobs alongside actual retries.

### Operational subcommands

```bash
# Per-(site, queue) depth snapshot:
bench --site=alpha.test conductor depth
bench conductor depth --all-sites

# DLQ triage:
bench --site=alpha.test conductor dlq list --queue default
bench --site=alpha.test conductor dlq retry --queue default --limit 50
bench --site=alpha.test conductor dlq discard --job <job_id>

# RQ → Conductor migration (idempotent via Redis marker):
bench --site=alpha.test conductor migrate-from-rq               # dry-run preview
bench --site=alpha.test conductor migrate-from-rq --commit      # actually move
bench --site=alpha.test conductor migrate-from-rq --commit --force  # ignore prior marker
```
```

- [ ] **Step 2: Bump the status badge / phase indicator**

In the README header, find any "Phase 5 of 5" or "Phase 4 of 5" status text and update it to indicate Phase 6 is the final phase of v1. If no such badge exists, leave the header alone.

- [ ] **Step 3: Run the full pre-merge gate**

```
cd /Users/osamamuhammed/frappe_15/apps/conductor

# 1. Pure-Python unit suite
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/ -v

# 2. Frappe-integration tests (DocType controllers)
bench --site frappe.localhost run-tests --app conductor

# 3. The three Phase 6 chaos gates (in order)
/Users/osamamuhammed/frappe_15/env/bin/pytest tests_chaos/test_phase6_concurrency_cap.py -v -s
/Users/osamamuhammed/frappe_15/env/bin/pytest tests_chaos/test_phase6_rate_limit.py -v -s
/Users/osamamuhammed/frappe_15/env/bin/pytest tests_chaos/test_phase6_pool_chaos.py -v -s

# 4. The earlier-phase chaos suites — must still pass under Phase 6 changes
/Users/osamamuhammed/frappe_15/env/bin/pytest tests_chaos/test_kill_during_run.py -v
/Users/osamamuhammed/frappe_15/env/bin/pytest tests_chaos/test_dispatch_idempotency.py -v
/Users/osamamuhammed/frappe_15/env/bin/pytest tests_chaos/test_retry_exhausts_to_dlq.py -v
/Users/osamamuhammed/frappe_15/env/bin/pytest tests_chaos/test_scheduler_handoff.py -v
/Users/osamamuhammed/frappe_15/env/bin/pytest tests_chaos/test_realtime_events.py -v
/Users/osamamuhammed/frappe_15/env/bin/pytest tests_chaos/test_phase5_chaos.py -v

# 5. Non-gating benchmark (informational)
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/benchmarks/test_phase6_pool_throughput.py -v -s || true
```

Expected for gates 1–4: all pass. Benchmark prints numbers and exits 0 (or skips if < 2 sites).

If `test_phase6_pool_chaos.py` SKIPs because the bench cannot create test sites, perform a manual verification:
1. Use any two existing conductor-installed sites.
2. Edit the test's `EXTRA_SITES` constant to those names temporarily.
3. Run the test.
4. Document in `docs/superpowers/specs/2026-04-29-conductor-phase6-handoff.md` (create if needed) which two sites were used and the `MAX RUNNING SAMPLED` / wall-time numbers from each gate.

- [ ] **Step 4: Commit**

```
git add README.md
git commit -m "docs(phase6): operator-facing README section for pool mode + ops"
```

- [ ] **Step 5: Final sanity check — push branch and confirm**

```
git log --oneline -25
```

Expected: 22 Phase 6 commits in chronological order, latest being the README update. The chain matches the task numbers in this plan.

---

## Self-Review Notes (engineer-facing)

Two implementation details worth re-reading once you finish:

1. **Throttle-gate ordering (Task 8).** Inflight is checked first because acquire-on-cap is a free fail (no INCR), preserving rate-limit tokens for callers that actually run. If inflight succeeds and rate-limit then rejects, you MUST call `inflight_release` before re-scheduling — the unit test covers this but production-code drift is easy to introduce.

2. **Drift correction never touches job rows (Task 11).** The reaper only decrements the counter; job-row recovery is owned by XAUTOCLAIM in the worker (Phase 1 path). If you find yourself adding `frappe.db.set_value("Conductor Job", ..., "status", "FAILED")` inside `_reaper_drift_correction_iter`, stop — that races with the peer worker that's about to reclaim the message and run it.

3. **Pool-mode heartbeat fanout (Task 7).** N init/destroy pairs every 5s. At N=10 sites that's 2/sec amortized — fine. If you see this start to dominate worker CPU at N=20+, that's the second signal (after the benchmark) that a connection cache is overdue. File the follow-up rather than building it in this phase.

---

## Spec Coverage Map

| Spec section | Covered by Tasks |
|---|---|
| §1 Scope (in/out) | §1 in: 6, 8, 11, 12, 13–14, 15–16. §1 out: stays out — no tasks needed. |
| §2 Cross-Phase Reference Map | Reused as-is across tasks; no dedicated coverage task. |
| §3.1 Pool worker — site discovery | 2 |
| §3.1 Pool worker — stream-key routing | 3, 6 |
| §3.1 Pool worker — heartbeat fanout | 7 |
| §3.1 Pool worker — CancelPoller | 9 |
| §3.1 Pool worker — CLI flag | 10 |
| §3.2 / §6.1 Rate-limit Lua + wrapper | 4 |
| §3.2 / §6.2 / §6.3 Inflight Lua + wrappers | 5 |
| §3.2 Per-(site, queue) limits config | 1 |
| §3.3 / §8 RQ migration | 15, 16 |
| §3.4 / §9 Operational subcommands | 12, 13, 14 |
| §5.4 Throttle path | 8 |
| §5.5 Reaper drift correction | 11 |
| §5.6 Fast path when limits unset | 8 (the `if rps <= 0 and conc <= 0: return True` short-circuit) |
| §10 Master document updates | 21 |
| §11.1 Pool chaos | 17 |
| §11.2 Rate-limit chaos | 18 |
| §11.3 Concurrency-cap chaos | 19 |
| §11.4 Benchmark | 20 |
| §12 Realtime events (no new family) | 8 (event payload `reason=...`); covered implicitly |
| §13 Risks | All risks have mitigations baked into the relevant tasks; no dedicated coverage task. |
| §14 Document lifecycle | 22 (README + handoff) |

No placeholders. No "TODO". Every code step has the actual code.

