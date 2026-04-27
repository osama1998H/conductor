# Phase 1 Hand-off Notes

**Source:** Phase 0 final code review + execution discoveries
**Date:** 2026-04-27
**Phase 0 final state:** 27 commits on `develop`, 36 pytest + 8 Frappe tests pass, `bench conductor doctor --demo` exits 0.

This is **not** a Phase 1 spec. It is the carry-over list that the Phase 1 brainstorm should consume as inputs. The Phase 1 brainstorm starts from the master design §4 "Phase 1 — Reliability core" + this list.

## Decisions deferred from Phase 0

- **Outbox pattern for dispatch (master §3 #12).** Master flagged this as a Phase 1 brainstorm decision. Recommendation: keep current dual-write (DB then XADD), document the failure mode for ops; only adopt outbox if chaos tests in Phase 1 show real DB/Redis interleave bugs.

## Test gaps from Phase 0 spec §11 (must land in Phase 1)

The Phase 0 spec listed eight integration tests under "Frappe site"; four are missing:

1. **`test_worker_records_timeout`** — most material gap. Validates that a job that ignores `should_cancel()` after a 1-second timeout actually transitions to `TIMED_OUT`. Watchdog has unit coverage (`test_context.py::test_watchdog_flips_should_cancel_after_deadline`); the *integration* between watchdog → worker → DB write is unverified.
2. **`test_doctor_clean_install`** — `bench conductor doctor --demo` exits 0 in a clean install (manually verified, not asserted).
3. **`test_doctor_redis_down`** — with Redis stopped, `doctor` exits 1 with the right error.
4. **`test_frappe_compat_shim`** — `conductor.frappe_compat.enqueue("conductor.demo.echo", x=1)` produces an equivalent `Conductor Job`.

Add these as Phase 1 task #1.

## Real bugs discovered during Phase 0 execution (already fixed)

1. **redis-py `xinfo_groups` returns string-keyed dicts**, not byte-keyed. Plan had `g[b"name"]`; corrected to `g["name"]` in `tests/test_streams.py:40,48`.
2. **MariaDB DATETIME columns reject tz-aware datetime strings** (the `+00:00` suffix). Dispatcher and worker strip tzinfo via `_now_naive()` before any DB write; tz-aware values are kept in the JobMessage and Redis stream payload. See `worker.py:36-38`, `dispatcher.py:48-50`.
3. **Werkzeug per-thread Local** (`frappe.local`) does NOT propagate to ThreadPoolExecutor pool threads. `_handle_one` re-runs `frappe.init/connect/destroy` per job. See `worker.py:118-152`.
4. **`frappe.utils.get_sites_path()` doesn't exist in Frappe 15** — use `frappe.local.sites_path`. See `worker.py:176, 213`.
5. **`frappe.destroy()` discards uncommitted changes.** Doctor's `frappe.delete_doc(jid)` for cleanup didn't persist; fixed by adding `frappe.db.commit()` before return. See `doctor.py:101-103`.
6. **Test isolation:** `test_dispatcher` leaves XADDed stream entries behind because it only cleans the DB row, not the stream. `test_worker_e2e.setUp` now `r.delete(stream_key(...))` first. Phase 1's chaos tests must follow the same hygiene.

## Issues from final code review (Phase 1 input, ordered by priority)

### Important (must address early in Phase 1)

- **I-1 (already fixed in commit `85de102`):** Production `run_worker` was joining futures per batch via `f.result()`, collapsing effective concurrency to the batch size and stalling heartbeats. Split via a `wait=` parameter. **Phase 1 chaos tests will exercise this; if anyone reintroduces `f.result()` in `_read_and_dispatch`, regression is silent.**

### Should-Fix before retry logic lands

- **M-2:** `dispatcher.py:109-115` runs three sequential commits in the `DISPATCH_FAILED` path. If the second `db_set` itself fails, the original XADD exception is masked. Replace with a single `frappe.db.set_value("Conductor Job", job_id, {dict})`. Master §3 #11 names this path as critical to the "DB succeeded but XADD failed" guarantee — get it right before adding retry semantics.

### Minor cleanups (Phase 1 first-day batch)

- **M-5:** `conductor/config.py` per spec became `conductor/config/__init__.py` (Frappe scaffold pre-created the package dir). Either revert to a single file or document the package shape in the spec.
- **M-6:** `Procfile.conductor` uses `bench --site all` while `README.md` shows `bench --site <site>`. Reconcile — most likely the Procfile should be a per-site template.
- **M-7:** `setup_otel(...)` is called per-`enqueue`; lift to module init or a check-without-lock fast path.
- **M-8:** `dispatcher.py:116` writes `redis_msg_id` outside the XADD try-block. If that DB write fails post-XADD, status stays `QUEUED` while the message is in the stream. Worker overwrites status on consumption so it's not a correctness bug, but tighten the window.

## Frozen contracts unchanged (do not relitigate in Phase 1)

- All 20 master-design cross-cutting decisions stand.
- DocType schemas (master §6) — `Conductor Job` ships full schema with workflow_run_id/step_id null until Phase 5; do not migrate.
- Stream message format (master §7) — `schema_version=1` stays.
- Redis key topology (master §8).
- Phase 0 public API: `conductor.enqueue(method, *, queue, timeout, **kwargs)` and `conductor.context`.

## Phase 1 scope reminder (master §4)

Phase 1 ships:
- DocTypes: `Conductor Job Run`, `Conductor DLQ Entry`.
- `RetryPolicy` typed config + `@conductor.job(...)` decorator.
- Retry path: ZADD scheduled set; status `SCHEDULED_RETRY`; per-attempt `Conductor Job Run` row.
- A minimal in-worker delay drainer (Phase 2 lifts to scheduler).
- DLQ: max-attempts → XADD to `conductor:{site}:dlq:{queue}` + `Conductor DLQ Entry` row.
- Dispatch idempotency: `SET NX EX` on `conductor:{site}:idem:{key}` (24h default).
- Execution lock: `SET NX EX` on `conductor:{site}:lock:{job_id}`.
- Stalled-message reclamation: `XAUTOCLAIM` per worker iteration.
- Outbox decision settled.
- Chaos tests pass.
