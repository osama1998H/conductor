# Conductor Phase 6 — Multi-Tenant Polish (Design)

**Status:** Draft for approval
**Date:** 2026-04-29
**Author:** osama.m@aau.iq
**Phase:** 6 of master roadmap (Multi-tenant polish). Final phase of the v1 plan.
**Master:** `docs/superpowers/specs/2026-04-27-conductor-master-design.md`

This spec refines, but does not relitigate, the master design. The site-bound worker decision (master §3 #14), the standalone-Redis + single-key-Lua constraint (master §3 #15), the Redis key topology (master §8 — including the `conductor:{site}:rate:{queue}` slot reserved for this phase), and the Phase 6 exit criterion (master §4) are all frozen there.

---

## 1. Scope

Phase 6 layers four operational features on top of the reliability core (Phases 0–2), the dashboard (Phase 3), and workflows (Phase 5). Each is independently shippable inside the phase but they share a common theme: making Conductor pleasant to operate when one Frappe bench serves many tenants (sites) at once.

**v1 scope (this phase):**

- **Pool worker mode.** A single worker process consumes streams from N sites concurrently, switching Frappe site context per job.
- **Per-(site, queue) rate limits and concurrency caps.** Configured on `Conductor Queue`, enforced via single-key Lua scripts at the worker.
- **`bench conductor migrate-from-rq` one-shot tool.** Moves pending RQ jobs into Conductor streams; idempotent via a Redis marker.
- **Operational subcommands.** `bench conductor dlq {list,retry,discard}`, `bench conductor depth [--all-sites]`.
- Master §9 contract additions and §10 risk-table updates.

**Explicitly out of scope (locked in this phase's brainstorm):**

- A persistent connection cache for pool workers — deferred until the in-phase benchmark proves it is needed (master §10 risk #2).
- A periodic site re-scan in pool mode — site list is resolved once at boot; tenant onboarding requires a worker restart.
- Failed/started/deferred RQ jobs in the migration tool — only pending jobs are moved; the rest stay on RQ for triage.
- Per-method or per-user rate limits — only per-(site, queue).
- A new DocType for rate-limit policy — fields live on the existing `Conductor Queue`.
- Cross-region replication — out of scope for v1 (master §1 non-goals).
- Hard-kill of the previous worker process during a `--sites` reconfiguration — operators recycle the supervisor unit.

---

## 2. Cross-Phase Reference Map

| Frozen contract | Where | Used here |
|---|---|---|
| `_handle_one(stream_name, msg_id, fields, worker_id, redis_client, site, sites_path)` already accepts `site` and runs `frappe.init/destroy` per call | `conductor/worker.py:330` | Lifted unchanged into pool mode; the **stream key** decides `site`, not `msg.site` (caller-controlled msg fields are not trusted for routing). |
| Phase 1 retry path: `schedule_message(redis_client, site, encoded, run_at_ms)` ZADDs to `conductor:{site}:scheduled` | `conductor/scheduled.py` | Reused verbatim by the rate-limit throttle path (§5.4). |
| Phase 2 delay loop drains scheduled ZSET into target streams every second | `conductor/scheduler_loops.py:_delay_loop_iter` | Carries throttled jobs back into the stream once tokens refill. No new loop. |
| Phase 2 reaper marks STALE/GONE workers via `last_heartbeat` age | `conductor/scheduler_loops.py:_reaper_loop_iter` | Extended with an inflight-counter drift-correction pass for §5.5. |
| Master §3 #15 — Lua scripts must remain single-key | Master | Both `take_token` and `inflight_*` operate on a single key per call. |
| Master §8 reserves `conductor:{site}:rate:{queue}` for Phase 6 | Master | Filled in here; semantics defined in §6.1. |
| Phase 1 idempotency lock + execution lock | `conductor/idempotency.py`, `conductor/execution_lock.py` | Unaffected. Pool mode does not change lock keys. |
| Realtime event family `conductor:job:{id}` with `doctype="Conductor Job"`, `docname=job_id` | Master §9 / Phase 3 spec §8 | Throttled jobs emit a normal `SCHEDULED_RETRY` event with `reason="rate_limited"`. |
| Stream message schema (master §7) | Master | Unchanged — no new fields. |

---

## 3. Architecture

### 3.1 Pool worker

Today's `bench conductor worker --site=<site>` resolves one site from bench context, builds one `streams` dict for that site's queues, and feeds it to a single ThreadPoolExecutor. Phase 6 introduces `bench conductor worker --sites=auto|A,B,C` which:

1. **Resolves the site list once at boot.** `--sites=auto` walks `<sites_path>/*/site_config.json` and keeps sites where `frappe.get_installed_apps()` (run inside a transient site context) contains `"conductor"`. `--sites=A,B,C` is the explicit override and skips the filesystem scan. `--site=X` (singular, existing) and `--sites=...` (plural, new) are mutually exclusive; passing both is a Click error.
2. **Builds a single `streams` dict spanning all sites × all queues.** For each (site, queue) pair, computes `stream_key(site, queue)`, calls `ensure_consumer_group`, and sets `streams[skey] = ">"`. The existing `XREADGROUP` call needs no change — Redis Streams already supports reading from multiple streams in one call.
3. **Routes per-message site by stream key, not by message fields.** A new helper `parse_site_from_stream_key(skey)` extracts the site from `conductor:{site}:stream:{queue}`. `msg.site` (from the JobMessage) is left in place for diagnostics but is not used for routing — caller-controlled fields cannot decide which site's MariaDB we connect to.
4. **Pool ThreadPoolExecutor of size `--concurrency`.** Same shape as today; threads are not bound to sites. Each thread, on each job, calls `_handle_one(stream_name, msg_id, fields, worker_id, redis_client, site, sites_path)` which already does `frappe.init/connect → … → frappe.destroy()`. No connection cache in v1.
5. **Heartbeats and worker registration.** The pool worker generates one `worker_id` (`host:pid:uuid8`) and inserts one `Conductor Worker` row per site at startup, all with the same `worker_id` and `queues=<json of all queues>`. The heartbeat tick updates `last_heartbeat`/`status=ALIVE` on **every** site's row in one pass (one `frappe.init/destroy` per site per heartbeat — heartbeat interval is 5s so cost is bounded). On shutdown, every site's row is set to `GONE`.
6. **Cancel poller.** The existing `CancelPoller` polls `Conductor Job WHERE worker_id=<self> AND status=CANCELLED`. In pool mode we run **one CancelPoller per site** (lightweight daemon threads), each filtering its site's table; events still flow into the same shared `_cancel_events` map keyed by `job_id` (UUID — globally unique across sites).

The existing site-bound `--site=X` path is the no-op case of pool mode where N=1, so we implement pool mode and re-route the single-site command through it; this avoids two parallel code paths. The CLI flag `--site=X` is preserved for backward compatibility.

### 3.2 Per-tenant limits

Two independent guards:

- **Rate limit (`max_rps`).** A token bucket on `conductor:{site}:rate:{queue}` regulating how often jobs may *start* executing on this (site, queue). Enforced after the message is read but before user code runs. If denied, the job is rescheduled (§5.4).
- **Concurrency cap (`max_concurrent`).** A counter on `conductor:{site}:inflight:{queue}` capping how many jobs are simultaneously in `RUNNING` for this (site, queue) across the fleet. Acquired after the rate limit check and before user code; released in the same `finally` as the execution lock.

Both are configured on `Conductor Queue` (§7.1). Default `0` means unlimited and the worker skips the Redis call entirely (§5.6 fast path).

### 3.3 RQ migration

`bench --site=<site> conductor migrate-from-rq` is one-shot, defaults to `--dry-run`, and requires `--commit` to mutate state. It walks RQ's pending registries for the site, translates RQ queue names to Conductor queue names via `--queue-map`, calls `conductor.enqueue` for each pending RQ job, and deletes the original RQ job. A Redis marker (`conductor:{site}:rq_migrated_at`) makes re-runs no-ops unless `--force` is passed. Failed / started / deferred / scheduled RQ jobs are not touched.

### 3.4 Operational subcommands

`bench conductor dlq {list,retry,discard}` works on `Conductor DLQ Entry` rows; `bench conductor depth [--all-sites]` reports queue depths via `XLEN` / `ZCARD`. Implementation is deliberately thin — these are CLI front-ends over existing Frappe ORM and Redis primitives, not new abstractions.

---

## 4. Components

| Path | Purpose |
|---|---|
| `conductor/site_discovery.py` *(new)* | `discover_installed_sites(sites_path)` — filesystem scan + `installed_apps` filter. Pure function; no Redis. |
| `conductor/worker.py` *(edit)* | Refactor: `run_worker(...)` becomes a thin wrapper over `run_worker_pool(sites, queues, concurrency, ...)` with `sites=[site]`. Add multi-site stream/heartbeat/CancelPoller wiring. Add rate-limit + inflight check before user code in `_handle_one`. |
| `conductor/commands/worker.py` *(edit)* | Add `--sites` option (mutually exclusive with `--site`); resolve site list and dispatch to `run_worker_pool`. |
| `conductor/rate_limit.py` *(new)* | Public Python wrappers: `take_token(client, site, queue, max_tokens, refill_per_sec, n=1) -> (allowed, retry_after_ms)`; key helpers `rate_key(site, queue)`, `inflight_key(site, queue)`. |
| `conductor/rate_limit.lua` *(new)* | Atomic refill bucket: `KEYS[1]=rate_key`, `ARGV={max_tokens, refill_per_sec, now_ms, n}`, returns `{allowed, retry_after_ms}`. |
| `conductor/inflight.py` *(new)* | `acquire(client, site, queue, max_concurrent) -> (acquired, current)`; `release(client, site, queue)`; `get_count(client, site, queue)`; `correct_drift(client, site, queue, decrement_by)`. |
| `conductor/inflight.lua` *(new)* | Two scripts: `acquire` (INCR if under cap; return acquired+current+retry_after_ms) and `release` (DECR floored at 0). |
| `conductor/scheduler_loops.py` *(edit)* | Extend `_reaper_loop_iter` with §5.5 inflight drift correction (no new loop — added pass within the existing reaper). |
| `conductor/conductor/doctype/conductor_queue/conductor_queue.json` *(edit)* | Add `max_rps` (Int, default 0) and `max_concurrent` (Int, default 0) fields. |
| `conductor/patches/v1_2_phase6_queue_limits.py` *(new)* | Migration: backfill `0` for existing `Conductor Queue` rows. |
| `conductor/migrate_rq.py` *(new)* | `migrate_from_rq(site, *, queue_map, commit=False, force=False) -> MigrationReport` — importable for tests. |
| `conductor/commands/migrate_rq.py` *(new)* | `bench conductor migrate-from-rq` Click command (thin wrapper). |
| `conductor/commands/dlq.py` *(new)* | `bench conductor dlq {list,retry,discard}` Click group. |
| `conductor/commands/depth.py` *(new)* | `bench conductor depth [--all-sites]` Click command. |
| `conductor/commands/__init__.py` *(edit)* | Register new commands in `conductor_group`. |
| `tests/test_site_discovery.py` *(new)* | Unit — tmpdir with fake `sites/<name>/site_config.json` files; varies `installed_apps`. |
| `tests/test_rate_limit.py` *(new)* | Unit on a real Redis (existing fixture pattern from `test_idempotency.py`); covers refill, exhaustion, retry_after_ms. |
| `tests/test_inflight.py` *(new)* | Unit; covers acquire-under-cap, acquire-at-cap, release floors at 0, drift correction. |
| `tests/test_migrate_rq.py` *(new)* | Unit; mocks `frappe.utils.background_jobs.get_redis_conn` and `rq.Queue` to inject a synthetic pending job set. |
| `tests/test_dlq_commands.py` *(new)* | Click `CliRunner` against fixture `Conductor DLQ Entry` rows. |
| `tests/test_depth_command.py` *(new)* | `CliRunner` + Redis fixture. |
| `tests/test_pool_worker.py` *(new)* | Unit; pool worker against 2 fake sites in `frappe.local.flags.in_test` mode; verifies stream-key→site routing, per-site Conductor Worker row insert. |
| `tests_chaos/test_phase6_pool_chaos.py` *(new)* | §9 chaos test 1. |
| `tests_chaos/test_phase6_rate_limit.py` *(new)* | §9 chaos test 2. |
| `tests_chaos/test_phase6_concurrency_cap.py` *(new)* | §9 chaos test 3. |
| `tests/benchmarks/test_phase6_pool_throughput.py` *(new)* | Benchmark for master §10 risk #2. Not part of the chaos exit criterion; produces the data point that decides whether a connection cache is needed. |

The `conductor/rate_limit.py` and `conductor/inflight.py` are kept as separate top-level modules (not a `conductor/limits/` subpackage) because each is small (~60 lines) and the public surfaces are unrelated. This matches `conductor/idempotency.py` and `conductor/execution_lock.py`'s sibling-module pattern.

---

## 5. Pool Worker Internals

### 5.1 Site discovery

```python
# conductor/site_discovery.py
def discover_installed_sites(sites_path: str) -> list[str]:
    """Return sorted site names where conductor is in installed_apps."""
```

Algorithm:
1. List directories under `sites_path` (ignore `assets`, hidden dirs, files).
2. For each candidate `site`, attempt `frappe.init(site=site, sites_path=sites_path); frappe.connect()`. On any error, skip with a warning (`site_discovery_skipped` log).
3. Read installed apps via `frappe.get_installed_apps()`. If `"conductor"` is in the list, include the site.
4. `frappe.destroy()` after every probe.
5. Return sorted list.

This is run **once per worker boot**. The result is cached in process memory; no re-scan.

### 5.2 Stream → site routing

```python
# conductor/streams.py (added)
def parse_site_from_stream_key(stream_key: str) -> str:
    """conductor:{site}:stream:{queue} -> site. Raises ValueError if malformed."""
```

The pool worker's `_read_and_dispatch` and `_reclaim_into_pool` already iterate `(stream_name, entries)` tuples — we add one line that calls `parse_site_from_stream_key(stream_name)` and passes the result to `_handle_one`. The existing `site` parameter on `_handle_one` becomes wired from the stream, not from the outer scope.

### 5.3 Heartbeat across sites

```python
def _heartbeat_pool(worker_id: str, sites: list[str], sites_path: str) -> None:
    for site in sites:
        frappe.init(site=site, sites_path=sites_path)
        frappe.connect()
        try:
            frappe.db.set_value(
                "Conductor Worker", worker_id,
                {"last_heartbeat": _now_naive(), "status": "ALIVE"},
                update_modified=False,
            )
            frappe.db.commit()
        finally:
            frappe.destroy()
```

Heartbeat runs every `_HEARTBEAT_SECS=5`. With N sites this is 5N init/destroy pairs every 5s — at N=10 that's 2 init/destroy per second amortized. Tolerable.

`_register_worker` and `_mark_worker_gone` get the same N-fanout pattern.

### 5.4 Throttle path (inflight at cap OR rate limit denied)

```
1. Worker reads message from stream (XREADGROUP).
2. _handle_one: frappe.init(site=site_from_stream); frappe.connect()
3. Decode JobMessage.
4. Acquire exec_lock (existing).
5. inflight.acquire(...) → (acquired, current).
   On (acquired=0): throttle via §5.4.A with reason="inflight_capped",
                    retry_after_ms = config.inflight_retry_backoff_ms.
6. take_token(...) → (allowed, retry_after_ms).
   On (allowed=0): inflight.release(...)      # we never run, give back the slot
                   throttle via §5.4.A with reason="rate_limited",
                                              retry_after_ms = the Lua return.
7. Run user code (existing path: _set_job_running, importlib lookup, etc).
8. On terminal: inflight.release(...) inside the same finally as
   release_exec_lock(...).

§5.4.A — Throttle action (shared subroutine):
   a. encoded = encode(msg)                  # same JobMessage, same attempt
   b. schedule_message(r, site, encoded, now_ms + retry_after_ms)
   c. frappe.db.set_value("Conductor Job", job_id, {
          "status": "SCHEDULED_RETRY",
          "next_run_at": now + retry_after_ms,
          "last_error_message": f"{reason}: ...",
      })  # attempt is NOT incremented — throttling, not failure
   d. emit_job_event(job_id, "SCHEDULED_RETRY", reason=reason, ...)
   e. release_exec_lock(...); xack original msg_id.

10. Phase 2 delay loop picks the rescheduled message up at run_at_ms and
    XADDs it back to the same stream. Eventually a worker reads it and the
    cycle repeats (or succeeds when capacity is available).
```

**Ordering rationale.** Inflight acquire is checked **before** the rate-limit token because rejection on inflight is free (no state mutation — the cap-check Lua does not INCR if at cap). If inflight succeeded but the rate limit then rejects, we explicitly call `inflight.release` to return the slot — failing to do this would leak inflight slots whenever rate-limited jobs land on a queue with both limits configured. The order also makes the failure-recovery story symmetric: any throttle path leaves inflight count in the same pre-attempt state.

Both checks run **after** the exec lock so a stalled-and-reclaimed peer's exec lock keeps the job from being throttle-rescheduled twice.

### 5.5 Inflight drift correction (in reaper)

Failure mode: worker dies between `inflight.acquire` and `inflight.release`. The counter does not auto-decrement on TTL (we deliberately did not put a TTL on the counter — we want "in-flight" to mean exactly that, not "in-flight or stuck").

Mitigation, integrated into the existing reaper loop:

```python
# scheduler_loops.py:_reaper_loop_iter, NEW pass appended:
# After marking GONE workers, for each site:
#   1. SELECT queue, COUNT(*) FROM `tabConductor Job`
#      WHERE worker_id IN (workers just-marked-GONE)
#        AND status='RUNNING'
#      GROUP BY queue
#   2. For each (queue, count), call inflight.correct_drift(site, queue, count).
```

Important: the reaper does **not** touch the `Conductor Job` row's status. Message-level recovery for jobs whose worker died is already handled by XAUTOCLAIM (existing Phase 1 path) — a peer worker reclaims the message, runs it again, and writes the row's terminal status. Pre-flipping the row to `FAILED` here would race with that flow. Drift correction's sole job is to subtract the counter slot the dead worker held; the live peer that reclaims will INCR a fresh slot via `inflight.acquire`, restoring the count to a value that reflects only live in-flight work.

The reaper already runs every 60s and already touches `Conductor Worker` and `Conductor Job` — drift correction is one extra SELECT + N DECRs per cycle. Cheap.

### 5.6 Fast path when limits are unset

`Conductor Queue.max_rps == 0` and `max_concurrent == 0` are the defaults. The worker reads them once per job (cached on the queue doc fetch that happens already inside `_handle_one`'s message decode flow — we extend the existing dispatcher's `_resolve_dispatch_config`-style read pattern with a worker-side `_resolve_queue_limits(queue) -> (rps, conc)` call against `frappe.get_cached_doc("Conductor Queue", queue)`). When both are 0, we skip the Redis Lua call entirely. Zero-cost when feature is off.

---

## 6. Rate Limit and Concurrency Cap Internals

### 6.1 `take_token` Lua script

```
-- KEYS[1] = "conductor:{site}:rate:{queue}"
-- ARGV   = max_tokens, refill_per_sec, now_ms, n
local max_tokens     = tonumber(ARGV[1])
local refill_per_sec = tonumber(ARGV[2])
local now_ms         = tonumber(ARGV[3])
local n              = tonumber(ARGV[4])

local state    = redis.call("HMGET", KEYS[1], "tokens", "last_refill_ms")
local tokens   = tonumber(state[1]) or max_tokens
local last_ms  = tonumber(state[2]) or now_ms

local elapsed_ms = math.max(0, now_ms - last_ms)
local refill     = (elapsed_ms * refill_per_sec) / 1000.0
tokens = math.min(max_tokens, tokens + refill)

if tokens >= n then
    tokens = tokens - n
    redis.call("HMSET", KEYS[1], "tokens", tokens, "last_refill_ms", now_ms)
    redis.call("PEXPIRE", KEYS[1], 60000)  -- self-clean after 60s idle
    return {1, 0}
else
    local missing      = n - tokens
    local retry_ms     = math.ceil((missing * 1000.0) / refill_per_sec)
    -- Persist the partial refill so consecutive callers see consistent state.
    redis.call("HMSET", KEYS[1], "tokens", tokens, "last_refill_ms", now_ms)
    redis.call("PEXPIRE", KEYS[1], 60000)
    return {0, retry_ms}
end
```

Properties: single key (cluster-safe). Self-cleaning via PEXPIRE so abandoned (site,queue) keys do not accumulate. Floats via Redis Lua's number type — Redis returns integers; we floor / ceil at the boundaries. Returned `retry_after_ms` is the worker's hint to the delay-set ZADD score.

### 6.2 `inflight.acquire` and `inflight.release` Lua scripts

```
-- acquire: KEYS[1]=inflight_key, ARGV={max_concurrent}
local cur = tonumber(redis.call("GET", KEYS[1]) or "0")
local cap = tonumber(ARGV[1])
if cur < cap then
    local new = redis.call("INCR", KEYS[1])
    redis.call("EXPIRE", KEYS[1], 86400)  -- self-clean after 1d idle
    return {1, new}
else
    return {0, cur}
end
```

```
-- release: KEYS[1]=inflight_key
local new = redis.call("DECR", KEYS[1])
if new < 0 then
    redis.call("SET", KEYS[1], 0)  -- floor at 0
    return 0
end
return new
```

`acquire` does not return a `retry_after_ms` — the worker computes that as a fixed `inflight_retry_backoff_ms` (default 1000ms, configurable via `site_config.json conductor.inflight_retry_backoff_ms`). The bucket here is "wait and try later"; we do not know when slots will free.

### 6.3 Drift correction (third Lua script in `inflight.lua`)

```
-- correct_drift: KEYS[1]=inflight_key, ARGV={decrement_by}
local cur = tonumber(redis.call("GET", KEYS[1]) or "0")
local new = cur - tonumber(ARGV[1])
if new < 0 then new = 0 end
redis.call("SET", KEYS[1], new)
return new
```

Wrapper:

```python
# conductor/inflight.py
def correct_drift(client, site, queue, decrement_by: int) -> int:
    """Decrement the inflight counter by N (used by the reaper after marking
    workers GONE). Floors at 0 atomically inside Redis."""
```

A naive `DECRBY + SET-if-negative` would TOCTOU-race with concurrent `acquire` calls from live workers (their INCR lands between the reaper's read and the floor-set, and gets stomped). The Lua read-modify-write is single-key (cluster-safe per master §3 #15) and atomic, so a concurrent acquire either runs entirely before or entirely after the drift correction.

---

## 7. DocType and Schema Changes

### 7.1 `Conductor Queue` (extended)

Add two fields:

| Field | Type | Default | Notes |
|---|---|---|---|
| `max_rps` | Int | `0` | `0` = unlimited. Tokens per second. |
| `max_concurrent` | Int | `0` | `0` = unlimited. Cap on simultaneously RUNNING jobs from this (site, queue). |

Patch: `conductor/patches/v1_2_phase6_queue_limits.py` runs `ALTER TABLE `tabConductor Queue` ADD COLUMN max_rps INT DEFAULT 0, ADD COLUMN max_concurrent INT DEFAULT 0` via `frappe.db.add_column` (Frappe's idempotent helper) and backfills any existing rows — Frappe's column add is no-op if the column already exists, so the patch is safely re-runnable.

No change to the `Conductor Queue` controller class — both fields are simple int columns.

### 7.2 No other DocType changes

The four ops subcommands operate on existing rows (`Conductor DLQ Entry` for `dlq`; `Conductor Queue` for `depth`; RQ data + `Conductor Job` insertion for `migrate-from-rq`). No new DocTypes for Phase 6.

---

## 8. RQ Migration Tool

### 8.1 Command surface

```
bench --site=<site> conductor migrate-from-rq
    [--queue-map RQ_NAME=CONDUCTOR_NAME[,...]]
    [--commit]
    [--force]
```

Default: dry-run (prints the migration plan without mutation). `--commit` is required to actually move jobs and write the marker.

### 8.2 Algorithm

1. **Marker check.** Read `conductor:{site}:rq_migrated_at`. If present and `--force` is not set, print the marker timestamp and exit `0` with a no-op message.
2. **Discover RQ pending jobs for this site.** Use `frappe.utils.background_jobs.get_redis_conn()` to obtain the RQ Redis client. For each RQ queue name in `get_queues_timeout()` keys (defaults `short`, `default`, `long`, plus any custom ones), construct the Frappe-namespaced queue name via `generate_qname(qtype)` and instantiate `rq.Queue(qname, connection=conn)`. Call `q.get_jobs()` (or iterate `q.job_ids` and `Job.fetch` each) for the **pending** registry only. Skip `started_job_registry`, `failed_job_registry`, `deferred_job_registry`, `scheduled_job_registry`.
3. **Filter by site.** Each RQ job has `kwargs={"site": ..., "method": ..., "kwargs": ...}` per `frappe.utils.background_jobs.execute_job`. Skip any whose `kwargs["site"]` ≠ `--site` (defensive — the queue is already site-namespaced via `generate_qname`, but tenants share a single RQ Redis).
4. **Translate the queue.** RQ's qtype (`short`/`default`/`long`/...) is mapped through `--queue-map` (default identity). Unmapped RQ queues fall back to Conductor's `default` queue with a warning.
5. **Per job (if `--commit`):**
   - `method = rq_kwargs["method"]` if it's a string. If it's callable, log a warning and skip — Conductor only accepts dotted method paths.
   - `conductor.enqueue(method, queue=mapped, **rq_kwargs["kwargs"])`. Capture the new `job_id`.
   - `rq_job.delete()` — removes the RQ job from its queue and registry. This is the cutover point; once deleted, the RQ worker cannot pick it up.
6. **Mark complete (if `--commit`).** `SET conductor:{site}:rq_migrated_at = ISO8601 now`. No TTL.
7. **Report.** Print a table: `(rq_queue → conductor_queue, rq_job_id → conductor_job_id, status)`. Counts of moved / skipped / failed at the end.

### 8.3 Failure semantics

- If `conductor.enqueue` raises mid-loop, abort the run, print which jobs were already moved (and remain deleted in RQ), and exit non-zero. The Redis marker is **not** written. Operator re-runs without `--force`; previously-moved jobs are no longer in RQ so step 2 picks up only the remainder.
- If `rq_job.delete()` raises after `conductor.enqueue` succeeded, log a `rq_migrate_double_dispatch_risk` error with both job_ids — the operator must manually delete the RQ job before re-running.

### 8.4 Pre-migration warning (in `--commit` mode)

Before doing any work, print:

```
WARNING: This will move pending RQ jobs into Conductor.
For a clean cutover, stop Frappe processes that still call frappe.enqueue
(or that route through conductor.frappe_compat.enqueue's HTTP shim while
intra-process Python calls bypass it; see master §3 #13).
Continue? [y/N]
```

Skipped if `--force` is set (CI / scripted use).

---

## 9. Operational Subcommands

### 9.1 `bench conductor dlq list`

```
bench --site=<site> conductor dlq list
    [--queue Q]
    [--status PENDING_REVIEW|RETRIED|DISCARDED]
    [--limit N=50]
```

Prints: `name | job | queue | moved_at | last_error_type | last_error_message`. Sorted by `moved_at DESC`.

### 9.2 `bench conductor dlq retry`

```
bench --site=<site> conductor dlq retry
    [--queue Q]
    [--limit N=50]
    [--job ID]              # mutually exclusive with --queue/--limit
```

For each matched `Conductor DLQ Entry` row with `status=PENDING_REVIEW`:
1. Read the original `Conductor Job` for `method` and decoded `kwargs` (from `args_b64`/`kwargs_b64`).
2. `conductor.enqueue(method, queue=row.queue, **kwargs)` — captures a new `job_id`.
3. `frappe.db.set_value("Conductor DLQ Entry", row.name, {"status": "RETRIED", "reviewed_by": frappe.session.user or "system", "reviewed_at": now})`.

Reports moved / skipped (already-retried/discarded) / failed.

### 9.3 `bench conductor dlq discard`

```
bench --site=<site> conductor dlq discard
    [--queue Q]
    [--limit N=50]
    [--job ID]
```

Marks rows `status=DISCARDED`; no Redis change. The original `Conductor Job` row stays in `DLQ` status (it is the historical record).

### 9.4 `bench conductor depth`

```
bench --site=<site> conductor depth [--all-sites]
```

Without `--all-sites`: prints a table for the current site:

```
queue       stream_xlen   dlq_xlen   scheduled_zcard   inflight   max_rps   max_concurrent
default     12            0          3                 4          0         0
critical    0             1          0                 0          50        10
...
```

With `--all-sites`: walks `discover_installed_sites(sites_path)` and prints the same table per site. Read-only; no writes.

---

## 10. Master Document Updates

After this phase merges, the master needs the following edits (these are deltas, applied as part of the implementation plan, not by this spec):

- **§3 Frozen Decisions row #14** — append: "Phase 6 ships pool mode (`--sites=auto|comma-list`) as the production multi-tenant deployment shape; site-bound `--site=X` workers remain supported."
- **§4 Phase 6** — replace exit criterion paragraph with the concrete tests in §11 below; replace the open-ended "Pool worker mode (`bench conductor worker --sites=auto --queues=default`): one worker process consumes from N per-site streams; switches Frappe site context per job with a connection cache" with: "...switches Frappe site context per job; connection cache deferred pending in-phase benchmark per master §10 risk #2."
- **§8 Redis Key Topology** — change the `conductor:{site}:rate:{queue}` line annotation from `[Phase 6+]` to `[Phase 6]` and append a hash-state note; add a new line `conductor:{site}:inflight:{queue}    # INCR/DECR counter, capped by Conductor Queue.max_concurrent     [Phase 6]`.
- **§9 Inter-Phase Contracts** — add row: "Pool worker + per-(site,queue) limits | Phase 6 | Phase 6".
- **§10 Risks** — keep risk #2 but append: "Phase 6 ships init/destroy-per-job and a benchmark; cache decision is data-driven post-Phase 6."
- **Change Log** — append a 2026-04-29 entry summarizing what Phase 6 ships.

---

## 11. Phase 6 Exit Criterion (per Master §4)

Three chaos tests + one benchmark. The chaos tests are gating; the benchmark produces a data point but its result does not block the phase.

### 11.1 `tests_chaos/test_phase6_pool_chaos.py`

Boot a pool worker for **3 test sites** (created via fixtures from Phase 1's `conftest.py` patterns), each with one queue. Dispatch 30 jobs total (10 per site). Mid-run, kill -9 the pool worker; start a peer pool worker covering the same 3 sites. Assert all 30 jobs reach `SUCCEEDED` exactly once each. This proves: stream→site routing is correct, XAUTOCLAIM works across sites, the inflight counter does not leak (drift correction kicks in via the reaper).

### 11.2 `tests_chaos/test_phase6_rate_limit.py`

Single site, one queue with `max_rps=10`. Dispatch 50 jobs each calling `time.sleep(0.1)`. Run a worker with `--concurrency=20` (intentionally over-provisioned to prove the rate limit is doing the work). Assert wall-clock duration to drain all 50 is **≥ 3.5s and ≤ 8.0s**. The lower bound is the load-bearing assertion: without throttling, 50 jobs × 0.1s ÷ 20 concurrency = 0.25s — so any wall time > ~1s proves rate-limit kicked in. The upper bound absorbs CI jitter, the 1s delay-loop tick that paces redelivery of throttled jobs, the bucket's full-on-first-call behavior (first 10 jobs run instantly), and msgpack/Redis round-trip overhead. The mathematical ideal of 50 ÷ 10 = 5s is the target; the wide window prevents flakes.

### 11.3 `tests_chaos/test_phase6_concurrency_cap.py`

Single site, one queue with `max_concurrent=2`. Dispatch 10 jobs each calling `time.sleep(1.0)`. Run a worker with `--concurrency=10`. Sample `Conductor Job.status` every 100ms throughout the run. Assert: at no sample point are more than 2 rows `RUNNING`.

### 11.4 `tests/benchmarks/test_phase6_pool_throughput.py` (non-gating)

10 fixture sites, 1 queue each, 100 instant `frappe.utils.now`-class jobs each. Single pool worker `--concurrency=8`. Records:
- p50/p95/p99 of `frappe.init+frappe.connect+frappe.destroy` wall time per job.
- Total throughput (jobs/sec).
- Per-job overhead as % of trivial-job duration.

If the overhead exceeds 30% of trivial-job time, file a follow-up to add the connection cache (master §10 risk #2). The benchmark prints results; it does not fail the build.

---

## 12. Realtime Events

Phase 6 introduces no new realtime room or event family. Throttled jobs emit existing `conductor:job:{id}` events with payload changes:

- Throttled (rate-limit denied): existing `SCHEDULED_RETRY` event, with `reason="rate_limited"` added to the payload, `attempt` unchanged.
- Throttled (inflight cap denied): existing `SCHEDULED_RETRY` event, with `reason="inflight_capped"` added, `attempt` unchanged.

Dashboard consumers can ignore the `reason` field if not interested; existing list-view rendering for `SCHEDULED_RETRY` works unchanged. The `last_error_message` column carries `"rate_limited: rps=10"` or `"inflight_capped: cap=2"` for at-a-glance triage.

---

## 13. Risks

1. **Pool-worker noisy neighbor.** A single slow site's jobs can monopolize the shared ThreadPoolExecutor; other sites starve. Mitigation: per-(site,queue) `max_concurrent` lets ops bound any one tenant's footprint. Documented in the Phase 6 README section.
2. **Inflight counter drift between worker death and reaper run.** A pool worker that dies between `inflight.acquire` and `inflight.release` leaks one slot for up to 60s (reaper interval). Acceptable; reaper is the safety net. Could add a per-job inflight-set with TTL as a follow-up if leaks are observed in production.
3. **`migrate-from-rq` race with active dispatchers.** If `frappe.enqueue` is still routing to RQ during `--commit`, jobs added after step 2's enumeration are not migrated. Mitigation: §8.4 warning + a post-migration re-check log line if RQ pending count is non-zero at the end.
4. **Site discovery during `--sites=auto` may probe a site that is mid-`bench install-app`.** `frappe.connect` may fail; we log and skip. The site is invisible to the pool until restart. Documented; not a correctness issue.
5. **`max_rps` is per-process Redis-side, but `Conductor Queue` is per-site MariaDB-side.** A pool worker reads `max_rps` from each (site, queue) row independently — there is no cross-site rate limit. This is the intended semantic ("per-tenant" = per-site).
6. **`take_token` PEXPIRE drops state if the (site, queue) sees no traffic for 60s.** First post-idle call sees a fresh bucket (full tokens), which is the correct behavior — no overcharge.

---

## 14. Document Lifecycle

- This spec is the source of truth for Phase 6's design. The implementation plan (`writing-plans` skill) derives from it; per-step exit criteria cite back to §11 here.
- Master document edits in §10 land as part of the Phase 6 implementation, not via this spec.
- Once Phase 6 ships, the Phase 6 row of master §4 should reference this spec by date.
