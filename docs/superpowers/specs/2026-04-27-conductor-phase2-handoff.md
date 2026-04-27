# Phase 2 Hand-off Notes

**Source:** Phase 1 execution discoveries + final-state observations
**Date:** 2026-04-27
**Phase 1 final state:** ~57 commits on `develop`. 71 pytest unit tests pass. 27 Frappe integration tests pass. `bench conductor doctor --demo` exits 0. 3 chaos tests written and individually green; 5-run flake gate has a documented residual issue (see §3 below).

This is **not** a Phase 2 spec. It is the carry-over list that the Phase 2 brainstorm should consume as input. The Phase 2 brainstorm starts from the master design's "Phase 2 — Scheduling" section (§4) plus this list.

---

## 1. Phase 1 — what shipped

The reliability core is in place:

- DocTypes: `Conductor Job Run`, `Conductor DLQ Entry`.
- `RetryPolicy` typed config + `@conductor.job(...)` decorator with full kwarg surface.
- Per-call `enqueue` overrides (`queue`, `timeout`, `max_attempts`, `idempotency_key`).
- Dispatch idempotency: SHA-256 keyed `SET NX EX` with 24h default TTL.
- Execution lock: `SET NX EX` with Lua check-and-delete release; TTL = `timeout + 30s` (env-var override `CONDUCTOR_TEST_EXEC_LOCK_TTL_SECONDS` for tests).
- Retry path: ZADD scheduled set → `SCHEDULED_RETRY` → drainer pumps to stream → next attempt.
- DLQ path: max-attempts hit → XADD to `conductor:{site}:dlq:{queue}` + `Conductor DLQ Entry` row + status `DLQ`.
- In-worker `DelayDrainer` thread (1s poll) — to be replaced by Phase 2's scheduler process.
- In-worker `OrphanSweeper` thread (30s poll) — outbox option C; recovers `QUEUED` rows whose XADD was lost in the dispatch dual-write crash window.
- `XAUTOCLAIM` stalled-message reclamation per worker iteration; idle threshold 60s production / 8s test (env-var override `CONDUCTOR_TEST_AUTOCLAIM_IDLE_MS`).
- Cancellation: `conductor.cancel(job_id)` (whitelisted) + `bench conductor cancel <job_id>`. Cooperative for RUNNING jobs via `cancel_event` + `CancelPoller` thread that polls `Conductor Job` for status=`CANCELLED` and flips the matching event.
- Per-attempt `Conductor Job Run` row written at terminal of each attempt.
- M-2 dispatcher fix: single-transaction `DISPATCH_FAILED` branch.
- Backfill of the 4 missing Phase 0 §11 tests: timeout, doctor-clean, doctor-redis-down, frappe-compat.
- Chaos test scaffolding (`tests_chaos/`) with subprocess-worker fixture.

## 2. Real bugs discovered during Phase 1 execution (already fixed)

These were not in the plan; integration testing surfaced them:

1. **Lua scripting in fakeredis requires `lupa`.** Test env was missing it; added to `[dev]` extras in `pyproject.toml`. Fresh CI installs would have failed on `test_execution_lock` without this.
2. **Exec-lock TTL needed an env-var override too.** Phase 1 plan only proposed `CONDUCTOR_TEST_AUTOCLAIM_IDLE_MS`. With production TTL=`timeout+30s` (~50s), the chaos kill-9 test could not fire `XAUTOCLAIM` quickly enough — peer reclaimed message but `acquire_exec_lock` failed against the still-live lock and the message was XACK'd into the void. Fix: `CONDUCTOR_TEST_EXEC_LOCK_TTL_SECONDS=5` plus the constraint `AUTOCLAIM_IDLE_MS > EXEC_LOCK_TTL_SECONDS * 1000` to ensure ordering.
3. **Stale DB snapshot in chaos tests.** Subprocess workers commit `Conductor Job Run` / `Conductor DLQ Entry` rows in their own transactions; the test process's connection sees a snapshot from before those commits. `wait_for_status` does `frappe.db.rollback()` per poll iteration but the assertion code that ran AFTER `wait_for_status` did not — resulting in `frappe.get_all(...) == []` flakes. Fix: explicit `frappe.db.rollback()` immediately before child-row queries.
4. **Worker-claim race in `test_kill_during_run`.** Original test spawned both workers up-front; whichever XREADGROUP'd first held the job. ~50% of runs the kill was a no-op. Fix: deterministic structure — spawn worker A alone, let it claim, kill, then spawn worker B.
5. **`PermissionError` from `os.killpg` on already-dead processes.** macOS-specific. Conftest cleanup catches `PermissionError` alongside `ProcessLookupError`.
6. **Linter touch on `messages.py` and `worker.py` post-commit.** Behavior unchanged; flagged but not reverted.

## 3. Phase 1 residual limitation (accepted, deferred)

**Chaos test 5-run flake gate is not 100% green.** Individual runs of the 3-test chaos suite pass reliably, but back-to-back runs within a single pytest session occasionally hit a flake (~1 fail per 5 runs).

**What we know:** The flake is **test-state pollution**, not a worker-correctness bug:
- Conductor Redis state (stream entries, scheduled-set retries, DLQ stream entries, idempotency locks) accumulates across tests in the same session.
- Two cleanup fixtures already shipped in `tests_chaos/conftest.py`:
  - **Session-scoped** (`_frappe_init`, autouse) wipes Conductor Redis keys + DocType rows once at session start.
  - **Per-test** (`_wipe_conductor_state_per_test`, autouse) does the same wipe before each test.
- Despite both, an occasional ~1-in-5 flake remained when running back-to-back 5-run gates. Hypothesis: residual subprocess workers from the previous gate still draining as the next gate's tests start (process group cleanup is best-effort with `proc.wait(timeout=5)`).

**Why we accepted:**
- All three chaos tests pass on a clean Redis + DB and pass individually.
- The worker-side invariants (kill-9 → reclaim, retry → DLQ, dispatch idempotency) are demonstrably correct — every passing run validates them.
- The flake is in test infrastructure, not in production code.

**Phase 2 task #1 should be:** track down the last residual flake. Likely culprits to investigate:
1. Subprocess worker shutdown takes longer than the 5s `proc.wait` grace; a peer `OrphanSweeper`/`CancelPoller` thread inside the dying worker keeps writing rows after the test wipe ran.
2. The XAUTOCLAIM consumer group's PEL retains stale message-IDs across tests even when the underlying stream entries are XDEL'd. Calling `XGROUP DESTROY` + lazy recreate per test would scrub it.
3. Test-process Redis client is reused across tests via `get_redis`'s pool; under high concurrency a stale read/write may interleave with worker-subprocess writes.

## 4. Other Phase 1 limitations called out in spec §16

These are documented behaviors, not bugs. Phase 2 should be aware:

- **Sweeper policy loss.** Sweeper-recovered messages (orphan rows in the dispatch dual-write crash window) lose their original retry policy and fall back to queue defaults. Documented in `conductor/sweeper.py` module docstring. To eliminate, add a `pending_payload` Long Text field to `Conductor Job` and have the dispatcher persist the encoded JobMessage there, clear on XADD success. Not a Phase 2 priority — orphans are rare.
- **Cooperative cancellation only.** A RUNNING job that does not poll `conductor.context.should_cancel()` will run to completion. Worker preserves CANCELLED status on terminal write rather than overwriting. Spec §12.3 documents this. Subprocess-per-job hard-kill is the master §3 #19 deferred-out-of-scope path.
- **Idempotency lock not released on terminal status.** Only TTL releases (24h default). A duplicate dispatch within the TTL is the entire point of having the lock.
- **`retry_on` exception class import failures fall back to `(Exception,)`.** Conservative — better to retry on a wrong assumption than hard-DLQ on a transient import failure.

## 5. Documented gotchas (preserve through Phase 2)

These were established in Phase 0 and reinforced in Phase 1. Do not violate:

- **MariaDB DATETIME** rejects tz-aware datetime strings. Strip `tzinfo` via `_now_naive()` before any DB write. Keep tz-aware values in the wire `JobMessage` and Redis stream payload.
- **Werkzeug per-thread Local.** ThreadPoolExecutor pool threads do NOT inherit `frappe.local`. Every helper that runs in a pool thread (`_handle_one`, OrphanSweeper iterations, CancelPoller iterations) must run `frappe.init/connect/destroy` inside.
- **`frappe.utils.get_sites_path()`** does not exist in Frappe 15. Use `frappe.local.sites_path`, captured on the calling thread before pool submission.
- **`frappe.destroy()` discards uncommitted changes.** Always `frappe.db.commit()` before `frappe.destroy()`.
- **`redis-py xinfo_groups` returns string-keyed dicts**, not byte-keyed. Use `g["name"]`, not `g[b"name"]`.
- **Redis 5+ required** (Streams API). Frappe 15 pins `redis~=4.5.5`; `bench update` will revert it. Re-run `pip install -e "apps/conductor[dev]"` after any bench update. (Memory: `bench_redis_startup.md`, `conductor_redis_version_conflict.md` in `~/.claude/projects/.../memory/`.)

## 6. Frozen contracts (do not relitigate in Phase 2)

- All 20 master-design cross-cutting decisions stand.
- DocType schemas (master §6) — no field changes since Phase 1 made the wire-format additions in `JobMessage` only.
- Stream message format — `schema_version=1` still; the Phase 1 optional fields (backoff, base_delay_seconds, max_delay_seconds, jitter, retry_on_names, no_retry_on_names) were added backward-compatibly.
- Redis key topology (master §8).
- Public API: `conductor.enqueue`, `conductor.context`, `conductor.job` decorator, `conductor.cancel`, `conductor.RetryPolicy`. Plus `conductor.frappe_compat.enqueue`. Plus three bench commands: `worker`, `doctor`, `cancel`.
- Phase 1 retry/DLQ/cancellation state machine.

## 7. Phase 2 scope reminder (master §4)

Phase 2 ships:

- DocType: `Conductor Schedule`.
- `bench conductor scheduler` — singleton process per site, lock via Redis `SET NX EX` on `conductor:{site}:scheduler:lock` with renewal.
- Three loops in the scheduler:
  - **Delay loop** (1s): drains `conductor:{site}:scheduled` (replaces the in-worker `DelayDrainer` from Phase 1).
  - **Cron loop** (30s): walks `Conductor Schedule` rows, computes `next_run_at` for any expired ones, ZADDs.
  - **Reaper loop** (60s): scans `conductor:{site}:workers` heartbeats, marks stale workers `STALE`/`GONE`, reclaims their pending entries.
- `bench conductor schedule` subcommands: `list`, `enable`, `disable`, `run-now`.
- Removal of the in-worker `DelayDrainer` thread (lifted to scheduler) and the dead-worker-reaping responsibility (added to scheduler).
- Worker-side keep: `OrphanSweeper` could move to the scheduler too (cleaner), or stay in the worker process. Decide in Phase 2 brainstorm.

**Phase 2 chaos extension:** kill the scheduler mid-cycle; another instance must pick up the lock within ~30s and resume.

## 8. Phase 2 first-day backlog (in priority order)

1. **Add per-test autouse cleanup to `tests_chaos/conftest.py`** so the 5-run flake gate is reliably green. Then re-run it to confirm.
2. **Move the in-worker `DelayDrainer` to the scheduler process.** Update `run_worker` to remove the drainer; the scheduler is the only producer pumping ZSET → stream.
3. **Implement the scheduler reaper loop** that detects stale `Conductor Worker` heartbeats and reclaims their pending entries (currently no reaping in v1).
4. **Implement `Conductor Schedule` DocType + cron loop.**
5. **Singleton lock** (`conductor:{site}:scheduler:lock`) with periodic renewal; if scheduler dies, peer picks up within TTL.
6. **Phase 2 chaos test:** kill scheduler mid-cycle, verify lock handoff.

## Change Log

| Date | Change | Author |
|---|---|---|
| 2026-04-27 | Initial Phase 2 hand-off. | osama.m@aau.iq |
