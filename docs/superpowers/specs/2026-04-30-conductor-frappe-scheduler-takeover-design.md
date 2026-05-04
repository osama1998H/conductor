# Conductor takeover of Frappe's scheduler

**Date:** 2026-04-30
**Status:** Design — ready for implementation planning
**Branch:** `v2/certification` (continues the v2 campaign)

## Goal

Replace the interception path (in-process `frappe.enqueue` patch) with an
origination path: Conductor's scheduler reads `tabScheduled Job Type` directly
and dispatches each due row through `conductor.dispatcher.enqueue`. This is
the v2 design pivot from path A to path B forced by an empirical finding —
Frappe's `Scheduled Job Type.enqueue()` calls `enqueue` imported directly
from `frappe.utils.background_jobs`, so monkey-patching `frappe.enqueue`
silently bypasses the scheduler's tick path.

## Why this shape

Path A (interception) requires enumerating every Frappe binding site for
`enqueue`. That set is open-ended: Frappe imports `enqueue` directly in
`Scheduled Job Type`, in the `bench schedule` daemon's request loop, and
potentially in any third-party app's hooks. A `walk(sys.modules)` patch
catches what is loaded at install time but not closures, partials, callback
tables, or future Frappe binding sites introduced by upgrades.

Path B (origination) sidesteps the surface entirely. Conductor's scheduler
already runs four daemon loops over `tabConductor Schedule`. Adding a fifth
loop over `tabScheduled Job Type` is a parallel addition — same pattern,
same dispatch helper (`conductor.dispatcher.enqueue`), same audit chain.
The `tabScheduled Job Type` schema is stable and small. There is one source
of truth and one place a Frappe upgrade could break things — the schema —
which is observable and tested.

## What stays from path A

The in-process `frappe.enqueue` patch already shipped in commits
`d2fb465`, `86296a9`, `a3543db`, `97dccae` is **not** removed. It remains
useful as a complementary catch-net for direct in-process callers —
application code, custom scripts, request handlers that call
`frappe.enqueue` outside the scheduler tick path. The patch's call-time
flag check means it is silent unless explicitly enabled, so it imposes no
behavior change on users who don't opt in.

## Architecture

A new file `conductor/frappe_scheduled_loop.py` ships one loop function
that runs alongside the existing four scheduler daemon loops. It runs once
per tick (default: every 60 seconds, matching Frappe's own tick cadence).

```
┌── bench --site X conductor scheduler ────────────────┐
│   ┌─ leader lock ──────────────────────────────────┐ │
│   │  cron_loop (tabConductor Schedule)             │ │
│   │  delay_loop  (Redis sorted-set drain)          │ │
│   │  reaper_loop (dead workers)                    │ │
│   │  sweeper_loop (orphan jobs)                    │ │
│   │  frappe_scheduled_loop (tabScheduled Job Type) │ │
│   └────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

### `frappe_scheduled_loop` per-tick behavior

```
1. SELECT all rows from tabScheduled Job Type where stopped=0
2. For each row:
   a. Compute is-due based on row.frequency, row.cron_format, row.last_execution
      (mirrors Frappe's own scheduler logic — see Algorithm below)
   b. If due:
      - Call conductor.dispatcher.enqueue(
            row.method, queue=mapped_queue(row), max_attempts=1
        )
      - On success: row.last_execution = now()
      - On dispatch failure: log + leave last_execution unchanged so we retry next tick
3. Commit
```

### Frequency → due-check algorithm

Frappe's `Scheduled Job Type.is_event_due()` already implements this. We
will not reimplement it. Conductor calls `frappe.get_doc(...).is_event_due()`
on each row. This pins us to Frappe's contract: any frequency change in
Frappe (e.g., a new "Hourly Long" interpretation) is automatically picked
up by us.

### Queue mapping

`tabScheduled Job Type` does not have a `queue` field. We map the
`frequency` column to a Conductor queue:

| Frappe frequency | Conductor queue |
|---|---|
| All / Cron | `default` |
| Hourly / Hourly Long / Hourly Maintenance | `default` |
| Daily / Daily Long / Daily Maintenance | `long` |
| Weekly / Weekly Long | `long` |
| Monthly / Monthly Long | `long` |

The mapping is overridable via a `conductor_frappe_schedule_queue_map` site-config key.

### Activation

A new bench-wide flag `conductor_take_over_frappe_scheduler` (in
`common_site_config.json`) gates the loop. When `false` (default), the
loop is registered but exits immediately each tick — zero behavior
change. When `true`, the loop runs.

**The user must also pause Frappe's own scheduler** so the same row does
not fire twice. Documented options:

- Set `pause_scheduler: true` in `common_site_config.json`, OR
- Remove the `schedule:` line from the bench `Procfile`.

The `bench conductor doctor` health-gate (M8 of v2) will assert this
constraint when `conductor_take_over_frappe_scheduler` is true.

### Coordination with the existing leader lock

The new loop runs only on the scheduler's leader instance (same lock the
other four loops use). When the leader fails over, the new loop fails
over with it. No new lock needed.

## Schema interaction

The loop reads three fields per row:

- `name` (PK)
- `method` (the dotted path)
- `frequency` (one of the enum values listed above)
- `cron_format` (only when frequency = `Cron`)
- `last_execution` (datetime, set by us after each successful dispatch)
- `stopped` (boolean filter)

We mutate one field: `last_execution`. We do NOT touch the
`Scheduled Job Log` DocType — Conductor's `Conductor Job` and
`Conductor Job Run` already provide audit. A future enhancement could
write a Scheduled Job Log row for compatibility with Frappe-shaped
tooling, but is out of scope for this design.

## Tests

Unit tests with mocked frappe (no live bench needed):

1. Loop iteration with no due rows is a no-op.
2. One due Daily row → `conductor_enqueue` called once with correct args; `last_execution` updated.
3. Three due rows of mixed frequencies → three `conductor_enqueue` calls; queue assignments match the map.
4. Dispatch failure on one row → `last_execution` unchanged on that row; other due rows still fire.
5. Stopped row never fires regardless of `is_event_due()` result.
6. Loop is a no-op when `conductor_take_over_frappe_scheduler` is unset.
7. Custom queue map override is respected.

Integration test (live bench, manual smoke):

8. Set `conductor_take_over_frappe_scheduler: true`; pause Frappe's scheduler;
   run `bench --site X conductor scheduler`; force a row to be due via
   `last_execution = NULL`; verify a `Conductor Job` row appears within 60s.

## File layout

| File | Status | Responsibility |
|---|---|---|
| `conductor/frappe_scheduled_loop.py` | New | The new loop function + queue map |
| `conductor/scheduler_loops.py` | Modify | `start_all_loops()` registers the new loop |
| `conductor/commands/scheduler.py` | Modify | Reads the activation flag |
| `tests/test_frappe_scheduled_loop.py` | New | Unit tests for the loop |
| `docs/reference-configuration.md` | Modify | Document `conductor_take_over_frappe_scheduler` and the queue map override |
| `docs/roadmap/v2.md` | Modify | Reflect the path A→B pivot in M1 |

## Acceptance criteria

- All seven unit tests pass.
- Integration smoke (test 8 above) creates a Conductor Job row within 60s on the live bench.
- Existing comparative KPI suite still passes — no regression.
- The in-process `frappe.enqueue` patch keeps working when its flag is set;
  this commit does not remove it.

## Out of scope

- Removing the in-process patch (kept as complementary catch-net).
- Writing `Scheduled Job Log` rows (Conductor Job rows are sufficient audit).
- Migrating individual scheduled jobs to `Conductor Schedule` rows (the user can do this manually if they want to take a row off Frappe's schema entirely).
- Per-row queue overrides (the frequency-based map plus a global override is enough for v2).

## Risks

- **Frappe upgrade changes `is_event_due()` semantics.** Mitigation: we call into the live method, so we get the new semantics for free. Detection: a regression appears as duplicate or missing fires; the M2 matrix's natural-cron soak window catches this.
- **`last_execution` race between conductor and a still-running Frappe scheduler.** Mitigation: documented as user-must-pause-Frappe; the doctor health-gate (M8) will assert this. Without the pause, we double-fire. This is a configuration footgun, not a code bug — but the doctor check turns it into a loud failure.
- **One slow `is_event_due()` call blocks the whole loop tick.** Mitigation: the loop runs on one thread, but each tick is bounded by `loop_iter_timeout` (default 30s) and any iter that exceeds it is logged and the next tick proceeds.
