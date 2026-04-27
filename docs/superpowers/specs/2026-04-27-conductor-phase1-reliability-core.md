# Conductor — Phase 1 Spec (Reliability Core)

**Status:** Approved (2026-04-27)
**Phase:** 1 of 6 — Reliability core
**Master design:** `2026-04-27-conductor-master-design.md`
**Phase 0 spec:** `2026-04-27-conductor-phase0-skeleton.md`
**Phase 1 hand-off (Phase 0 carry-over):** `2026-04-27-conductor-phase1-handoff.md`
**Author:** osama.m@aau.iq

This spec lives inside the boundaries of the master design. It does **not** relitigate any of the 20 frozen cross-cutting decisions. Where a Phase 1 decision genuinely extends or refines a master decision (e.g., the JobMessage schema gains optional fields), this is called out explicitly.

---

## 1. Goal

Take the Phase 0 skeleton and make it **actually reliable**. Reliability primitives ship in this phase: declarative retry policies, dead-letter queue, dispatch idempotency, execution locks, stalled-message reclamation, cooperative cancellation, and a sweeper that recovers from the dual-write crash window. Acceptance: a chaos test suite that kill -9's a worker mid-job (and other adversarial patterns) doesn't lose or double-run jobs.

## 2. In Scope

- DocTypes: `Conductor Job Run` (master §6.4), `Conductor DLQ Entry` (master §6.5).
- `RetryPolicy` typed config (frozen dataclass).
- `@conductor.job(...)` decorator with full Phase 1 kwarg surface.
- Per-call `enqueue` overrides for retry-related fields.
- Dispatch idempotency via `SET NX EX` on `conductor:{site}:idem:{sha256}`.
- Execution lock via `SET NX EX` on `conductor:{site}:lock:{job_id}`.
- Retry path: ZADD scheduled set + status `SCHEDULED_RETRY` + per-attempt `Conductor Job Run` row.
- DLQ path: XADD to `conductor:{site}:dlq:{queue}` + `Conductor DLQ Entry` row + status `DLQ`.
- In-worker delay drainer thread (replaced by Phase 2's scheduler process).
- In-worker sweeper for the dispatch dual-write crash window (master §3 #12 outbox decision = option C).
- `XAUTOCLAIM` stalled-message reclamation per worker iteration.
- Cancellation: whitelisted method `conductor.cancel(job_id)` + `bench conductor cancel <job_id>`.
- The four missing Phase 0 §11 integration tests (timeout, doctor-clean, doctor-redis-down, frappe-compat).
- M-2 dispatcher fix (single-transaction DISPATCH_FAILED branch).
- Chaos test suite that gates the phase.

## 3. Out of Scope (Phase 1)

Per master §4, Phase 1 explicitly does **not** ship:

- The dedicated `bench conductor scheduler` process — that's **Phase 2**. The in-worker delay drainer in Phase 1 is a temporary stand-in; Phase 2 lifts the loop into the scheduler and removes the worker thread.
- `Conductor Schedule` DocType, cron evaluation, calendar UI — Phase 2.
- Dead-worker reaping — still Phase 2 (the scheduler's reaper loop).
- Dashboard UI / DLQ browser / DLQ "edit-and-retry" actions — Phase 3.
- OTel exporter, Prometheus metrics, Sentry — Phase 4. (Spans continue to be no-op.)
- Workflows — Phase 5.
- Pool workers, per-tenant rate limits, RQ migration — Phase 6.
- `rate_limit` kwarg on the decorator — Phase 6 (depends on token buckets).
- Subprocess-per-job for hard-kill timeouts — out of scope for v1; cooperative cancellation only (master §3 #19).
- Per-call `idempotency_ttl_seconds` override — site-wide config only in Phase 1.

## 4. Tactical Decisions (Phase-1 only)

These extend the master's frozen decisions; relevant within this phase only.

| # | Decision | Value |
|---|---|---|
| P1-1 | Outbox pattern | **Dual-write + sweeper** (master §3 #12 option C). Sweeper inside worker iteration. |
| P1-2 | `RetryPolicy` shape | Frozen dataclass: `max_attempts`, `backoff` (`exponential`/`linear`/`fixed`), `base_delay_seconds`, `max_delay_seconds`, `jitter` (`none`/`full`/`equal`), `retry_on` (tuple of `Exception` subclasses), `no_retry_on` (tuple). All fields immutable. |
| P1-3 | Decorator API surface | `@conductor.job(queue, max_attempts, backoff, base_delay_seconds, max_delay_seconds, jitter, timeout, idempotency_key, retry_on, no_retry_on)` — 10 kwargs all optional. `rate_limit` deferred to Phase 6. |
| P1-4 | Decorator config flow | **Stamped into the JobMessage at dispatch time** (worker reads message, not decorator metadata at execute time). In-flight retries stay pinned to dispatch-time policy across redeploys. |
| P1-5 | Policy precedence | per-call `enqueue` kwargs > decorator metadata > queue defaults |
| P1-6 | `enqueue` API extension | `conductor.enqueue(method, *, queue=None, timeout=None, max_attempts=None, idempotency_key=None, **kwargs)` — keyword-only, all optional |
| P1-7 | Idempotency key TTL | 24 h default; configurable site-wide via `site_config.conductor.idempotency_ttl_seconds`; **no per-call override** |
| P1-8 | Idempotency key hashing | SHA-256 hex-encoded; Redis key = `conductor:{site}:idem:{hex_hash}` |
| P1-9 | Execution lock | `SET NX EX <timeout_seconds + 30>` on `conductor:{site}:lock:{job_id}`, value = `worker_id`; released on terminal status |
| P1-10 | Stalled-message reclaim | `XAUTOCLAIM` per iteration, `min-idle-time = 60_000 ms`. Per-queue tuning is Phase 2+ if ever needed. |
| P1-11 | Delay drainer location | One thread per worker process, polls `conductor:{site}:scheduled` ZSET every 1 s for due items, ZADD-then-XADD. Phase 2's scheduler process replaces this. |
| P1-12 | Cancellation API | `conductor.cancel(job_id)` (whitelisted) + `bench conductor cancel <job_id>`. Updates `Conductor Job.status = CANCELLED`; a per-worker cancel-poller thread flips matching `cancel_event`s every 1 s; user code checks via `should_cancel()` (cooperative — same primitive as timeout). Functions that never poll will complete normally, but the worker preserves the CANCELLED status on terminal write (it does **not** overwrite to SUCCEEDED/FAILED). UI button is Phase 3. |
| P1-13 | M-2 dispatcher fix | Single `frappe.db.set_value("Conductor Job", id, {dict})` in DISPATCH_FAILED path (replaces three sequential commits) |
| P1-14 | Chaos test framework | pytest fixture in `tests_chaos/` that spawns `bench conductor worker` as a subprocess via `subprocess.Popen`; chaos = `os.kill(pid, signal.SIGKILL)` mid-job; CI-friendly. Five-run flake gate. |
| P1-15 | `Conductor Job Run` write timing | Worker writes the row at the **terminal** of each attempt (success / failed / timed_out). No "started but never finished" rows. |
| P1-16 | RetryPolicy registry | **Inline only** in Phase 1 (no named registry). Shared policies are a Python constant assigned to decorator kwargs. |
| P1-17 | Sweeper threshold | A row is "orphaned" if `status = QUEUED AND redis_msg_id IS NULL AND enqueued_at < now - 30s`. Re-XADD and update `redis_msg_id`. Idempotent against the dual-write race. |

## 5. Public Python API (Phase 1 additions)

```python
import conductor
from conductor.retry import RetryPolicy

# Decorator (new)
@conductor.job(
    queue="critical",
    max_attempts=5,
    backoff="exponential",
    base_delay_seconds=2,
    max_delay_seconds=600,
    jitter="full",
    timeout=300,
    idempotency_key=lambda invoice: f"invoice:{invoice}:email",
    retry_on=(ConnectionError, TimeoutError),
    no_retry_on=(ValueError,),
)
def send_invoice_email(invoice: str): ...

# enqueue() — Phase 0 surface preserved; gains keyword-only overrides
job_id: str = conductor.enqueue(
    "myapp.tasks.send_email",
    queue="critical",      # optional, overrides decorator/queue default
    timeout=600,           # optional override
    max_attempts=10,       # optional override
    idempotency_key="invoice:INV-001:email",  # optional override
    invoice="INV-001",     # remaining kwargs forwarded to the function
)

# Cancellation (new)
ok: bool = conductor.cancel(job_id)
# True  → cancellation transitioned the job to CANCELLED (or set the cooperative flag)
# False → already terminal, or job_id unknown
```

`conductor.context` (from Phase 0) is unchanged. `attempt` will now reflect the actual retry count (was always `1` in Phase 0).

`RetryPolicy` is exposed under `conductor.retry.RetryPolicy` for users who want to construct/inspect a policy programmatically; the canonical interface is the decorator kwargs.

## 6. Out of Scope: API surface that does **not** ship in Phase 1

- `conductor.cancel(job_id, reason=...)` — `reason` arg lands when `Conductor DLQ Entry.review_notes` UI ships in Phase 3.
- Per-call `idempotency_ttl_seconds`.
- Named `RetryPolicy` registry.
- Decorator `rate_limit` kwarg.

## 7. File Tree

```
apps/conductor/conductor/
├── retry.py                    # RetryPolicy dataclass + compute_next_delay()
├── decorator.py                # @conductor.job(...) + per-function metadata registry
├── idempotency.py              # acquire_idem_lock / release_idem_lock helpers
├── execution_lock.py           # acquire_exec_lock / release_exec_lock helpers
├── scheduled.py                # ZSET helpers + delay-drainer thread
├── sweeper.py                  # orphaned-row sweep (outbox option C)
├── cancellation.py             # cancel(job_id) + state machine guard
├── api.py                      # extends Phase 0 re-exports
├── __init__.py                 # extends Phase 0 re-exports
├── messages.py                 # extends with retry/idempotency optional fields
├── dispatcher.py               # extends: idempotency check, policy resolution, M-2 fix
├── worker.py                   # extends: exec lock, retry/DLQ paths, XAUTOCLAIM, drainer/sweeper threads
├── hooks.py                    # extends: register cancel command + whitelisted method
├── commands/
│   ├── cancel.py               # `bench conductor cancel <job_id>`
│   └── __init__.py             # extends to include cancel_command
└── conductor/doctype/
    ├── conductor_job_run/      # NEW (master §6.4)
    └── conductor_dlq_entry/    # NEW (master §6.5)

apps/conductor/tests/                # pytest unit (no Frappe)
├── test_retry.py
├── test_idempotency.py
├── test_execution_lock.py
├── test_scheduled.py
├── test_decorator.py
└── test_sweeper.py

apps/conductor/tests_chaos/          # NEW directory; subprocess-driven
├── conftest.py                      # subprocess-worker fixture
├── test_kill_during_run.py
├── test_retry_exhausts_to_dlq.py
└── test_dispatch_idempotency.py
```

DocType integration tests live in their respective DocType folders per Frappe convention.

## 8. DocType Specs

Schemas come straight from the master design — Phase 1 ships exactly what master §6.4 and §6.5 specify, no field changes:

- **`Conductor Job Run`** → master §6.4 (16 fields, including `sentry_event_id` and `sentry_url` which stay null until Phase 4).
- **`Conductor DLQ Entry`** → master §6.5 (15 fields, including `reviewed_by`/`reviewed_at`/`review_notes` which the Phase 3 UI will populate).

Permissions for both: System Manager (full); Conductor Operator (read + report). DLQ "retry/discard/edit-and-retry" actions are Phase 3 buttons.

## 9. Stream Message Schema — Phase 1 Additions

Master §7 listed the Phase 0 fields. Phase 1 adds the following **optional** fields to the wire format. All are str-encoded (Redis Stream constraint) and may be empty/zero-length when not used. The decoder treats missing fields as None/empty/default — **fully backward-compatible** with Phase 0 messages still in queues during a rolling deploy. **No `schema_version` bump** (still `"1"`).

| Field | Type (wire) | Meaning | Phase 0 default |
|---|---|---|---|
| `idempotency_key` | str (already in §7) | Now actually populated (was `""` in Phase 0) | `""` if not set |
| `backoff` | str (`exponential`/`linear`/`fixed`/`""`) | Backoff strategy for retries | `""` (worker falls back to queue default) |
| `base_delay_seconds` | str(int) | First-retry delay base | `"0"` |
| `max_delay_seconds` | str(int) | Cap | `"0"` |
| `jitter` | str (`none`/`full`/`equal`/`""`) | Jitter strategy | `""` |
| `retry_on_names` | str (JSON list[str]) | Fully-qualified Exception class paths to match | `"[]"` |
| `no_retry_on_names` | str (JSON list[str]) | Exception class paths to **never** retry | `"[]"` |

The master design's §7 will gain a footnote acknowledging these Phase 1 additions; this is not a schema-version bump because:
1. Phase 0 messages decode correctly under the Phase 1 decoder (missing fields default).
2. Phase 1 messages decode correctly under a hypothetical pinned-Phase-0 decoder (those decoders only check `_REQUIRED_FIELDS`, which is unchanged).

## 10. RetryPolicy

```python
@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    backoff: Literal["exponential", "linear", "fixed"] = "exponential"
    base_delay_seconds: int = 2
    max_delay_seconds: int = 600
    jitter: Literal["none", "full", "equal"] = "full"
    retry_on: tuple[type[BaseException], ...] = (Exception,)  # default: any non-no_retry_on
    no_retry_on: tuple[type[BaseException], ...] = ()

    def compute_next_delay(self, attempt: int) -> float:
        """Return the seconds to wait before retry attempt `attempt + 1`."""

    def should_retry(self, exc: BaseException, attempt: int) -> bool:
        """True iff exc matches retry_on, doesn't match no_retry_on, and attempt < max_attempts."""
```

`compute_next_delay`:
- `exponential` → `min(max, base * 2 ** (attempt - 1))` then jitter
- `linear` → `min(max, base * attempt)` then jitter
- `fixed` → `base` then jitter
- Jitter `full` → `random.uniform(0, computed)` (AWS-style); `equal` → `computed/2 + random.uniform(0, computed/2)`; `none` → `computed`

`should_retry`:
- `isinstance(exc, no_retry_on)` → False (no_retry_on wins)
- `isinstance(exc, retry_on)` AND `attempt < max_attempts` → True
- otherwise False

## 11. Worker Iteration (concrete, Phase 1)

```python
def run_worker(*, queues, concurrency, site, grace_seconds=30):
    setup_logging(site=site); setup_otel(); cfg=load_config(...); r=get_redis(...)
    worker_id = _make_worker_id()
    _register_worker(worker_id, queues, site)
    _install_signal_handlers()

    streams = {stream_key(site, q): ">" for q in queues}
    for s in streams: ensure_consumer_group(r, s)

    pool = ThreadPoolExecutor(max_workers=concurrency, ...)
    cancel_events = {}                                          # job_id -> threading.Event
    cancel_events_lock = threading.Lock()
    drainer_thread = start_delay_drainer(r, site)               # P1-11
    sweeper_thread = start_orphan_sweeper(r, cfg)               # P1-1
    cancel_poller_thread = start_cancel_poller(worker_id, cancel_events, cancel_events_lock)  # §12.4
    last_beat = 0.0

    try:
        while not _shutdown.is_set():
            beat_if_due(worker_id, &last_beat)

            # Reclaim stalled messages first (peer died holding them).
            for s in streams:
                _xautoclaim_into_pool(r, s, worker_id, pool, idle_ms=60_000,
                                      cancel_events=cancel_events, cancel_events_lock=cancel_events_lock)   # P1-10

            # Read new messages.
            try:
                _read_and_dispatch(r, streams, concurrency, 5000, worker_id, pool, site, sites_path,
                                   cancel_events=cancel_events, cancel_events_lock=cancel_events_lock, wait=False)
            except redis.ConnectionError:
                log.warning("redis_connection_error"); time.sleep(2)
    finally:
        drainer_thread.stop(); sweeper_thread.stop(); cancel_poller_thread.stop()
        pool.shutdown(wait=True)
        _mark_worker_gone(worker_id)


def _handle_one(stream_name, msg_id, fields, worker_id, redis_client, site, sites_path,
                cancel_events, cancel_events_lock):
    frappe.init(site=site, sites_path=sites_path); frappe.connect()
    try:
        decoded = {k.decode(): v.decode() for k, v in fields.items()}
        msg = decode(decoded)

        # Pre-execution cancellation: cancel() ran before we picked up the message.
        if frappe.db.get_value("Conductor Job", msg.job_id, "status") == "CANCELLED":
            redis_client.xack(stream_name, CONSUMER_GROUP, msg_id)
            return  # No Job Run row — no attempt was started.

        # Defense-in-depth: only one worker runs the job body within a window.
        if not acquire_exec_lock(redis_client, site, msg.job_id, worker_id, ttl=msg.timeout_seconds + 30):
            log.info("exec_lock_held_by_peer", job_id=msg.job_id)
            redis_client.xack(stream_name, CONSUMER_GROUP, msg_id)
            return

        # Register cancel_event so the cancel-poller thread can flip it (§12.4).
        cancel_event = threading.Event()
        with cancel_events_lock:
            cancel_events[msg.job_id] = cancel_event
        watchdog = start_watchdog(msg.deadline, cancel_event) if msg.deadline else None

        succeeded = False; result = None; exc = None
        try:
            with set_context(job_id=msg.job_id, attempt=msg.attempt, deadline=msg.deadline, cancel_event=cancel_event):
                _set_job_running(msg.job_id, worker_id)
                func = frappe.get_attr(msg.method)
                result = func(**msg.kwargs)
            succeeded = True
        except BaseException as e:
            exc = e

        # Reload status to see if cancel() flipped it during execution.
        current_status = frappe.db.get_value("Conductor Job", msg.job_id, "status")
        cancelled_during_run = (current_status == "CANCELLED") or cancel_event.is_set()

        if cancelled_during_run and current_status == "CANCELLED":
            # cancel() observed during execution. Preserve CANCELLED; do not overwrite.
            _write_job_run_row(msg, worker_id,
                               status="SUCCEEDED" if succeeded else "FAILED", exc=exc)
            log.info("job_cancelled", job_id=msg.job_id, completed_anyway=succeeded)

        elif succeeded:
            _set_job_succeeded(msg.job_id, result)
            _write_job_run_row(msg, worker_id, status="SUCCEEDED")
            log.info("job_succeeded", job_id=msg.job_id)

        else:
            policy = _resolve_policy_from_msg(msg)
            if cancel_event.is_set():
                # Watchdog timeout (cancel() path is handled above).
                _write_job_run_row(msg, worker_id, status="TIMED_OUT", exc=exc)
                _retry_or_dlq(msg, policy, exc, attempt_status="TIMED_OUT")
            elif policy.should_retry(exc, msg.attempt):
                delay = policy.compute_next_delay(msg.attempt)
                _schedule_retry(msg, delay)
                _write_job_run_row(msg, worker_id, status="FAILED", exc=exc)
            else:
                _move_to_dlq(msg, exc)
                _write_job_run_row(msg, worker_id, status="FAILED", exc=exc)
            log.error("job_failed", job_id=msg.job_id, attempt=msg.attempt)

        if watchdog: watchdog.cancel()
        with cancel_events_lock:
            cancel_events.pop(msg.job_id, None)
        release_exec_lock(redis_client, site, msg.job_id, worker_id)
        redis_client.xack(stream_name, CONSUMER_GROUP, msg_id)
    finally:
        frappe.destroy()
```

Helpers:
- `_resolve_policy_from_msg(msg)` reconstructs `RetryPolicy` from the stamped fields, importing exception class names lazily.
- `_schedule_retry(msg, delay)` increments `msg.attempt` for the next dispatch, copies the message into the next stream entry once the drainer fires (we re-XADD with attempt+1), updates `Conductor Job` to `SCHEDULED_RETRY` + `next_run_at`.
- `_move_to_dlq(msg, exc)` XADDs the original message (unchanged) to `conductor:{site}:dlq:{queue}`, inserts `Conductor DLQ Entry` (status=PENDING_REVIEW), updates `Conductor Job` to `DLQ`.

## 12. Idempotency, Execution Lock, and Cancellation

### 12.1 Dispatch idempotency

```python
def acquire_idem_lock(r, site: str, idem_key: str, job_id: str, ttl: int) -> str | None:
    """SET NX EX. Returns existing job_id if duplicate, None if newly acquired."""
    h = sha256(idem_key.encode()).hexdigest()
    redis_key = f"conductor:{site}:idem:{h}"
    if r.set(redis_key, job_id, nx=True, ex=ttl):
        return None
    return r.get(redis_key).decode()
```

The dispatcher calls this **before** inserting the Conductor Job row. If a job_id is returned, no DB row is inserted and no XADD; the existing job_id is returned to the caller. If `idempotency_key` is empty/None, the lock step is skipped.

The lock TTL = `site_config.conductor.idempotency_ttl_seconds` (default 24 h).

The lock is **not released on terminal status** in Phase 1. The TTL is the only release mechanism. (Releasing on success would mean a duplicate dispatch within the TTL would re-execute — which is the opposite of what we want.)

### 12.2 Execution lock

`SET NX EX <timeout + 30>` on `conductor:{site}:lock:{job_id}`, value=`worker_id`. Released by deleting the key on terminal status. Defense in depth against the rare race where two workers each receive the same message via XAUTOCLAIM + a fresh XREADGROUP.

### 12.3 Cancellation

`conductor.cancel(job_id)` (the only public API; bench command is a thin wrapper, whitelisted method is an HTTP wrapper):

1. Read current status. If terminal (SUCCEEDED/FAILED/DLQ/CANCELLED/DISPATCH_FAILED) → return False.
2. Update `Conductor Job.status = CANCELLED`. **Do not write a `Conductor Job Run` row here** — Job Run rows are written by the worker at attempt-terminal (P1-15); whether a row is needed depends on whether a worker actually started this attempt.
3. If prior status was `QUEUED`: best-effort `XDEL` from the queue stream (succeeds if the message hasn't been read yet by any consumer; failure is silently ignored — the worker will see status=CANCELLED on consumption and short-circuit).
4. If prior status was `SCHEDULED_RETRY`: ZREM from `conductor:{site}:scheduled`.
5. If prior status was `RUNNING`: nothing more to do here. The cancel-poller thread (§12.4) will flip the worker's `cancel_event` within 1 s; the user code observes via `should_cancel()` and can exit cooperatively.
6. Return True.

**Cooperative-cancellation limitation:** functions that never call `conductor.context.should_cancel()` will run to completion. The worker's terminal-write logic preserves the CANCELLED status — it does not overwrite to SUCCEEDED/FAILED. So a "cancelled-but-finished" job has Conductor Job status=CANCELLED, with a Conductor Job Run row capturing what actually happened (typically status=SUCCEEDED or status=FAILED). This is the documented v1 contract; subprocess-isolation hard-kill is master §3 #19 deferred-out-of-scope.

### 12.4 Cancel-poller thread

One thread per worker process, started alongside the delay drainer and sweeper. Every 1 s:

```sql
SELECT name FROM `tabConductor Job`
WHERE status = 'CANCELLED' AND worker_id = <this worker_id>
```

For each match, look up the in-memory map `{job_id: cancel_event}` (populated by `_handle_one` when it begins executing a job, removed at finally) and call `event.set()`. The user code's next call to `conductor.context.should_cancel()` returns True.

The map is a process-global `dict` guarded by a lock. Adding/removing entries is O(1); the poll query is bounded by `worker_id` so it scales with concurrent jobs on this worker, not site-wide.

## 13. Outbox / Sweeper (P1-1, master §3 #12 option C)

A "sweeper" thread runs inside each worker process. Once per 30 s, it queries:

```sql
SELECT name FROM `tabConductor Job`
WHERE status = 'QUEUED'
  AND redis_msg_id IS NULL
  AND enqueued_at < NOW() - INTERVAL 30 SECOND
LIMIT 100;
```

For each row found:
1. Reconstruct the JobMessage from the row (kwargs/args base64 already stored).
2. `XADD` to the target stream.
3. Update `redis_msg_id`. If XADD fails, mark `DISPATCH_FAILED` with the exception (single-txn).

The 30 s threshold is intentional — it's longer than any sane DB commit + XADD round-trip, so we never compete with the dispatcher's normal path.

The sweeper is single-threaded (one query lock per worker process). With multiple workers, contention is a non-issue because the recovery is idempotent — one worker re-XADDs first, the other workers see `redis_msg_id IS NOT NULL` on the next sweep.

## 14. Test Plan

### Unit (pytest, no Frappe)

| File | Tests |
|---|---|
| `test_retry.py` | exponential/linear/fixed delay calculations; max_delay clamp; full/equal/none jitter bounds; should_retry honors no_retry_on > retry_on > attempt-count; default-policy behavior |
| `test_idempotency.py` | SHA-256 hashing stable; SET NX EX with fakeredis; second acquire returns existing job_id; expired key allows re-acquire; missing idempotency_key skips lock |
| `test_execution_lock.py` | acquire returns True on free lock, False on held; release deletes only if value matches (Lua check); TTL applied |
| `test_scheduled.py` | ZADD with score=run_at_ms; ZRANGEBYSCORE returns due items; drainer XADDs and ZREMs in one pass; not-yet-due items left alone |
| `test_decorator.py` | decorator stores metadata on function (`__conductor_metadata__`); enqueue resolves precedence call > decorator > queue; dispatch reflects resolved values; no decorator → queue defaults |
| `test_sweeper.py` | finds rows older than 30 s with NULL redis_msg_id; ignores rows < 30 s; ignores rows with redis_msg_id; updates redis_msg_id after re-XADD; on XADD fail marks DISPATCH_FAILED |

### Integration (Frappe site)

| Test | Asserts |
|---|---|
| `test_conductor_job_run.py` | DocType CRUD; required fields enforced |
| `test_conductor_dlq_entry.py` | DocType CRUD; default status=PENDING_REVIEW |
| `test_dispatcher_idempotency` | Two enqueues with same `idempotency_key` → same job_id, only one DocType row, only one stream entry |
| `test_dispatcher_dispatch_failed_single_txn` | M-2: simulate XADD failure (mock) → exactly one DB write captures status+error in one transaction |
| `test_decorator_pulls_through_dispatch` | A function decorated with `@conductor.job(max_attempts=7, backoff="linear")` then enqueued without overrides → JobMessage carries those values |
| `test_worker_retry_then_succeed` | A function that fails twice with `RetryableError` then succeeds: 3 `Conductor Job Run` rows (FAILED, FAILED, SUCCEEDED); final job status SUCCEEDED; attempt counter increments correctly |
| `test_worker_exhausts_to_dlq` | A function that always raises with max_attempts=3: 3 Job Run rows; XADD to dlq stream; `Conductor DLQ Entry` row (PENDING_REVIEW); job status DLQ |
| `test_worker_no_retry_on` | `ValueError` matched by no_retry_on terminates immediately to DLQ — no retries written |
| `test_worker_records_timeout` | (the missing Phase 0 §11 test) cooperative timeout writes TIMED_OUT row + retries |
| `test_doctor_clean_install` | (missing) `doctor` (no --demo) exits 0 in clean install |
| `test_doctor_redis_down` | (missing) with Redis stopped, `doctor` exits 1 with the right error |
| `test_frappe_compat_shim` | (missing) `conductor.frappe_compat.enqueue` produces an equivalent Conductor Job |
| `test_cancel_queued_job` | cancel() while QUEUED → status=CANCELLED, XDEL succeeded, DocType reflects |
| `test_cancel_running_job` | cancel() while RUNNING → cancel_event set, worker observes via should_cancel(), final status=CANCELLED |
| `test_cancel_already_terminal_returns_false` | cancel() on SUCCEEDED job → returns False, status unchanged |

### Chaos (subprocess-driven, in `tests_chaos/`)

| Test | Asserts |
|---|---|
| `test_kill_during_run` | Spawn 2 worker subprocesses. Dispatch `conductor.demo.slow` (sleeps 10 s, returns OK). Kill -9 the worker holding the lock at t=2 s. Verify: a peer reclaims via XAUTOCLAIM at t≥60s, runs the job, status=SUCCEEDED. (Adjust idle_ms in test to ≤2 s for speed.) |
| `test_retry_exhausts_to_dlq` | Spawn 1 worker. Dispatch a function that always fails, max_attempts=3, base_delay=0.5 s. Verify: 3 Job Run rows over ≤3 s; final DLQ status; DLQ stream has the message; DLQ Entry exists |
| `test_dispatch_idempotency` | Two **separate processes** simultaneously enqueue with the same key. Verify: exactly one Conductor Job row, exactly one stream entry, both processes return the same job_id |

The chaos suite must pass **5 consecutive runs with zero flakes** before Phase 1 is "done".

## 15. Acceptance Gate (Definition of Done — Phase 1)

All of the following must hold simultaneously, on a clean `frappe.localhost` install:

- [ ] All Phase 0 DoD items still hold (regression check).
- [ ] All pytest unit tests pass (Phase 0 + Phase 1).
- [ ] All Frappe integration tests pass.
- [ ] The four missing Phase 0 §11 tests are present and passing.
- [ ] All chaos tests pass 5 consecutive runs.
- [ ] `conductor.enqueue("conductor.demo.boom", queue="default", max_attempts=3, base_delay_seconds=0.1, retry_on=(RuntimeError,))` followed by a worker run produces 3 `Conductor Job Run` rows and a `Conductor DLQ Entry` (PENDING_REVIEW).
- [ ] `conductor.enqueue("conductor.demo.echo", idempotency_key="dup-test", x=1)` followed by an identical second call returns the same job_id; DB has one row.
- [ ] Killing a worker mid-job: a peer reclaims and finishes the job; no double-execution observable to the function (verified via a side-effect counter in the chaos test).
- [ ] `conductor.cancel(job_id)` works while QUEUED, while SCHEDULED_RETRY, and (cooperatively) while RUNNING.
- [ ] M-2: simulated XADD failure produces exactly one DB write (one transaction) capturing both status and error fields.

## 16. Risks / Open Items in Phase 1

1. **Test flakiness from time-based assertions** — chaos tests depend on `XAUTOCLAIM` idle thresholds and watchdog timing. We ship them with shortened thresholds (parameterized for tests) rather than 60 s production defaults, but flakes can still happen on slow CI. Five-run gate forces us to address them.
2. **Sweeper re-XADD races with normal dispatcher** — both can XADD the same row if the dispatcher commit happened just under 30 s ago. Mitigation: dispatcher updates `redis_msg_id` immediately after XADD; sweeper double-checks `redis_msg_id IS NULL` inside the SELECT (Frappe row-level lock). Worst case: a duplicate stream entry; the worker's `Conductor Job` row uniqueness keeps execution single-threaded via the exec lock.
3. **Reclaim during graceful shutdown** — a worker that's draining at SIGTERM may be on the verge of acking a message; if XAUTOCLAIM fires on a peer 60 s in, we get a re-execution. Idempotency key (if set) protects business state. Without an idempotency key, a function may run twice for one logical job. Document this clearly; recommend keys for any function with side effects.
4. **Cancellation racing with retry scheduling** — `cancel()` runs while the worker is in the retry path. We need to check status==CANCELLED **after** acquiring the exec lock and **before** scheduling a retry. The pseudocode in §11 does this but it's easy to regress.
5. **Decorator metadata + dotted-path lookup** — `frappe.get_attr("foo.bar")` resolves a function. The decorator attaches `__conductor_metadata__` to the function object. As long as `frappe.get_attr` returns the same object the decorator wrapped, metadata is reachable. Verify across a `bench restart` cycle.
6. **Importing exception classes for retry_on** at the worker — the worker may not have the same set of installed apps as the dispatcher (in a heterogeneous deploy). `retry_on_names` is fully-qualified; `importlib.import_module(...)` may fail. On import failure, treat as "not in retry_on" (be conservative — let it DLQ rather than retry on a wrong assumption).

## 17. Hand-off to Phase 2

Phase 2 brainstorm starts with these inputs:

- The in-worker delay drainer (P1-11) and sweeper (P1-1) are temporary; Phase 2 lifts them into the dedicated scheduler process and removes the worker threads.
- Dead-worker reaping (master §6.3 — `Conductor Worker.status = STALE` after heartbeat staleness) lives in Phase 2's reaper loop.
- `Conductor Schedule` DocType + cron evaluation are Phase 2.
- Phase 2 will need the chaos test framework from Phase 1 to validate the scheduler's lease/lock semantics.

## Change Log

| Date | Change | Author |
|---|---|---|
| 2026-04-27 | Initial Phase 1 spec, approved by user. | osama.m@aau.iq |
