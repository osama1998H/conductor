# Conductor Phase 2 — Scheduling

**Status:** Draft for approval
**Date:** 2026-04-27
**Author:** osama.m@aau.iq
**Master:** [`2026-04-27-conductor-master-design.md`](./2026-04-27-conductor-master-design.md)
**Hand-off in:** [`2026-04-27-conductor-phase2-handoff.md`](./2026-04-27-conductor-phase2-handoff.md)

This spec refines the master design's "Phase 2 — Scheduling" charter (master §4) using the discoveries documented in the Phase 2 hand-off and the seven brainstorm decisions captured in §3 below. It does **not** relitigate any of the 20 master cross-cutting decisions or any of Phase 1's frozen contracts.

---

## 1. What Phase 2 Ships

A long-running per-site singleton process — `bench conductor scheduler` — that owns four background loops (delay-drain, cron, dead-worker reap, orphan-sweep), plus the `Conductor Schedule` DocType and a `bench conductor schedule` admin CLI. The process subsumes the in-worker `DelayDrainer` and `OrphanSweeper` threads from Phase 1, replaces ad-hoc dead-worker handling with explicit reaping, and is the place where future site-scoped maintenance (Phase 4 metrics sampler, Phase 6 rate-limit refill) will live.

The phase also ships a chaos test (`kill scheduler → peer takes over within ~20 s`) and a fix for the residual 5-run chaos flake gate (per master Phase 2 hand-off §3).

## 2. Out of Scope (deferred per master)

- Pool workers and per-tenant rate limits — Phase 6.
- Real-time dashboard pages — Phase 3.
- OTel exporter and metrics endpoint — Phase 4.
- Workflow advancer and DAG step orchestration — Phase 5.
- Subprocess-isolated hard-kill timeout — master §3 #19 deferred indefinitely; v1 stays cooperative.
- New stream message fields — `schema_version=1` is preserved untouched.

## 3. Brainstorm Decisions (locked)

These seven decisions are inputs to the spec. They cannot be relitigated inside Phase 2 implementation; revisiting any of them requires reopening the brainstorm.

| # | Question | Decision | Reason |
|---|---|---|---|
| 1 | Residual chaos 5-run flake gate | **In scope.** Phase 2 ships a fix; chaos exit criterion includes a green 5-run gate. | Carry-over from master Phase 2 hand-off §3 — best resolved while we're already touching `tests_chaos/`. |
| 2 | `OrphanSweeper` placement | **Move to scheduler.** Worker no longer runs it. | Single-owner background hygiene; eliminates N workers running the same DB query every 30 s. |
| 3 | Cron parser | **`croniter>=2,<7`** added to install_requires. | De-facto Python cron lib; mature DST/tz handling; minimal transitive deps. |
| 4 | Singleton lock model | **TTL=15 s, renew every 5 s, poll every 5 s, lost-lock fence → exit process.** Renewal is Lua check-and-PEXPIRE. | Worst-case takeover ~20 s — comfortably inside master's "~30 s" target with margin for a single missed renewal. |
| 5 | `schedule run-now` | **Calls `conductor.enqueue(...)` directly.** Forward link via `Conductor Schedule.last_job`. | One enqueue path; no schema amendment to master §6.2. |
| 6 | Reaper scope | **Marks workers `STALE`/`GONE` and prunes rows >7 days old.** Does NOT XAUTOCLAIM on behalf of dead workers. | Workers' own per-iteration XAUTOCLAIM covers steady-state; "all workers dead" is an operability problem, not a recovery problem. |
| 7 | Cron timezone + catch-up | **Evaluate in row's timezone, store UTC. Skip-and-resume catch-up.** | Matches Unix `cron`; no surprise re-fire after maintenance windows. |

## 4. Architecture

```
                           ┌────────────────────────────────────────────┐
                           │  bench --site SITE conductor scheduler     │
                           │                                             │
                           │  SET NX EX 15s   conductor:SITE:scheduler:lock
                           │  ┌─────────────────────────────────────────┐│
                           │  │  Lock holder (one of N processes):      ││
                           │  │   • Renewer thread       (every 5 s)    ││
                           │  │   • Delay loop           (every 1 s)    ││
                           │  │   • Cron loop            (every 1 s)    ││
                           │  │   • Reaper loop          (every 60 s)   ││
                           │  │   • Sweeper loop         (every 30 s)   ││
                           │  │  ─ Lost-lock event → exit non-zero ─    ││
                           │  └─────────────────────────────────────────┘│
                           │                                             │
                           │  Non-holders: poll for lock every 5 s.      │
                           └────────────────────────────────────────────┘
                                        │
                                        ▼
       ┌─────────────────────────┬─────────────────────────┬──────────────────────────┐
       │ ZSET                    │ Conductor Schedule       │ Conductor Worker         │
       │ conductor:SITE:scheduled │ DocType (cron walks)     │ DocType (heartbeat scan) │
       │ → XADD streams           │ → conductor.enqueue(...) │ → STALE/GONE / prune     │
       └─────────────────────────┴─────────────────────────┴──────────────────────────┘
```

**One process per site.** Multiple processes may run simultaneously per site; only one holds the lock and runs the loops at a time. Non-holders poll for the lock and become holders if it expires or is released. This is the classic Redis singleton pattern.

**Loops are independent.** Each loop is its own daemon thread; each tick is wrapped in a `try / except: log` so a transient DB or Redis error never crashes the scheduler. Each loop opens its own `frappe.init/connect → … → frappe.db.commit() → frappe.destroy()` cycle (the Werkzeug-Local rule established in master Phase 1 hand-off §5).

**Loops are stateless across ticks.** Source of truth is Redis (ZSET, lock key, workers HSET) and MariaDB (`Conductor Schedule`, `Conductor Worker`, `Conductor Job`). No in-memory state survives a process restart.

## 5. Singleton lock

### 5.1 Key and value

- **Key:** `conductor:{site}:scheduler:lock`
- **Value:** scheduler instance ID — `f"{hostname}:{pid}:{uuid4().hex[:8]}"`
- **TTL:** 15 s (production), overridable for tests.

### 5.2 Operations (`conductor/scheduler_lock.py`)

```python
def acquire(client, site, instance_id, *, ttl: int = 15) -> bool:
    """SET conductor:{site}:scheduler:lock instance_id NX EX ttl. True on win."""

def renew(client, site, instance_id, *, ttl: int = 15) -> bool:
    """Lua: GET == instance_id ? PEXPIRE ttl*1000 : 0. True iff still ours."""

def release(client, site, instance_id) -> bool:
    """Lua: GET == instance_id ? DEL : 0. True iff we deleted our own lock."""
```

All three Lua scripts are single-key (master §3 #15 cluster-compat).

### 5.3 Renewer thread

A daemon thread that calls `renew()` every 5 s. If `renew()` returns `False` (we lost the key — TTL expired due to a paused process, Redis hiccup, clock skew, or a peer stole it), it sets a `lost_lock_event`. The main process awaits this event in addition to `_shutdown`; on either, all four loops drain and the process exits non-zero. The supervisor (bench / systemd) restarts the process, which then re-enters the poll loop.

### 5.4 Worst-case takeover time

```
holder dies → at most TTL=15s for the key to expire → at most 5s for the next
              poller's tick → ≤ 20s total takeover.
```

This satisfies the master §4 Phase 2 exit criterion ("another instance picks up the lock within ~30 s") with a 10 s margin.

## 6. The four loops

### 6.1 Delay loop (1 s)

**Purpose:** Drain `conductor:{site}:scheduled` ZSET → XADD to target queue streams. Replaces the in-worker `DelayDrainer` from Phase 1.

**Pseudocode:**

```python
def delay_loop(redis_client, site, stop_event, lost_lock_event):
    while not (stop_event.is_set() or lost_lock_event.is_set()):
        try:
            due = drain_due_messages(redis_client, site)  # existing helper
            for encoded in due:
                queue = encoded.get("queue") or ""
                if not queue:
                    log.warning("delay_loop_skipped_empty_queue", encoded=encoded)
                    continue
                target = stream_key(site, queue)
                ensure_consumer_group(redis_client, target)
                redis_client.xadd(target, encoded, maxlen=10000, approximate=True)
        except Exception as e:
            log.error("delay_loop_iteration_failed", error=str(e))
        stop_event.wait(1.0)
```

`drain_due_messages` (already shipped in `conductor/scheduled.py`) is reused unchanged. The `DelayDrainer` *class* in that module is deleted; the helper function stays.

### 6.2 Cron loop (1 s)

**Purpose:** Walk `Conductor Schedule` rows; for any whose `next_run_at <= now`, call `conductor.enqueue(...)`, update `last_run_at` / `last_status` / `last_job`, recompute `next_run_at`. Skip-and-resume — never backfills missed runs.

**Tick interval rationale:** Master §4 hints at a 30 s tick. The master also requires "< 2 s drift per run" as Phase 2's cron-throughput exit criterion. The two are inconsistent — at 30 s tick, average drift is ~15 s. We deviate from the master hint and run the cron loop on a 1 s tick so the drift target is actually achievable. The cost is one indexed `SELECT … WHERE enabled=1 AND next_run_at <= NOW()` per second per site, which is negligible against a small `Conductor Schedule` table (typically O(10–100) rows per site).

**Pseudocode:**

```python
def cron_loop(stop_event, lost_lock_event, site, sites_path):
    while not (stop_event.is_set() or lost_lock_event.is_set()):
        try:
            frappe.init(site=site, sites_path=sites_path)
            frappe.connect()
            try:
                now = datetime.now(timezone.utc)
                rows = frappe.db.sql(
                    "SELECT name FROM `tabConductor Schedule` WHERE enabled=1 "
                    "AND next_run_at IS NOT NULL AND next_run_at <= %s",
                    (now.replace(tzinfo=None),), as_dict=True,
                )
                for r in rows:
                    fire_schedule(r["name"], now)
                frappe.db.commit()
            finally:
                frappe.destroy()
        except Exception as e:
            log.error("cron_loop_iteration_failed", error=str(e))
        stop_event.wait(1.0)


def fire_schedule(name, now_utc):
    doc = frappe.get_doc("Conductor Schedule", name)
    try:
        # decode the schedule's stored kwargs using the same msgpack-base64
        # codec used by JobMessage (see conductor/serialization.py); empty
        # string means "no kwargs".
        kwargs = decode_kwargs(doc.kwargs) if doc.kwargs else {}
        job_id = conductor.enqueue(
            doc.method, queue=doc.queue, max_attempts=doc.max_attempts or None, **kwargs,
        )
        doc.db_set("last_run_at", now_utc.replace(tzinfo=None), update_modified=False)
        doc.db_set("last_status", "DISPATCHED", update_modified=False)
        doc.db_set("last_job", job_id, update_modified=False)
    except Exception as e:
        doc.db_set("last_run_at", now_utc.replace(tzinfo=None), update_modified=False)
        doc.db_set("last_status", "DISPATCH_FAILED", update_modified=False)
        log.error("cron_fire_failed", schedule=name, error=str(e))

    next_at = compute_next_run_at(doc.cron_expression, doc.timezone or "UTC", base=now_utc)
    doc.db_set("next_run_at", next_at.replace(tzinfo=None), update_modified=False)
```

`next_run_at` is the only field that drives firing — the cron expression is re-evaluated on every fire, so an admin who edits the expression on a row only needs to call `bench conductor schedule run-now <name>` (or wait for the next cycle) to have the new schedule reflected.

**Schedule onboarding:** When a `Conductor Schedule` is created or its `cron_expression`/`timezone`/`enabled` change, the DocType controller recomputes `next_run_at` (see §8.3). That keeps the cron loop purely a "fire and recompute" walker without a separate "newly-created" handler.

### 6.3 Reaper loop (60 s)

**Purpose:** Mark `Conductor Worker.status` `STALE` (heartbeat older than 30 s) or `GONE` (older than 120 s); delete `Conductor Worker` rows whose `last_heartbeat` is older than 7 days. Does **not** touch streams.

```python
def reaper_loop(stop_event, lost_lock_event, site, sites_path):
    STALE_AGE = 30      # seconds
    GONE_AGE = 120
    PRUNE_AGE = 7 * 24 * 3600
    while not (stop_event.is_set() or lost_lock_event.is_set()):
        try:
            frappe.init(site=site, sites_path=sites_path)
            frappe.connect()
            try:
                now = datetime.now()
                gone_cut  = now - timedelta(seconds=GONE_AGE)
                stale_cut = now - timedelta(seconds=STALE_AGE)
                prune_cut = now - timedelta(seconds=PRUNE_AGE)

                frappe.db.sql(
                    "UPDATE `tabConductor Worker` SET status='GONE' "
                    "WHERE site=%s AND status<>'GONE' AND last_heartbeat < %s",
                    (site, gone_cut),
                )
                frappe.db.sql(
                    "UPDATE `tabConductor Worker` SET status='STALE' "
                    "WHERE site=%s AND status='ALIVE' AND last_heartbeat < %s "
                    "  AND last_heartbeat >= %s",
                    (site, stale_cut, gone_cut),
                )
                frappe.db.sql(
                    "DELETE FROM `tabConductor Worker` "
                    "WHERE site=%s AND last_heartbeat < %s",
                    (site, prune_cut),
                )
                frappe.db.commit()
            finally:
                frappe.destroy()
        except Exception as e:
            log.error("reaper_loop_iteration_failed", error=str(e))
        stop_event.wait(60.0)
```

Worker reclamation is **not** the reaper's job. Workers run XAUTOCLAIM on every iteration; as long as ≥1 worker is alive on a queue, stalled messages from dead peers are reclaimed within `_AUTOCLAIM_IDLE_MS` (60 s production). If the entire fleet dies, that's an operational alert problem; restarting workers resumes reclamation.

### 6.4 Sweeper loop (30 s)

**Purpose:** Re-XADD `Conductor Job` rows orphaned by the dispatch dual-write crash window (master §3 #12 option C). Replaces the in-worker `OrphanSweeper` from Phase 1.

```python
def sweeper_loop(redis_client, stop_event, lost_lock_event, site, sites_path):
    while not (stop_event.is_set() or lost_lock_event.is_set()):
        try:
            frappe.init(site=site, sites_path=sites_path)
            frappe.connect()
            try:
                sweep_orphans(redis_client, site)  # existing helper, reused
            finally:
                frappe.destroy()
        except Exception as e:
            log.error("sweeper_loop_iteration_failed", error=str(e))
        stop_event.wait(30.0)
```

`sweep_orphans` (already shipped in `conductor/sweeper.py`) is reused unchanged. The `OrphanSweeper` *class* in that module is deleted; the helper function stays.

## 7. Cron module (`conductor/cron.py`)

```python
from datetime import datetime, timezone
import zoneinfo
from croniter import croniter

def compute_next_run_at(cron_expression: str, tz_name: str = "UTC",
                        base: datetime | None = None) -> datetime:
    """Return the next fire time strictly after `base` (default: now), as UTC.
    `base` may be naive (treated as UTC) or tz-aware. Raises ValueError on
    malformed cron_expression."""
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

Skip-and-resume catch-up is implicit: `get_next(base)` always returns a time strictly after `base = now`, so missed runs (where `last_run_at < now - one_period`) are silently skipped.

Malformed `cron_expression` raises `ValueError` from `croniter`. The cron loop catches per-row errors (so one bad row doesn't kill the loop) and logs `cron_eval_failed`; the row's `next_run_at` is left untouched until an admin fixes it via Desk.

## 8. `Conductor Schedule` DocType

### 8.1 Schema

Per master §6.6 — **no field changes**. Restated for clarity:

| Field | Type | Notes |
|---|---|---|
| `name` | Data (primary, autoname=`SCHED-.######`) | |
| `enabled` | Check | Default 1 |
| `cron_expression` | Data | E.g., `0 */5 * * *` |
| `timezone` | Data | Default `UTC` |
| `method` | Data | Dotted path |
| `args` | Long Text | msgpack-base64 (always `""` in v1; positional args unused) |
| `kwargs` | Long Text | msgpack-base64 |
| `queue` | Link → `Conductor Queue` | Required |
| `max_attempts` | Int | Optional override; falls back to queue defaults via dispatcher |
| `last_run_at` | Datetime | |
| `last_status` | Select: `DISPATCHED` / `DISPATCH_FAILED` (text-only field, no link to Job state) | |
| `last_job` | Link → `Conductor Job` | |
| `next_run_at` | Datetime (indexed) | Source of cron-loop selection |
| `description` | Small Text | |

### 8.2 Permissions

Same pattern as `Conductor Queue`:
- System Manager — full CRUD.
- Conductor Operator — read + report only.

### 8.3 Controller (`conductor/conductor/doctype/conductor_schedule/conductor_schedule.py`)

```python
from frappe.model.document import Document
from conductor.cron import compute_next_run_at

class ConductorSchedule(Document):
    def validate(self):
        if not self.enabled:
            return
        if not self.cron_expression:
            frappe.throw("cron_expression required")
        # Validate by attempting to compute next_run_at now. Throws on bad expr.
        next_at = compute_next_run_at(self.cron_expression, self.timezone or "UTC")
        self.next_run_at = next_at.replace(tzinfo=None)

    def on_change(self):
        # If user toggled enabled or edited cron/tz post-save, recompute.
        if self.has_value_changed("cron_expression") \
           or self.has_value_changed("timezone") \
           or self.has_value_changed("enabled"):
            if self.enabled:
                next_at = compute_next_run_at(self.cron_expression, self.timezone or "UTC")
                self.db_set("next_run_at", next_at.replace(tzinfo=None), update_modified=False)
            else:
                self.db_set("next_run_at", None, update_modified=False)
```

`validate` runs on save; an admin who pastes `not a cron expr` gets a `ValueError` surfaced as a Frappe validation error. `on_change` keeps `next_run_at` consistent without forcing the cron loop to do this work.

## 9. CLI surface

### 9.1 `bench conductor scheduler`

`commands/scheduler.py`:

```python
@click.command("scheduler")
@click.option("--lock-ttl-seconds", default=15, type=int)
@click.option("--renew-interval-seconds", default=5, type=int)
@click.option("--poll-interval-seconds", default=5, type=int)
@pass_context
def scheduler_command(ctx, lock_ttl_seconds, renew_interval_seconds, poll_interval_seconds):
    """Run a Conductor scheduler process."""
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

The intervals are CLI options (not just constants) so chaos tests can tighten them: `--lock-ttl-seconds=3 --renew-interval-seconds=1 --poll-interval-seconds=1` keeps the chaos test fast.

### 9.2 `bench conductor schedule`

`commands/schedule.py`:

```python
@click.group("schedule")
def schedule_group():
    """Manage Conductor schedules."""

@schedule_group.command("list")
@pass_context
def schedule_list(ctx):
    """Print all schedules: name | enabled | cron | tz | next_run_at | last_status."""
    ...

@schedule_group.command("enable")
@click.argument("name")
@pass_context
def schedule_enable(ctx, name):
    """Enable a schedule and recompute next_run_at."""
    ...

@schedule_group.command("disable")
@click.argument("name")
@pass_context
def schedule_disable(ctx, name):
    """Disable a schedule. next_run_at is cleared."""
    ...

@schedule_group.command("run-now")
@click.argument("name")
@pass_context
def schedule_run_now(ctx, name):
    """Fire the schedule's payload via conductor.enqueue, out-of-band of cron."""
    ...
```

`run-now` does **not** affect cron cadence — it does not touch `last_run_at` (so as not to confuse the cron-loop "did we just run this" check) but does update `last_job` and `last_status` (`DISPATCHED` on success, `DISPATCH_FAILED` if `conductor.enqueue` raises). The schedule's next cron fire stays on its UTC schedule.

> NOTE on `run-now` semantics: an alternative behaviour would be to also bump `last_run_at`, treating it like a cron fire. We pick the conservative option — `run-now` is for ad-hoc dispatching and tests; humans should not need to think about whether it postpones the next cron fire.

`commands/__init__.py` registers both new commands:

```python
from conductor.commands.scheduler import scheduler_command
from conductor.commands.schedule import schedule_group

conductor_group.add_command(scheduler_command)
conductor_group.add_command(schedule_group)
```

## 10. Worker changes

`conductor/worker.py`:

- **Remove** `from conductor.scheduled import DelayDrainer, schedule_message` → keep only `schedule_message` (still used by `_schedule_retry`).
- **Remove** `from conductor.sweeper import OrphanSweeper`.
- **Remove** the three `drainer = DelayDrainer(...)`, `sweeper = OrphanSweeper(...)` start/stop blocks in `run_worker`.
- **Keep** `CancelPoller` (cancellation is per-worker, not site-level).
- **Keep** `_register_worker`, heartbeat (every 5 s), `_mark_worker_gone` on shutdown.
- **Keep** `_reclaim_into_pool` (per-iteration XAUTOCLAIM).
- **Modify `_heartbeat`** to also reset `status` to `ALIVE` on every heartbeat write. Without this, a worker that the reaper marked `STALE` (e.g., during a long GC pause) would stay `STALE` forever in Desk even after it resumes heartbeating. Reset is unconditional — `last_heartbeat = now, status = 'ALIVE'` — and atomic via a single `set_value` call.

`conductor/scheduled.py`:
- **Keep** `schedule_message`, `drain_due_messages`, `scheduled_redis_key`.
- **Remove** the `DelayDrainer` class (moved into `conductor/scheduler.py`).

`conductor/sweeper.py`:
- **Keep** `sweep_orphans` and helpers.
- **Remove** the `OrphanSweeper` class (moved into `conductor/scheduler.py`).

## 11. Public API surface (delta from Phase 1)

**Added:**
- `bench conductor scheduler` (long-running daemon)
- `bench conductor schedule list / enable / disable / run-now`
- `Conductor Schedule` DocType (Desk-creatable)
- `conductor.cron.compute_next_run_at` (used internally + by tests)

**Unchanged:**
- `conductor.enqueue`, `conductor.context`, `conductor.job`, `conductor.cancel`, `conductor.RetryPolicy`, `conductor.frappe_compat.enqueue`.
- All Phase 1 DocType schemas, the state machine, the stream message format, the Redis key topology.

**Removed (internal only):**
- `conductor.scheduled.DelayDrainer` class.
- `conductor.sweeper.OrphanSweeper` class.

These deletions are safe — both classes were only constructed inside `conductor.worker.run_worker` and are not part of any public API.

## 12. File tree

### 12.1 New files

```
apps/conductor/conductor/
├── scheduler.py                # entry: run_scheduler(site, …); owns four loops + renewer
├── scheduler_lock.py           # acquire / renew (Lua) / release (Lua)
├── cron.py                     # compute_next_run_at(expr, tz, base) -> UTC datetime
├── conductor/doctype/conductor_schedule/
│   ├── __init__.py
│   ├── conductor_schedule.json
│   └── conductor_schedule.py   # validate() + on_change() recomputes next_run_at
└── commands/
    ├── scheduler.py            # bench conductor scheduler
    └── schedule.py             # bench conductor schedule list/enable/disable/run-now

apps/conductor/tests/
├── test_cron.py                # compute_next_run_at across tz, DST, malformed expr
├── test_scheduler_lock.py      # acquire/renew/release + two-instance contention
├── test_scheduler_loops.py     # delay/cron/reaper/sweeper loops with mocked clock
├── test_schedule_doctype.py    # validate(), on_change() recomputes next_run_at
└── test_run_now.py             # run-now hits conductor.enqueue and updates last_job

apps/conductor/tests_chaos/
└── test_scheduler_handoff.py   # kill scheduler-A → scheduler-B takes lock ≤ 20 s
```

### 12.2 Edited files

```
apps/conductor/conductor/worker.py            # drop DelayDrainer + OrphanSweeper threads
apps/conductor/conductor/scheduled.py         # drop DelayDrainer class; keep helpers
apps/conductor/conductor/sweeper.py           # drop OrphanSweeper class; keep helpers
apps/conductor/conductor/commands/__init__.py # register two new commands
apps/conductor/conductor/modules.txt          # (no change — Conductor module already exists)
apps/conductor/pyproject.toml                 # add croniter>=2,<7 to install_requires
apps/conductor/tests_chaos/conftest.py        # XGROUP DESTROY per-test + tighter teardown
```

## 13. Test plan

### 13.1 Unit tests (no Redis subprocess; uses fakeredis + in-process Frappe)

**`test_cron.py`:**
- `compute_next_run_at("* * * * *", "UTC")` → returns now+(<60s) UTC.
- `compute_next_run_at("0 9 * * *", "America/New_York")` at noon UTC → returns 14:00 UTC (9 AM ET) or 13:00 UTC (DST). Verify both DST transitions explicitly.
- `compute_next_run_at("@hourly", "UTC")` → top of next hour.
- Malformed expression raises `ValueError`.
- Unknown tz silently falls back to UTC (already covered by `zoneinfo.ZoneInfoNotFoundError` catch).

**`test_scheduler_lock.py`:**
- `acquire` succeeds on empty key; second `acquire` from a different instance fails.
- `renew` returns `True` while we own the key; `False` after the owner is overwritten.
- `release` deletes only when we own the key; second release returns `False`.
- TTL expiry: set TTL=1s, `acquire` from instance A, sleep 1.2s, `acquire` from instance B succeeds.

**`test_scheduler_loops.py`:**
- Delay loop: ZADD 5 messages with score=now-1s, run one iteration, assert all five XADDed and the ZSET is empty.
- Cron loop: insert two `Conductor Schedule` rows (one due, one not), run one iteration, assert the due one's `last_job` is set and a `Conductor Job` row exists.
- Reaper loop: insert four `Conductor Worker` rows with `last_heartbeat` ages 5s/45s/180s/8d, run one iteration, assert statuses are `ALIVE/STALE/GONE` and the 8-day row was deleted.
- Heartbeat resets STALE → ALIVE: insert a worker row with status=`STALE` and last_heartbeat=now-45s; call `_heartbeat(worker_id)`; assert the row's status is now `ALIVE` and `last_heartbeat` is recent.
- Sweeper loop: insert one orphan `Conductor Job` row (status=QUEUED, redis_msg_id=NULL, enqueued_at=now-1m), run one iteration, assert XADD happened and `redis_msg_id` is populated.

**`test_schedule_doctype.py`:**
- Insert with `cron_expression="* * * * *"` populates `next_run_at` automatically.
- Insert with `cron_expression="not valid"` raises Frappe validation error.
- `on_change` recomputes `next_run_at` when `cron_expression` is updated.
- Toggling `enabled` from 1 → 0 clears `next_run_at`; 0 → 1 recomputes it.

**`test_run_now.py`:**
- `bench conductor schedule run-now <name>` calls into `conductor.enqueue`; resulting `Conductor Job` row exists; the schedule's `last_job` is populated and `last_status="DISPATCHED"`.
- `last_run_at` is **not** updated by `run-now` (verifies the conservative semantics).

### 13.2 Chaos tests

**`tests_chaos/test_scheduler_handoff.py`:**

```
scenario:
  - spawn scheduler-A (--lock-ttl-seconds=3 --renew-interval-seconds=1 --poll-interval-seconds=1)
  - wait until lock key exists with value=A's instance_id  (≤ 2 s)
  - kill -9 scheduler-A
  - spawn scheduler-B (same flags)
  - assert lock key value flips to B's instance_id within 5 s
  - ZADD a due message; assert it lands on the queue stream within 2 s
```

This single test covers the master Phase 2 exit criterion ("another instance picks up the lock within ~30 s") and verifies the delay loop is healthy under the new owner.

### 13.3 Flake-gate fix (`tests_chaos/conftest.py`)

Two changes, targeting the two surviving hypotheses from master Phase 2 hand-off §3:

1. **`XGROUP DESTROY` on test teardown.** Add a per-test teardown step: enumerate every existing `conductor:{site}:stream:*` and `conductor:{site}:dlq:*` key, run `XGROUP DESTROY <stream> conductor` against each (ignore `NOGROUP` errors), *then* delete the key. This scrubs the PEL of stale message-IDs that survived the previous test's wipe — the residual flake hypothesis from master Phase 2 hand-off §3 #2. The next test's `ensure_consumer_group` lazily recreates the group on first XADD, so there's no setup work needed in the new test.

2. **Tighter subprocess teardown.** Replace `proc.wait(timeout=5)` with a poll loop that waits until `os.killpg(pid, 0)` raises `ProcessLookupError` (process group is empty), with a hard ceiling of 10 s. Eliminates hand-off §3 #1.

The chaos exit criterion now includes a `pytest tests_chaos --count=5` green run (using `pytest-repeat` already in dev deps). Phase 2 is not done until this gate is green twice in a row on a clean checkout.

### 13.4 Coverage of frozen contracts

After Phase 2 lands, this still holds:
- All Phase 1 chaos tests pass (kill-during-run, retry-exhausts-to-DLQ, dispatch-idempotency).
- All Phase 0 tests pass.
- Doctor still exits 0 (`bench --site SITE conductor doctor --demo`). The doctor command is not extended in Phase 2 — checking scheduler health is a Phase 3/4 concern.

## 14. Operator UX

### 14.1 Starting the scheduler

A bench will need to add a Procfile entry alongside the existing worker:

```
conductor_scheduler: bench --site frappe.localhost conductor scheduler
conductor_worker:    bench --site frappe.localhost conductor worker --queue default
```

Documenting this in `apps/conductor/README.md` is part of the implementation plan.

### 14.2 Common operator commands

```
$ bench --site SITE conductor schedule list
NAME             ENABLED  CRON              TZ            NEXT_RUN_AT             LAST_STATUS
nightly-rollup   1        0 2 * * *         America/NewYork 2026-04-28 06:00:00 UTC DISPATCHED
hourly-cleanup   1        0 * * * *         UTC           2026-04-27 23:00:00 UTC DISPATCHED

$ bench --site SITE conductor schedule run-now nightly-rollup
fired: nightly-rollup → job 9f2…

$ bench --site SITE conductor schedule disable nightly-rollup
disabled: nightly-rollup
```

## 15. Risks and accepted limitations

1. **Scheduler is a single point of failure.** The lock holder is the only producer for the delay loop. If Redis goes hard-down, no scheduler can hold the lock and retries do not fire. This is the same dependency as the worker fleet (which also requires Redis). Documented; acceptable for v1.

2. **Cron loop tick is 1 s** (deviating from master §4's 30 s hint, see §6.2 rationale). Worst-case drift is therefore ~1 s, average ~0.5 s — well inside the master's "< 2 s drift" target. Loosening the tick (e.g., to reduce DB SELECTs on a quiet site) widens the drift; the value lives as a constant in `scheduler.py` for easy tuning.

3. **No built-in catch-up for missed runs.** Per Q7, this is by design. Workloads needing every-tick guarantees should be event-driven. Documented in the `Conductor Schedule` field help text.

4. **`run-now` does not bump `last_run_at`.** A user who runs `run-now` immediately before a cron fire might see two jobs run within seconds. Acceptable; same behaviour as Frappe's "enqueue ad-hoc" pattern.

5. **Scheduler does not self-heal a dead-fleet stuck-PEL situation.** Per Q6, this is operator-fix territory. The scheduler does mark workers `GONE` so the operator can see it in Desk.

6. **Reaper deletes `Conductor Worker` rows >7 days old.** A long-disconnected worker that comes back will re-insert via `_register_worker`. There is no historical "this worker existed once" record after pruning. Acceptable — we have `worker_id` stamped on every `Conductor Job` and `Conductor Job Run` row already.

7. **Schedule rows only refer to Python methods**, identical to `frappe.enqueue`'s mental model. Calling shell scripts or external endpoints is out of scope.

8. **Cron is at-least-once across scheduler crashes.** `fire_schedule` calls `conductor.enqueue(...)` *before* writing the new `next_run_at`. If the lock holder crashes between those two writes, the next holder sees the unchanged `next_run_at <= now` and re-fires the schedule. `Conductor Schedule` has no `idempotency_key` field (master §6.6), so the dispatcher's idempotency check is bypassed — both fires produce distinct `Conductor Job` rows. Workloads that cannot tolerate a double-fire after a scheduler crash should make their `method` idempotent (the natural Frappe pattern), or compute an idempotency key per fire by setting `idempotency_key` in their decorator and having it derive from a time-bucketed value (e.g., `f"my-job:{now_iso_minute}"`). The reverse choice — write `next_run_at` first, then enqueue — would convert "double-fire on crash" into "missed-fire on enqueue failure", which we judge worse: silent miss is harder to detect than duplicate execution.

## 16. Exit criteria

A Phase 2 ship is gated on **all** of:

- A `Conductor Schedule` row with `cron_expression="* * * * *"` runs ≥ 60 times in an hour with average drift < 2 s, observable as `Conductor Job` rows linked back via `last_job`.
- The chaos test `test_scheduler_handoff.py` passes: kill scheduler-A, scheduler-B picks up the lock within 5 s (with test-time intervals; ≤ 20 s with production intervals), and a due ZSET entry is drained.
- All Phase 1 chaos tests still pass.
- `pytest tests_chaos --count=5` is green twice in a row on a clean checkout.
- All unit tests in §13.1 are green.
- `bench --site SITE conductor doctor --demo` still exits 0.
- The in-worker `DelayDrainer` and `OrphanSweeper` threads are deleted (verified by grep on `worker.py`).

## 17. Implementation order (overview)

The `superpowers:writing-plans` cycle that follows this spec produces the actual TDD task queue. As a guide for that plan:

1. `conductor/cron.py` + `tests/test_cron.py` (no Redis, no DocType — pure logic, fastest TDD red-green).
2. `conductor/scheduler_lock.py` + `tests/test_scheduler_lock.py` (fakeredis + Lua, requires `lupa`; covered).
3. `Conductor Schedule` DocType + controller + `tests/test_schedule_doctype.py`.
4. `conductor/scheduler.py` skeleton (run_scheduler, lock-hold lifecycle, lost-lock fence) + integration test for the lifecycle.
5. Each loop in turn (delay → cron → reaper → sweeper), each with its `tests/test_scheduler_loops.py` section.
6. `commands/scheduler.py` and `commands/schedule.py` + `tests/test_run_now.py`.
7. Rip `DelayDrainer` and `OrphanSweeper` out of `worker.py`. Re-run all Phase 1 chaos tests.
8. `tests_chaos/conftest.py` flake-gate fix; verify `pytest tests_chaos --count=5` green.
9. `tests_chaos/test_scheduler_handoff.py`; verify exit criterion.
10. Update `apps/conductor/README.md` with Procfile entry and CLI examples.

## 18. Frozen contracts honoured (do not violate)

- All 20 master cross-cutting decisions stand (master §3).
- Stream message format unchanged; `schema_version=1`.
- Redis key topology unchanged (master §8) — `conductor:{site}:scheduler:lock` was already declared as a Phase 2+ key.
- DocType schemas unchanged from master §6.
- Public API additions only; no removals.
- Phase 1 retry/DLQ/cancellation state machine unchanged.
- MariaDB DATETIME `_now_naive()` rule preserved in the new loops.
- ThreadPoolExecutor / pool-thread `frappe.init/connect/destroy` rule preserved in every loop.

## Change Log

| Date | Change | Author |
|---|---|---|
| 2026-04-27 | Initial Phase 2 — Scheduling spec. | osama.m@aau.iq |
