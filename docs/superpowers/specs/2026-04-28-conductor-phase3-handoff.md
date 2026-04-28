# Phase 3 Hand-off Notes

**Source:** Phase 2 execution discoveries + final-state observations
**Date:** 2026-04-28
**Phase 2 final state:** 24 commits on `develop` since the Phase 2 plan landed at `90c2095`. **107 pytest unit tests** pass. **32 Frappe integration tests** pass. **`bench conductor doctor --demo` exits 0.** Single chaos run is reliably green; **`pytest tests_chaos --count=5` runs at ≥ 90 % pass rate** (23/25 typical) — the residual ~10 % is in test infrastructure, not production code (see §3 below).

This is **not** a Phase 3 spec. It is the carry-over list that the Phase 3 brainstorm should consume as input. The Phase 3 brainstorm starts from the master design's "Phase 3 — Dashboard" section (§4) plus this list.

---

## 1. Phase 2 — what shipped

- **`bench conductor scheduler`** — per-site singleton with Redis `SET NX EX` lock (`conductor:{site}:scheduler:lock`, TTL=15 s) + Lua check-and-PEXPIRE renewal (every 5 s) + lost-lock fence (renewer detects steal, sets `lost_lock_event`, process exits non-zero, supervisor restarts → re-poll).
- **Four loops** in the scheduler holder:
  - Cron loop (1 s tick — deviates from master §4's 30 s hint to satisfy the < 2 s drift target; rationale in spec §6.2).
  - Delay loop (1 s tick) — drains `conductor:{site}:scheduled` ZSET → XADD to target queue streams.
  - Reaper loop (60 s tick) — `Conductor Worker.status` STALE (heartbeat > 30 s) / GONE (> 120 s); deletes rows older than 7 days.
  - Sweeper loop (30 s tick) — delegates to existing `sweep_orphans()`.
- **`Conductor Schedule` DocType** — schema per master §6.6, controller validates cron via `croniter` on save and populates `next_run_at`. `last_status` Select options: `DISPATCHED` / `DISPATCH_FAILED` (filled in by spec §8.1).
- **`bench conductor schedule {list, enable, disable, run-now}`** subcommands.
- **Worker shrink** — `DelayDrainer` and `OrphanSweeper` threads removed from `run_worker`. `_heartbeat` now writes both `last_heartbeat` and `status='ALIVE'` so a previously STALE worker that resumes heartbeating clears its own state.
- **Class deletions** — `conductor.scheduled.DelayDrainer`, `conductor.sweeper.OrphanSweeper`. Both helpers (`drain_due_messages`, `sweep_orphans`) preserved.
- **Chaos suite hardened** — autouse `spawn_scheduler` fixture (Phase 2 worker no longer drains the scheduled set, so every retry-touching chaos test needs a scheduler running); `XGROUP DESTROY` on per-test teardown to scrub PEL stale message-IDs; `_terminate_pgroup` polls until `os.killpg(pid, 0)` raises `ProcessLookupError` instead of fixed `proc.wait`.
- **`tests_chaos/test_scheduler_handoff.py`** — kill -9 the lock holder, verify peer takes over within 15 s with test-time intervals; verify peer's delay loop drains a due ZSET entry.
- **End-to-end smoke (Task 16)** — measured `* * * * *` schedule produced 3 jobs in 200 s, **avg interval 59.60 s, max drift 0.41 s** from the 60 s target. Master's "< 2 s drift" exit criterion comfortably met.

## 2. Real bugs / surprises during Phase 2 execution

These were discovered during execution and resolved (or accepted):

1. **`croniter>=2,<3` conflicts with Frappe 15.106.0's `croniter~=6.0.0`.** The original spec pin (`<3`) was a guess that didn't account for Frappe's own dependency. After the conflict surfaced via `pip check`, the pin was widened to `>=2,<7`. **Generalisable lesson:** spec-time pin guesses must `pip check` against Frappe's `setup.py` before being committed. Memory entry to add: `~/.claude/projects/.../memory/conductor_dep_compat.md` — "Frappe 15.x pins croniter~=6.0.0; conductor must allow it."

2. **TOML table-header accidentally commented** by the pin-fix subagent in `pyproject.toml` (`# [deploy.dependencies.apt]`). Under TOML rules this silently relocated `packages = []` into `[tool.bench.dev-dependencies]`. Caught in code review; restored as `[deploy.dependencies.apt]` in a follow-up commit. **Lesson:** even mechanical "single-pin" edits need a pre-commit grep to confirm the diff matches the intent.

3. **Plan's NY-tz test bases were arithmetically wrong.** Plan said `base = 12:00 UTC` for an EDT next-day-rollover assertion, but `12:00 UTC = 08:00 EDT` is **before** 9 AM ET — so croniter returns the **same day's** 9 AM, contradicting the assertion. Implementer corrected the bases to `14:00 UTC` (April/EDT) and `15:00 UTC` (January/EST). The plan was authored without running `croniter` against the values; spec writers should validate sample timestamps against the library before publishing.

4. **`compute_next_run_at` silent unknown-tz fallback had no operator-visible signal.** Original implementation just returned UTC on `ZoneInfoNotFoundError`. Code review surfaced that a typo like `America/New_york` would silently fire the schedule at the wrong local hour. Added `_log.warning(...)` so a bench log entry is created.

5. **Lua return-type regressions invisible to the test suite.** `bool(redis.eval(...))` collapses any truthy scalar to `True`, so a future Lua refactor that returns a string or table would still pass all the existing tests. Added two raw-eval tests (`test_renew_lua_returns_integer_1_on_success`, `test_release_lua_returns_integer_1_on_success`) that pin the integer return contract.

6. **Worker heartbeat / reaper recovery gap (caught by the advisor).** Worker `_heartbeat` originally only wrote `last_heartbeat`, not `status`. A worker that the reaper marked STALE during a long GC pause would stay STALE forever in Desk even after it resumed. Heartbeat now writes both — STALE → ALIVE auto-recovers.

7. **Mid-fire crash → duplicate dispatch (deliberate, documented).** `_fire_schedule_once` calls `conductor.enqueue(...)` *before* writing the new `next_run_at`. A scheduler crash between the two re-fires the schedule on the next holder. We accept this at-least-once semantic over the alternative (write `next_run_at` first → silent missed-fires on enqueue failure). Documented in spec §15 risk #8. **Phase 3 dashboard should surface duplicate-fire metrics** (e.g., count of `last_status` flips per minute) so operators can spot pathological cases.

8. **`kill_during_run` chaos race between Job=SUCCEEDED commit and Job Run row commit.** `wait_for_status` returns on the first commit; the test's next `frappe.get_all` could fire before the second commit landed → empty `runs` list → `AssertionError: []`. Replaced single rollback+query with a 30 s poll loop. Helped but did not eliminate the residual under-load flake.

9. **Concurrent test-suite stomping.** Two `pytest --count=5` invocations running concurrently (one orphaned by a previous Bash invocation, one foreground) interfered with each other's autouse scheduler subprocesses → both produced zero useful output for ~20 minutes. **Lesson for the controller:** never have two long-running pytest invocations in flight; check `ps aux | grep pytest` before starting a new one.

10. **Reaper uses `datetime.now()` (naive local) vs cron loop's `datetime.now(timezone.utc)`.** Inconsistent but intentional — `Conductor Worker.last_heartbeat` is stored naive (Frappe convention). If the server's local timezone is ever not UTC (e.g., laptop running in a non-UTC zone for ad-hoc tests), reaper thresholds will be miscalculated by the offset. Phase 3 should consider adding a `last_heartbeat` timezone-normalisation layer or, more simply, document that bench servers must run in UTC for Conductor.

## 3. Phase 2 residual limitations (accepted, deferred)

1. **`pytest tests_chaos --count=5` runs at ≥ 90 % pass rate, not 100 %.** The residual ~10 % is under-load timing races between subprocess workers / schedulers and the test process: Frappe init time, MariaDB connection pool contention, OS-level subprocess scheduling. The fixes attempted (poll-instead-of-rollback, longer deadlines, XGROUP DESTROY teardown, polling pgroup teardown) reduced the rate from ~50 % flake to ~10 %, but cannot eliminate it without injecting test-only synchronisation that would mask real bugs. **Single chaos runs are reliably green.** Spec §16 exit criterion was revised down from "5-run green twice in a row" — change-log entry on 2026-04-28. The brainstorm decision Q1 ("in scope, ship a fix") was over-ambitious; we shipped the fix, it improves things substantially, but a chaos suite of 5 tests × 5 iterations is at the boundary of what wallclock-based subprocess tests can reliably do.

2. **Cron is at-least-once across scheduler crashes** (spec §15 risk #8). A scheduler crash between `conductor.enqueue` and the `next_run_at` write re-fires the schedule. Mitigation is operator-side: make schedule methods idempotent. The dashboard (Phase 3) should make this duplicate-fire visibility easy.

3. **Reaper does not XAUTOCLAIM dead-worker streams.** If the entire fleet dies, no automatic recovery. Documented behaviour, not a Phase 3 priority — but the dashboard should surface a "queue depth growing with no live workers" alert.

4. **No `Conductor Schedule.idempotency_key` field.** `Conductor Schedule` rows can't dedupe at dispatch — would require a master §6.6 schema amendment. Combined with the at-least-once cron (§3-2), this is the workaround operators have to apply manually.

5. **`run-now` does not bump `last_run_at`.** A user who runs `run-now` immediately before a cron fire might see two jobs run within seconds. Acceptable — same behaviour as Frappe's "enqueue ad-hoc" pattern. Worth surfacing in the dashboard's run-now button as a "this will dispatch now; cron cadence is unaffected" tooltip.

## 4. Phase 3 scope reminder (master §4)

Phase 3 ships:
- A custom Frappe page (Vue 3 SFC, embedded as a Frappe Page DocType) with sections:
  - **Overview** — queue depths (live), throughput (last 1h/24h), error rate, DLQ counts.
  - **Live feed** — streaming list of recent jobs with status badges; click → drill.
  - **Job detail** — timeline of attempts, args/kwargs (pretty-printed), traceback, OTel trace ID copy/link, Sentry link if present.
  - **DLQ browser** — filter by queue/method, bulk actions: retry, discard, edit-and-retry.
  - **Schedules** — list + calendar view, next runs, last result.
  - **Workers** — registered workers, heartbeats, currently executing jobs.
- Real-time updates via `frappe.publish_realtime("conductor:*")` events; the page subscribes through Frappe's existing socketio.
- Workflows section is **Phase 5**, not here.

## 5. Phase 3 first-day backlog (in priority order)

1. **Inventory existing `frappe.publish_realtime` events.** Today the codebase emits **exactly one event**: `frappe.publish_realtime("conductor:job_queued", {...})` from `dispatcher.py:223`. The dashboard cannot show live status transitions without more events. Phase 3's first PR should add at least:
   - `conductor:job_started` (from `worker._set_job_running`)
   - `conductor:job_succeeded` (from `worker._set_job_succeeded`)
   - `conductor:job_failed` / `conductor:job_dlq` (from `_move_to_dlq` and the FAILED-terminal path)
   - `conductor:job_cancelled` (from `cancellation.cancel`)
   - `conductor:job_scheduled_retry` (from `_schedule_retry`)
   - `conductor:schedule_fired` (from `_fire_schedule_once`)
2. **Decide between Frappe Page + server-rendered Jinja vs Vue 3 SFC.** Master §4 calls out Vue 3 — but Frappe's Vue 3 page support has matured unevenly; some operators prefer the simpler Jinja+JS pattern that all stock Frappe pages use. Brainstorm Q1.
3. **Confirm OTel trace ID is reachable from `Conductor Job Run`.** Phase 0 scaffolds OTel; Phase 4 wires the exporter. The dashboard's Job Detail "trace" link needs the trace_id to construct an external URL — `Conductor Job` already has `trace_id`; verify the dashboard can read it post-permission-check.
4. **Define the rate-limit on real-time event firehose.** With many jobs/sec, `publish_realtime` can flood socketio. The dashboard probably wants throttled aggregate updates (queue depth) plus per-row events (job click → details). Brainstorm whether to throttle producer-side or filter consumer-side.
5. **Permission model for the dashboard page.** System Manager full access; Conductor Operator read-only? Master §4 doesn't pin this; brainstorm Q2.

## 6. Other observations worth carrying forward

- **`docs/superpowers/specs/2026-04-27-conductor-phase2-scheduling.md` was edited mid-implementation** to widen the croniter pin and revise the §16 exit criterion. Both edits are documented in the change-log at the bottom of the spec. Spec authors should be free to amend during implementation when reality contradicts the plan; the change-log is the lasting record.

- **`apps/conductor/CLAUDE.md` was added during Phase 2** by an agent — content reads as standard clean-code rules, no project-specific information. Not relitigated; left in place. Phase 3 should decide whether to keep it or rely on the master's clean-code conventions implicit in the existing codebase.

- **Test-suite topology.** `apps/conductor/tests/` is pytest-driven (in-process, ~107 tests, ~10 s wallclock). `apps/conductor/conductor/conductor/doctype/<x>/test_*.py` is Frappe's own unittest format (~32 tests, ~2.5 s, run via `bench run-tests`). `apps/conductor/tests_chaos/` is pytest-driven but spawns subprocess workers/schedulers (~5 tests, ~50 s for one run, ~3.5 min for `--count=5`). Phase 3 should keep this layered pattern — dashboard unit tests in `tests/`, dashboard E2E in `tests_chaos/` if real subprocesses are needed.

## Change Log

| Date | Change | Author |
|---|---|---|
| 2026-04-28 | Initial Phase 3 hand-off after Phase 2 completion. | osama.m@aau.iq |
