# Conductor — Master Design

**Status:** Draft for approval
**Date:** 2026-04-27
**Author:** osama.m@aau.iq
**Scope:** Master architecture + 6-phase roadmap. Each phase will get its own brainstorm → spec → plan → implementation cycle. This document is the source of truth for cross-phase contracts (DocType schemas, Redis topology, stream message format, state machine).

---

## 1. What Conductor Is

A reliability-first background job platform for Frappe/ERPNext, built as a custom Frappe app named **`conductor`**. It coexists with `frappe.enqueue` and stock RQ; client apps migrate gradually via an opt-in shim.

**v1 goals:** durable at-least-once execution on Redis Streams; full Desk-queryable audit (every dispatch, attempt, retry, DLQ); declarative retry policies; idempotency; scheduled/cron jobs; DAG workflows with compensations; OpenTelemetry tracing; works in single-tenant on-prem and multi-tenant SaaS without code changes.

**v1 non-goals:** replacing Frappe's scheduler entirely (we coexist with `hooks.py`'s `scheduler_events`); cross-region replication; visual workflow builder (read-only UI); replacing Celery/Service Bus for non-Frappe workloads.

---

## 2. Architecture (one paragraph)

A **Dispatcher** library, embedded in every Frappe process, writes a `Conductor Job` row, takes an idempotency lock, and `XADD`s to a per-queue Redis Stream. Long-running **Worker** processes (`bench conductor worker`) consume those streams via consumer groups, execute the user function under an execution lock + timeout, write a `Conductor Job Run` row per attempt, and either ack on success, ZADD to a "scheduled" set for retry, or XADD to a DLQ stream. A **Scheduler** singleton (`bench conductor scheduler`) drains the scheduled set into the right queue stream, evaluates cron schedules, and reaps stalled workers. State is dual-tracked: Redis is the source of truth for *queueing*; MariaDB DocTypes are the source of truth for *history* and the data source for the Desk UI.

A textual diagram is in the original system-design draft (kept inline for reference, not reproduced here).

---

## 3. Cross-Cutting Decisions (Frozen)

These decisions are fixed across all phases. Per-phase brainstorms cannot relitigate them — only refine details inside their boundaries.

| # | Decision | Value | Reason |
|---|---|---|---|
| 1 | App / Python package name | `conductor` | Clean, matches Redis prefix and the metaphor. |
| 2 | License | MIT | Standard for Frappe community apps. |
| 3 | Author | `osama.m@aau.iq` | |
| 4 | Frappe target | 15.x (developed against 15.106.0) | Current bench. |
| 5 | Python target | 3.10+ | Matches Frappe 15. |
| 6 | Redis instance | `redis_queue` host (`127.0.0.1:11000` in this bench), DB **2** | Coexists with RQ on the same Redis without keyspace overlap. Configurable via `site_config.json` `conductor.redis_url`. |
| 7 | Redis key namespace | `conductor:{site}:…` from day 1 | Forward-compatible with multi-tenant SaaS without a migration. |
| 8 | DocType rollout | Schemas frozen here; each phase ships only the DocTypes it needs | Smaller phases, no dead surface in early DocTypes. |
| 9 | Stream message schema | Frozen here (§7); unused fields stay `null` in early phases | No mid-rollout message format migration. |
| 10 | _(removed)_ | OpenTelemetry tracing was a Phase 4 deliverable; the entire phase has been dropped (see §4). Observability is out of scope for v1 — a future cross-cutting app may handle it for the whole bench. | |
| 11 | Dispatch ordering (Phase 0) | Idempotency check → insert `Conductor Job` (status=`QUEUED`) → `XADD` → `publish_realtime` | Simplest correct path. The "DB succeeded but XADD failed" case marks the row `DISPATCH_FAILED`. |
| 12 | Outbox pattern | **Deferred to Phase 1 brainstorm**, with a strong default of *not* introducing an outbox table (current design). | Real decision once we have retry/DLQ in scope. |
| 13 | `frappe.enqueue` shim | Available from Phase 0 as opt-in (`override_whitelisted_methods` in client `hooks.py`); RQ keeps running in parallel | Lets one client app start migrating immediately after Phase 0. |
| 14 | Multi-tenancy in v1 | Site-bound workers (`bench conductor worker --site=<site>`). Pool workers with site-context switching are a Phase 6 enhancement. | Simpler ops + isolation. |
| 15 | Cluster vs standalone Redis | Standalone for v1; any Lua scripts must remain single-key so cluster compat is achievable later | YAGNI on Cluster; don't paint ourselves into a corner. |
| 16 | Stream retention | `XADD … MAXLEN ~ 10000` per stream + 7-day periodic `XTRIM MINID` by reaper | Bounded memory, configurable per queue later. |
| 17 | Args serialization | `msgpack` (base64 in stream value) for `args`/`kwargs`/`result` | Preserves Frappe types (datetimes, Decimals) JSON drops. |
| 18 | Worker concurrency model (v1) | One **process** per worker; **N threads** per process via a thread-pool executor (per `--concurrency`). Each in-flight job pins one thread. | Frappe is not async; threads are fine for I/O-bound jobs. CPU-bound jobs scale horizontally with more processes. |
| 19 | Job timeout enforcement | Soft signal (cancellation flag) + hard kill via per-job thread + watchdog. (Note: Python threads can't be force-killed cleanly; for hard-kill we may need subprocess isolation in a later phase. v1 uses cooperative timeout + watchdog logging.) | Pragmatic. Subprocess-per-job is a future option if hard-kill is required. |
| 20 | Workflow definition versioning | Pin definition snapshot at run start (immutable per run); definition changes bump version | Avoids mid-run schema drift. |

---

## 4. Phase Roadmap (Master Plan)

Each phase below is shippable on its own and builds on the previous. **Each phase will get its own brainstorm → spec → plan cycle.** The exit criterion is the operational test that proves the phase actually works; it is also the gating condition for moving on.

### Phase 0 — Skeleton

**Ships:**
- App scaffold (`bench new-app conductor`), `hooks.py`, fixtures.
- DocTypes (full schemas frozen in §6, but only these three created): `Conductor Queue`, `Conductor Job`, `Conductor Worker`.
- Default queues seeded as fixtures: `default`, `short`, `long`, `critical`.
- Redis client wrapper module.
- `conductor.enqueue(method, *, queue, **kwargs)` — drop-in for `frappe.enqueue`.
- `bench conductor worker --queue <name> [--concurrency N]` — long-running consumer.
- `bench conductor doctor` — health check (Redis up, streams + groups created, default queues seeded).
- Worker writes status transitions `QUEUED → RUNNING → SUCCEEDED|FAILED|TIMED_OUT`. **No retry, no DLQ in this phase.**
- `frappe.enqueue` opt-in shim available.
- Unit tests + an integration test that dispatches a known function and asserts the audit row.

**Exit criterion:** Dispatching `frappe.utils.now()` from Desk via `conductor.enqueue` produces a `Conductor Job` row whose status transitions `QUEUED → RUNNING → SUCCEEDED` end-to-end with `started_at`/`finished_at` populated, while a worker is running. Killing the worker mid-job leaves the row in `RUNNING` (recovery is Phase 1's job).

**Out of scope (this phase):** retries, DLQ, idempotency keys (the field exists in the schema but no Redis lock yet), scheduled/delayed jobs, scheduler process, **dead-worker reaping** (workers heartbeat from Phase 0 but stale rows are not cleaned up until Phase 2's reaper), dashboard, workflows, pool workers.

### Phase 1 — Reliability core

**Ships:**
- DocTypes: `Conductor Job Run`, `Conductor DLQ Entry`.
- `RetryPolicy` typed config (max_attempts, backoff strategy, base/max delay, jitter, retry_on, no_retry_on).
- Retry path: failed (retryable) attempt → ZADD to `conductor:{site}:scheduled` with score = `now + delay`, status `SCHEDULED_RETRY`, `Conductor Job Run` row written for the failed attempt.
- A **minimal in-worker delay drainer** (one loop per worker) so retries actually fire even before Phase 2's full scheduler exists. (Phase 2 lifts this into the scheduler process and the worker drainer is removed.)
- DLQ: jobs that exhaust attempts XADD to `conductor:{site}:dlq:{queue}` and create a `Conductor DLQ Entry` row.
- Dispatch idempotency: `SET NX EX` on `conductor:{site}:idem:{key}` (TTL 24h default).
- Execution lock: `SET NX EX` on `conductor:{site}:lock:{job_id}` for the duration of the job.
- Stalled-message reclamation: `XAUTOCLAIM` on each worker iteration with idle-ms threshold.
- Outbox decision (per §3 #12) settled in this phase's brainstorm.
- Chaos tests: kill -9 a worker mid-job, verify peer reclaims and finishes; double-dispatch with same idempotency key, verify only one job exists.

**Exit criterion:** the chaos test suite passes — no lost jobs, no double-execution, dispatch idempotency holds, jobs that exceed `max_attempts` land in the DLQ with a row.

### Phase 2 — Scheduling

**Ships:**
- DocType: `Conductor Schedule`.
- `bench conductor scheduler` — singleton process, lock via Redis `SET NX EX` on `conductor:{site}:scheduler:lock` with renewal.
- Three loops:
  - Delay loop (1s): drains `conductor:{site}:scheduled` (replaces the in-worker drainer from Phase 1).
  - Cron loop (30s): walks `Conductor Schedule` rows, computes `next_run_at` for any expired ones, ZADDs.
  - Reaper loop (60s): scans `conductor:{site}:workers` heartbeats, marks stale workers, reclaims their pending entries.
- `bench conductor schedule` subcommands: list, enable, disable, run-now.

**Exit criterion:** A cron job set to run every minute runs ≥ 60 times in an hour with < 2s drift per run. Killing the scheduler process: another instance picks up the lock within ~30s.

### Phase 3 — Dashboard

**Ships:**
- A custom Frappe page (single-file Vue 3 SFC) with sections:

> **Phase 3 refinement (2026-04-28):** Implemented as a `www/conductor-dashboard.html` route built from a standalone vite project at `apps/conductor/dashboard/` (HRMS-roster pattern), not as a Frappe Page DocType. The `www/` route is the proven Vue 3 SFC pattern in this Frappe 15.106.0 bench. See [Phase 3 spec](2026-04-28-conductor-phase3-dashboard-design.md) §2 #3 for full reasoning.

  - **Overview** — queue depths (live), throughput (last 1h/24h), error rate, DLQ counts.
  - **Live feed** — streaming list of recent jobs with status badges; click → drill.
  - **Job detail** — timeline of attempts, args/kwargs (pretty-printed), traceback.
  - **DLQ browser** — filter by queue/method, bulk actions: retry, discard, edit-and-retry.
  - **Schedules** — list + calendar view, next runs, last result.
  - **Workers** — registered workers, heartbeats, currently executing jobs.
- Real-time updates via `frappe.publish_realtime("conductor:*")` events; the page subscribes through Frappe's existing socketio.
- (Workflows section is **Phase 5**, not here.)

**Exit criterion:** Operator can fully diagnose a failed job (find it, see its traceback, retry it) without SSH or `bench console`.

### Phase 4 — _(removed)_

Originally an "Observability" phase covering OpenTelemetry exporter wiring, Prometheus / OTLP metrics, structured trace-tagged logs, and Sentry integration. The phase was dropped (2026-04-28) because observability is a cross-cutting concern of the whole bench, not a job-platform feature; bundling it into Conductor would dilute the app's single responsibility ("reliability-first background job platform"). A separate, bench-wide observability app may revisit this later. The phase number is left as a gap; subsequent phases keep their original numbers.

### Phase 5 — Workflows

**Ships:**
- DocTypes: `Conductor Workflow`, `Conductor Workflow Run`, `Conductor Workflow Step Run`.
- `@conductor.workflow` decorator + `Step` type with `depends_on` and optional `compensation`.
- **Advancer job:** on each step success, an advancer (itself a Conductor job) re-evaluates the DAG and dispatches now-unblocked steps. Fan-in is atomic via a Lua script that decrements a per-run "remaining-deps" counter for downstream steps.
- **Compensation:** on a step's terminal failure (post-retries), run compensations in reverse topological order over completed steps; the workflow run goes to status `COMPENSATING` then `FAILED`.
- Definition versioning per §3 #20.
- Dashboard: Workflows section with DAG visualization (Mermaid) and per-step status.

**Exit criterion:** A 4-step workflow with one parallel branch (steps B and C both depending on A; D depending on B and C) runs to success; forcing C to fail terminally rolls back A's compensation.

### Phase 6 — Multi-tenant polish

**Ships:**
- Pool worker mode (`bench conductor worker --sites=auto --queues=default`): one worker process consumes from N per-site streams; switches Frappe site context per job with a connection cache.
- Per-tenant rate limits and concurrency caps (Redis token buckets keyed by `{site}:{queue}`).
- `bench --site=<site> conductor migrate-from-rq` one-shot tool: copies pending RQ jobs into Conductor streams, leaves a marker so we don't double-import.
- Operational subcommands: `dlq retry --queue critical --limit 100`, per-tenant queue depth dump.

**Exit criterion:** One worker fleet serves 10 sites concurrently; chaos test in this mode still passes; per-tenant rate limits cap throughput as configured.

---

## 5. State Machine (Frozen)

```
QUEUED  ── XREADGROUP ─►  RUNNING  ──► SUCCEEDED
                              │
                              ├─► FAILED (terminal in Phase 0; in Phase 1+ split:)
                              │     ├─ attempt < max_attempts ─► SCHEDULED_RETRY ─► QUEUED
                              │     └─ attempt ≥ max_attempts ─► DLQ
                              ├─► TIMED_OUT (treated like FAILED for retry purposes)
                              └─► CANCELLED (manual; from Desk)

Out-of-band: DISPATCH_FAILED (DB row exists but XADD failed at dispatch time).
```

The DocType `status` Select field carries every state above. Phase 0 only ever writes `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `TIMED_OUT`, `DISPATCH_FAILED`. Phase 1 adds `SCHEDULED_RETRY`, `DLQ`, `CANCELLED`.

---

## 6. DocType Schemas (Frozen)

Field types are Frappe DocType field types. "Indexed" notes are MariaDB indexes for query performance. Fields not listed are excluded from v1.

### 6.1 `Conductor Queue`

| Field | Type | Notes |
|---|---|---|
| `name` | Data (primary, autoname) | E.g., "default", "critical" |
| `concurrency` | Int | Default 4 |
| `default_max_attempts` | Int | Default 3 |
| `default_timeout` | Int (seconds) | Default 300 |
| `default_backoff` | Select: exponential / linear / fixed | Default exponential |
| `default_base_delay_seconds` | Int | Default 2 |
| `default_max_delay_seconds` | Int | Default 600 |
| `default_jitter` | Select: none / full / equal | Default full |
| `enabled` | Check | Default 1 |
| `description` | Small Text | |

Phase 0 ships this. Fixtures seed `default`, `short`, `long`, `critical`.

### 6.2 `Conductor Job`

| Field | Type | Notes |
|---|---|---|
| `name` | Data (autoname = `job_id`) | UUID |
| `job_id` | Data (unique, indexed) | Same value as `name`; explicit for joins |
| `queue` | Link → `Conductor Queue` (indexed) | |
| `method` | Data | Dotted path |
| `args` | Long Text | msgpack-base64 serialization |
| `kwargs` | Long Text | msgpack-base64 |
| `args_preview` | Code (read-only) | JSON-pretty for the dashboard; best-effort |
| `kwargs_preview` | Code (read-only) | JSON-pretty for the dashboard; best-effort |
| `status` | Select (see §5) (indexed) | |
| `attempt` | Int | Default 1 |
| `max_attempts` | Int | |
| `timeout_seconds` | Int | |
| `enqueued_at` | Datetime (indexed) | |
| `scheduled_at` | Datetime (indexed) | For delayed enqueue / retry |
| `started_at` | Datetime | |
| `finished_at` | Datetime | |
| `next_run_at` | Datetime (indexed) | For `SCHEDULED_RETRY` |
| `deadline` | Datetime | |
| `idempotency_key` | Data (indexed) | Hashed key value |
| `workflow_run_id` | Link → `Conductor Workflow Run` | Phase 5 |
| `step_id` | Data | Phase 5 |
| `last_error_type` | Data | |
| `last_error_message` | Small Text | One-line summary for list views |
| `last_traceback` | Long Text | Full Python traceback of latest attempt; needed in Phase 0 because `Conductor Job Run` ships in Phase 1 |
| `result_preview` | Code | Truncated; full result is in last `Conductor Job Run` |
| `worker_id` | Data | Last/current worker |
| `redis_msg_id` | Data | XADD-returned ID for the latest dispatch |
| `site` | Data | Frappe site name |

Composite indexes: `(status, queue, scheduled_at)`, `(status, queue, enqueued_at)`.

Phase 0 ships this DocType with **all** fields above (workflow fields stay null until Phase 5).

### 6.3 `Conductor Worker`

| Field | Type | Notes |
|---|---|---|
| `name` | Data (primary) | `worker_id`, e.g., `host:pid:short-uuid` |
| `host` | Data | |
| `pid` | Int | |
| `queues` | Long Text | JSON array of queue names |
| `site` | Data | |
| `status` | Select: ALIVE / STALE / GONE | |
| `started_at` | Datetime | |
| `last_heartbeat` | Datetime (indexed) | |
| `current_job` | Link → `Conductor Job` | Best-effort |
| `conductor_version` | Data | |

Phase 0 ships this. Heartbeats every 5s.

### 6.4 `Conductor Job Run` (Phase 1)

| Field | Type | Notes |
|---|---|---|
| `name` | autoname | |
| `job` | Link → `Conductor Job` (indexed) | |
| `attempt_number` | Int | |
| `worker_id` | Data | |
| `started_at` | Datetime | |
| `finished_at` | Datetime | |
| `duration_ms` | Int | |
| `status` | Select: SUCCEEDED / FAILED / TIMED_OUT | |
| `error_type` | Data | |
| `error_message` | Small Text | |
| `traceback` | Long Text | |

### 6.5 `Conductor DLQ Entry` (Phase 1)

| Field | Type | Notes |
|---|---|---|
| `name` | autoname | |
| `job` | Link → `Conductor Job` | |
| `queue` | Link → `Conductor Queue` | |
| `moved_at` | Datetime | |
| `last_error_type` | Data | |
| `last_error_message` | Small Text | |
| `last_traceback` | Long Text | |
| `attempts` | Int | |
| `payload` | Long Text | Full stream message JSON for edit-and-retry |
| `status` | Select: PENDING_REVIEW / RETRIED / DISCARDED | Default PENDING_REVIEW |
| `reviewed_by` | Link → User | |
| `reviewed_at` | Datetime | |
| `review_notes` | Small Text | |

### 6.6 `Conductor Schedule` (Phase 2)

| Field | Type | Notes |
|---|---|---|
| `name` | Data (primary) | |
| `enabled` | Check | Default 1 |
| `cron_expression` | Data | E.g., "0 */5 * * *" |
| `timezone` | Data | Default "UTC" |
| `method` | Data | |
| `args` | Long Text | msgpack-base64 |
| `kwargs` | Long Text | msgpack-base64 |
| `queue` | Link → `Conductor Queue` | |
| `max_attempts` | Int | |
| `last_run_at` | Datetime | |
| `last_status` | Select | |
| `last_job` | Link → `Conductor Job` | |
| `next_run_at` | Datetime (indexed) | |
| `description` | Small Text | |

### 6.7 `Conductor Workflow` (Phase 5)

| Field | Type | Notes |
|---|---|---|
| `name` | Data (primary) | |
| `enabled` | Check | Default 1 |
| `definition_path` | Data | Dotted path to the `@workflow` class |
| `version` | Int | Bumped when the snapshot changes |
| `definition_snapshot` | Long Text | Frozen DAG JSON |
| `description` | Small Text | |

### 6.8 `Conductor Workflow Run` (Phase 5)

| Field | Type | Notes |
|---|---|---|
| `name` | autoname | |
| `workflow` | Link → `Conductor Workflow` | |
| `definition_version` | Int | Pinned at run start |
| `status` | Select: PENDING / RUNNING / COMPENSATING / SUCCEEDED / FAILED / CANCELLED | |
| `input_args` | Long Text | |
| `input_kwargs` | Long Text | |
| `started_at` | Datetime | |
| `finished_at` | Datetime | |
| `last_error` | Long Text | |

### 6.9 `Conductor Workflow Step Run` (Phase 5)

| Field | Type | Notes |
|---|---|---|
| `name` | autoname | |
| `workflow_run` | Link → `Conductor Workflow Run` (indexed) | |
| `step_id` | Data | Step name in the definition |
| `job` | Link → `Conductor Job` | |
| `status` | Select: PENDING / READY / RUNNING / SUCCEEDED / FAILED / COMPENSATED / SKIPPED | |
| `started_at` | Datetime | |
| `finished_at` | Datetime | |
| `depends_on` | Long Text | JSON array of step_ids |

---

## 7. Stream Message Schema (Frozen)

XADD value (one Redis hash per stream entry). Fields not used by the current phase stay empty/`null` strings. Binary args are msgpack-encoded then base64'd into UTF-8.

```
job_id            : str (UUID)
site              : str (Frappe site name)
name              : str (dotted method path)
queue             : str
args_b64          : str (msgpack→base64; "" if no positional args)
kwargs_b64        : str (msgpack→base64)
attempt           : str (int)
max_attempts      : str (int)
timeout_seconds   : str (int)
enqueued_at       : str (ISO8601)
deadline          : str (ISO8601 or "")
idempotency_key   : str ("" if none)            # Phase 1 honors this
workflow_run_id   : str ("" if none)            # Phase 5
step_id           : str ("" if none)            # Phase 5
schema_version    : str (int, starts at "1")    # Bump on incompat change
```

---

## 8. Redis Key Topology (Frozen)

```
conductor:{site}:stream:{queue}        # XADD here, XREADGROUP from here
conductor:{site}:cg:{queue}            # consumer group name (also: cg-name = "conductor")
conductor:{site}:dlq:{queue}           # dead-letter stream
conductor:{site}:scheduled             # ZSET, score = run_at_unix_ms      [Phase 1+]
conductor:{site}:idem:{hash}           # SET NX EX, value = job_id          [Phase 1+]
conductor:{site}:lock:{job_id}         # SET NX EX, value = worker_id       [Phase 1+]
conductor:{site}:workers               # HSET worker_id → last_heartbeat_iso
conductor:{site}:scheduler:lock        # singleton lock, SET NX EX           [Phase 2+]
conductor:{site}:rate:{queue}          # token bucket                        [Phase 6+]
```

Per-stream consumer group is created lazily by the dispatcher (XGROUP CREATE … MKSTREAM) — first-write wins, ignore BUSYGROUP errors.

---

## 9. Inter-Phase Contracts

What every later phase can rely on:

| Contract | Where it's introduced | Stable from |
|---|---|---|
| `Conductor Job` row exists for every dispatched job (or `DISPATCH_FAILED`) | Phase 0 | Phase 0 |
| Stream message schema (§7) | Phase 0 | Phase 0 |
| Redis key topology (§8) | Phase 0 (relevant subset) | Phase 0 |
| `conductor.enqueue(...)` API surface | Phase 0 | Phase 0 |
| `Conductor Job Run` row per attempt | Phase 1 | Phase 1 |
| `Conductor DLQ Entry` per terminal failure | Phase 1 | Phase 1 |
| Idempotency / execution lock semantics | Phase 1 | Phase 1 |
| Delay drainer behavior (in-worker → scheduler) | Phase 1 → Phase 2 | Phase 2 |
| `bench conductor scheduler` singleton + reaper | Phase 2 | Phase 2 |
| Real-time dashboard events: per-job `conductor:job:{id}` events with `doctype="Conductor Job"`, `docname=job_id` for room scoping; aggregates use polling (see [Phase 3 spec](2026-04-28-conductor-phase3-dashboard-design.md) §8 + §8.6.1). Existing global `conductor:job_queued` is **replaced** (breaking change). | Phase 3 | Phase 3 |
| Workflow definition + advancer | Phase 5 | Phase 5 |
| Pool workers + per-tenant rate limits | Phase 6 | Phase 6 |

---

## 10. Risks Tracked Across Phases

1. **Outbox vs. dual-write** (decided in Phase 1 brainstorm). If we keep dual-write, document the failure mode for ops.
2. **Frappe site context overhead** for pool workers — benchmark before Phase 6; may force per-site sub-process pool.
3. **Hard timeout enforcement** — Python threads can't be force-killed. v1 uses cooperative cancellation + watchdog. If real hard-kill is needed, subprocess-per-job is a follow-up.
4. **Lua scripts for atomic transitions** must stay single-key to keep cluster compatibility open (§3 #15).
5. **Workflow definition drift mid-run** — pinned via §3 #20; need an alert when a run is using a stale pinned version.
6. **Stream growth** — `MAXLEN ~ 10000` + reaper-driven `XTRIM MINID` keeps memory bounded; revisit once production volume is observable.
7. **Non-Python producers** (e.g., .NET Questify) — out of scope for v1, but the language-neutral msgpack message format keeps the door open.

---

## 11. Workflow For Each Phase

For every phase 0…6:

1. **Brainstorm** — short focused session on that phase's concrete questions only (not architecture-level).
2. **Spec** — written to `docs/superpowers/specs/YYYY-MM-DD-conductor-phaseN-<slug>.md`, derived from this master.
3. **Plan** — `superpowers:writing-plans` produces an executable implementation plan.
4. **Implement** — `superpowers:executing-plans` (or subagent-driven-development) runs the plan with TDD.
5. **Verify** — exit criterion stated in §4 must demonstrably pass before the phase is "done".
6. **Move on** — only after the user signs off on the phase exit demo.

---

## 12. Document Lifecycle

- This document is the **master**. Per-phase specs cite it and refine inside its boundaries.
- It lives at `docs/superpowers/specs/2026-04-27-conductor-master-design.md` until the `conductor` app is scaffolded; once Phase 0 lands, it should be **moved into** `apps/conductor/docs/superpowers/specs/` and committed there with the rest of the app's docs.
- Changes to this master after approval require a brief change-log entry at the bottom of this document and (if the change affects an in-flight phase) a note in that phase's spec.

---

## Change Log

| Date | Change | Author |
|---|---|---|
| 2026-04-27 | Initial master design. | osama.m@aau.iq |
| 2026-04-28 | Phase 3 footnotes: UI delivery refined to `www/` route + standalone vite project; realtime event family settled as `conductor:job:{id}` with `doctype`/`docname` room scoping. | osama.m@aau.iq |
| 2026-04-28 | **Phase 4 (Observability) removed.** OpenTelemetry exporter, Prometheus/OTLP metrics, structured trace-tagged logs, and Sentry integration are out of scope for v1. Conductor's responsibility is "reliability-first background jobs"; observability is a bench-wide concern best handled by a separate app. Code: removed `conductor.otel`, dropped `opentelemetry-*` runtime deps, stripped `trace_id`/`span_id`/`trace_parent`/`sentry_event_id`/`sentry_url` from DocType schemas, dispatcher, worker, scheduler, sweeper, stream message schema (§7), Redis topology (§8), inter-phase contracts (§9), and risks (§10). Python exception tracebacks (`last_traceback` / `traceback` fields) are **kept** — those are diagnostic data for the job platform itself, not observability instrumentation. Phase 5/6 numbering preserved (gap at Phase 4). | osama.m@aau.iq |
| 2026-04-29 | **Phase 5 (Workflows) shipped.** Adds DAG workflow support: `Conductor Workflow`, `Conductor Workflow Run`, `Conductor Workflow Step Run` DocTypes (with §8.1–8.3 augmentations from the Phase 5 spec — `last_version_bumped_at`, `idempotency_key`, `cancelled_at`/`cancelled_by`, `is_compensation`, `error_type`/`error_message`). New Redis keys `conductor:{site}:wfdeps:{run_id}` (single-key Lua scope) and `conductor:{site}:wfidem:{hash}`. New `workflow` queue in default fixtures for advancer/compensator coordination. The `workflow_run_id` and `step_id` fields frozen in §7 are now populated by the dispatcher. Realtime events `conductor:workflow_run:{run_id}` use the same per-doc room scoping as Phase 3. Worker resolves `module.ClassName.method` paths by instantiating the workflow class and calling the method as an instance method. **Master Phase 5 exit criterion verified**: `tests_chaos/test_phase5_chaos.py::test_diamond_c_terminal_fail_compensates_a` — 4-step diamond with parallel B/C branches, C fails terminally → A's compensation runs in reverse-topo order → run lands FAILED. Passes in ~18s through real worker subprocesses. | osama.m@aau.iq |
