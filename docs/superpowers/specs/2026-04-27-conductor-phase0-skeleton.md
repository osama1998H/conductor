# Conductor — Phase 0 Spec (Skeleton)

**Status:** Approved (2026-04-27)
**Phase:** 0 of 6 — Skeleton
**Master design:** `2026-04-27-conductor-master-design.md` (this spec lives inside its boundaries; it does **not** relitigate any of the 20 frozen cross-cutting decisions there)
**Author:** osama.m@aau.iq

---

## 1. Goal

Stand up the smallest end-to-end Conductor that proves the architecture is real:
**dispatch → stream → worker → audit row**, with a one-command acceptance test (`bench conductor doctor --demo`).

## 2. In Scope

- App scaffolding (`bench new-app conductor`).
- DocTypes: `Conductor Queue`, `Conductor Job`, `Conductor Worker` (all master §6.1, §6.2, §6.3 fields).
- Default queue fixtures: `default`, `short`, `long`, `critical`.
- `Conductor Operator` role.
- Public API: `conductor.enqueue(...)` and `conductor.context`.
- Bench commands: `bench conductor worker`, `bench conductor doctor [--demo]`.
- `frappe.enqueue` opt-in shim (`conductor.frappe_compat.enqueue`).
- OTel SDK wired as no-op spans across dispatcher and worker.
- `structlog` JSON logging from day 1.
- `Procfile.conductor` for `bench start` integration.

## 3. Out of Scope (Phase 0)

Per the master plan, Phase 0 explicitly does **not** ship:

- The `@conductor.job(...)` decorator, `RetryPolicy`, retries, DLQ, idempotency-key Redis lock, execution lock — **all Phase 1**.
- `Conductor Job Run`, `Conductor DLQ Entry` DocTypes — Phase 1.
- Scheduler process, delayed jobs, cron — Phase 2.
- Dead-worker reaping (Phase 0 workers heartbeat, but stale rows are never cleaned) — Phase 2.
- Dashboard UI — Phase 3.
- OTel exporter, Prometheus metrics, Sentry — Phase 4.
- Workflows — Phase 5.
- Pool workers, per-tenant rate limits, RQ migration tool — Phase 6.

## 4. Tactical Decisions (Phase-0 only)

These extend the master's frozen decisions; relevant within this phase only.

| # | Decision | Value |
|---|---|---|
| P0-1 | `bench new-app` answers | title="Conductor", description="Reliability-first background jobs for Frappe", publisher="Osama Muhammed", email=`osama.m@aau.iq`, license=MIT, branch=`develop` |
| P0-2 | API surface | Imperative `conductor.enqueue(...)` only. No decorator. |
| P0-3 | Worker concurrency | `--concurrency N` flag, default 4, `ThreadPoolExecutor`-backed |
| P0-4 | Worker graceful shutdown | SIGTERM → stop reading new messages → `pool.shutdown(wait=True)` with 30s grace → exit. After grace, in-flight rows stay `RUNNING` (Phase 1 reclaims). |
| P0-5 | Required Python deps | `redis>=5`, `msgpack>=1.0`, `opentelemetry-api`, `opentelemetry-sdk`, `structlog` |
| P0-6 | `Conductor Job` naming | `autoname = field:job_id` (UUID v4 generated at dispatch time) |
| P0-7 | `Conductor Worker` lifecycle | Insert on start (status=`ALIVE`); update `last_heartbeat` every 5s; on graceful shutdown set status=`GONE`; stale rows untouched (no reaper this phase) |
| P0-8 | Queue fixtures | `default`(concurrency=4), `short`(4), `long`(2), `critical`(8). Loaded via `after_install` hook. |
| P0-9 | Consumer group | Lazily created on first `XADD` per queue (`XGROUP CREATE … MKSTREAM`, swallow `BUSYGROUP`); group name `"conductor"` |
| P0-10 | OTel | `TracerProvider` initialized with no exporter; `start_as_current_span` invoked at dispatch and at execution; `traceparent` injected into stream message |
| P0-11 | Logging | `structlog` JSON renderer; bound: `trace_id`, `span_id`, `job_id`, `queue`, `worker_id`, `attempt`, `site` |
| P0-12 | Hard timeout enforcement | Cooperative: per-job `threading.Event`, watchdog flips it at deadline; `conductor.context.should_cancel()` exposed; no force-kill |
| P0-13 | Worker process supervision | Both: `bench conductor worker` foreground command **and** a `Procfile.conductor` line for dev (`bench start` picks it up) |
| P0-14 | Acceptance test | `bench conductor doctor --demo` must exit 0 in a clean install (see §10) |
| P0-15 | Permissions | `System Manager`: full; `Conductor Operator`: read + cancel; everyone else: none |
| P0-16 | Test framework | pytest for pure-Python; Frappe's `bench --site … run-tests --app conductor` for site-bound tests |
| P0-17 | TDD | Yes — red → green → refactor per `superpowers:test-driven-development` |

## 5. Public Python API (frozen for Phase 0)

```python
import conductor

# Imperative dispatch — drop-in for frappe.enqueue
job_id: str = conductor.enqueue(
    "myapp.tasks.send_email",   # dotted method path
    queue="default",             # optional, defaults to "default"
    timeout=300,                 # optional override of queue default
    invoice="INV-2026-001",      # **kwargs forwarded to the function
)

# Inside a job body
conductor.context.job_id        # str (UUID)
conductor.context.attempt       # int (always 1 in Phase 0)
conductor.context.deadline      # datetime | None
conductor.context.should_cancel() -> bool
```

Phase 0 does **not** ship: `@conductor.job(...)`, `idempotency_key`, `max_attempts`, `RetryPolicy`, `backoff`. Those land in Phase 1.

## 6. File Tree

```
apps/conductor/
├── pyproject.toml
├── license.txt
├── README.md
├── Procfile.conductor          # "conductor_worker: bench conductor worker --queue default"
├── tests/                      # pytest unit tests (no Frappe site needed)
│   ├── conftest.py
│   ├── test_messages.py
│   ├── test_serialization.py
│   ├── test_streams.py
│   ├── test_config.py
│   └── test_context.py
└── conductor/
    ├── __init__.py             # exports: enqueue, context, __version__
    ├── hooks.py
    ├── modules.txt             # "Conductor"
    ├── patches.txt             # empty
    ├── api.py                  # public re-exports
    ├── config.py               # site_config["conductor"] reader, defaults
    ├── client.py               # Redis connection pool factory
    ├── streams.py              # stream key builders, lazy XGROUP CREATE
    ├── messages.py             # stream message encode/decode (schema_version=1)
    ├── serialization.py        # msgpack helpers (datetime, Decimal codecs)
    ├── context.py              # per-job thread-local context
    ├── dispatcher.py           # enqueue(): DocType insert → XADD → publish_realtime
    ├── worker.py               # worker loop
    ├── doctor.py               # health checks + --demo
    ├── otel.py                 # no-op TracerProvider; traceparent inject/extract
    ├── logging.py              # structlog setup
    ├── frappe_compat.py        # frappe.enqueue-signature shim
    ├── install.py              # after_install: seed role + queues
    ├── demo.py                 # demo.echo(**kwargs) used by doctor --demo
    ├── commands/
    │   ├── __init__.py         # click command group, exported via hooks.py["commands"]
    │   ├── worker.py           # `bench conductor worker`
    │   └── doctor.py           # `bench conductor doctor`
    └── conductor/              # Frappe module folder (modules.txt: "Conductor")
        ├── __init__.py
        ├── doctype/
        │   ├── conductor_queue/
        │   │   ├── conductor_queue.json
        │   │   ├── conductor_queue.py
        │   │   └── test_conductor_queue.py
        │   ├── conductor_job/
        │   │   ├── conductor_job.json
        │   │   ├── conductor_job.py
        │   │   └── test_conductor_job.py
        │   └── conductor_worker/
        │       ├── conductor_worker.json
        │       ├── conductor_worker.py
        │       └── test_conductor_worker.py
        └── role/
            └── conductor_operator/
                └── conductor_operator.json
```

Frappe integration tests (need a site) live in each DocType's `test_*.py` per Frappe convention. Higher-level e2e tests:

```
apps/conductor/conductor/conductor/doctype/conductor_job/test_conductor_job.py
    # includes test_dispatcher_creates_row, test_worker_consumes_and_succeeds, test_worker_e2e
```

## 7. DocType Specs

Field schemas come straight from the master:
- `Conductor Queue` → master §6.1
- `Conductor Job` → master §6.2 (all fields shipped; workflow fields stay null)
- `Conductor Worker` → master §6.3

Phase-0-specific specifics:

**Conductor Queue**
- `autoname = field:queue_name` (where `queue_name` is the primary `name` field)
- Single doctype: no — it's a regular doctype keyed by name
- Permissions: System Manager (CRUD), Conductor Operator (R)
- Track changes: yes
- Custom: no (this is a core app DocType)

**Conductor Job**
- `autoname = field:job_id`
- Permissions: System Manager (full), Conductor Operator (read-only). The `CANCELLED` status exists in the state machine but the cancel-action UI ships in Phase 1 alongside the rest of the cancellation flow.
- Default sort field: `enqueued_at`, descending
- List view fields: `name`, `method`, `queue`, `status`, `attempt`, `enqueued_at`, `worker_id`
- Composite indexes added via an `after_install` `frappe.db.add_index` call: `(status, queue, scheduled_at)`, `(status, queue, enqueued_at)`

**Conductor Worker**
- `autoname = field:worker_id`
- Permissions: System Manager (read-only is fine); only the worker process writes via Frappe API.
- Default sort field: `last_heartbeat`, descending

## 8. Stream Message — concrete encoding

Per master §7. Phase 0 fields actually populated:
- `job_id`, `site`, `name` (= `method`), `queue`, `args_b64`, `kwargs_b64`, `attempt=1`, `max_attempts=1` (Phase 0 = no retries), `timeout_seconds`, `enqueued_at`, `deadline`, `trace_parent`, `schema_version="1"`.

Phase 0 fields written empty: `idempotency_key`, `workflow_run_id`, `step_id`.

Encoding sequence:
1. `payload = msgpack.packb({"args": list(args), "kwargs": dict(kwargs)}, default=...)`
2. `b64 = base64.b64encode(payload).decode("ascii")`
3. Map fields above into a flat dict of `str→str` (Redis Streams field values are bytes; we keep them as ASCII-safe strings).

## 9. Worker Loop (concrete)

```python
def run_worker(queues: list[str], concurrency: int, site: str, grace_seconds: int = 30):
    setup_logging(site=site)
    setup_otel(site=site)
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
    register_worker_row(worker_id, queues, status="ALIVE")
    install_signal_handlers()  # SIGTERM/SIGINT set shutdown event

    pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="conductor-")
    streams = {stream_key(site, q): ">" for q in queues}
    last_heartbeat = 0

    while not shutdown.is_set():
        if time.time() - last_heartbeat >= 5:
            update_worker_heartbeat(worker_id)
            last_heartbeat = time.time()

        try:
            msgs = r.xreadgroup("conductor", worker_id, streams, count=concurrency, block=5000)
        except redis.ConnectionError:
            log.warning("redis_connection_error", retry_in=2)
            time.sleep(2)
            continue

        for stream_name, entries in (msgs or []):
            for msg_id, fields in entries:
                pool.submit(handle_one, stream_name, msg_id, fields, worker_id)

    log.info("worker_shutting_down", grace_seconds=grace_seconds)
    pool.shutdown(wait=True)  # bounded by os-level signal; we accept stragglers
    mark_worker_row(worker_id, status="GONE")


def handle_one(stream_name, msg_id, fields, worker_id):
    job = decode_message(fields)
    log_ctx = log.bind(job_id=job.id, queue=job.queue, worker_id=worker_id)
    parent_ctx = otel_extract(job.trace_parent)
    with tracer.start_as_current_span(f"job:{job.method}", context=parent_ctx) as span:
        span.set_attribute("conductor.job_id", job.id)
        update_job_status(job.id, "RUNNING", started_at=now(), worker_id=worker_id)
        deadline = parse(job.deadline) if job.deadline else None
        cancel_event = threading.Event()
        watchdog = start_watchdog(deadline, cancel_event) if deadline else None
        with set_context(job_id=job.id, attempt=1, deadline=deadline, cancel_event=cancel_event):
            try:
                func = frappe.get_attr(job.method)
                result = func(**job.kwargs)  # positional args dropped in Phase 0; kwargs only
                update_job_status(job.id, "SUCCEEDED", finished_at=now(),
                                  result_preview=preview(result))
                log_ctx.info("job_succeeded")
            except Exception as e:
                status = "TIMED_OUT" if cancel_event.is_set() else "FAILED"
                update_job_status(job.id, status, finished_at=now(),
                                  last_error_type=type(e).__name__,
                                  last_error_message=str(e)[:140],
                                  last_traceback=traceback.format_exc())
                span.record_exception(e)
                log_ctx.error("job_failed", status=status, error=str(e))
            finally:
                if watchdog: watchdog.cancel()
                r.xack(stream_name, "conductor", msg_id)
```

Note on positional args: Phase 0 supports `**kwargs` only — positional `*args` are dropped at dispatch with a warning. Frappe job conventions are kwargs-first; we'll add positional support if any caller actually needs it.

## 10. `bench conductor doctor --demo` (acceptance test)

```text
$ bench --site frappe.localhost conductor doctor --demo

[1/6] Redis connectivity ............................................ OK  (127.0.0.1:11000 db=2)
[2/6] Default queues seeded ......................................... OK  (default, short, long, critical)
[3/6] Consumer groups exist ......................................... OK  (4 groups)
[4/6] XADD/XREADGROUP/XACK round-trip ............................... OK  (≈3.4ms)
[5/6] End-to-end demo dispatch (conductor.demo.echo) ................ OK  (job_id=… succeeded in 1.1s)
[6/6] Result round-trip (datetime, Decimal preserved) ............... OK

All checks passed. Conductor is healthy.
$ echo $?
0
```

Failure modes (non-zero exit, red output):
- Redis unreachable.
- Default queues missing.
- Demo job times out (> 10s) — likely no worker running.
- Demo job ends in `FAILED` — show traceback.

`bench conductor doctor` (no `--demo`): runs steps 1–4 only; suitable for liveness checks and CI.

## 11. Test Plan

### Unit (pytest, no site)

| File | Tests |
|---|---|
| `test_messages.py` | round-trip encode/decode; reject unknown `schema_version`; missing required fields raise; empty-string null-equivalent fields decode to `None` |
| `test_serialization.py` | msgpack of `datetime` (UTC + tz-aware), `Decimal`, nested dicts; oversize payload raises early |
| `test_streams.py` | `stream_key("aau.local", "default")` → `"conductor:aau.local:stream:default"`; `ensure_consumer_group` creates if missing, swallows BUSYGROUP, raises everything else |
| `test_config.py` | site_config layered with library defaults; missing `conductor.redis_url` falls back to bench's `redis_queue` |
| `test_context.py` | thread-local isolation between two threads; watchdog flips `should_cancel()` at deadline |

### Integration (Frappe site)

| Test | Asserts |
|---|---|
| `test_dispatcher_creates_row` | After `enqueue("conductor.demo.echo", x=1)`, a `Conductor Job` row exists with status=QUEUED, method, queue, kwargs round-trip |
| `test_dispatcher_writes_stream` | The row's `redis_msg_id` is present in the corresponding stream |
| `test_worker_consumes_and_succeeds` | Start worker thread, dispatch echo, wait ≤ 5s, row reaches SUCCEEDED, started_at < finished_at |
| `test_worker_records_failure` | Dispatch a function that raises; row reaches FAILED; `last_traceback` contains the exception class name |
| `test_worker_records_timeout` | Dispatch a function that ignores `should_cancel()`, set timeout=1s; row reaches TIMED_OUT (cooperative), watchdog fired |
| `test_doctor_clean_install` | `doctor --demo` exits 0 |
| `test_doctor_redis_down` | With Redis stopped, `doctor` exits 1 with the right error |
| `test_frappe_compat_shim` | `conductor.frappe_compat.enqueue("conductor.demo.echo", x=1)` produces an equivalent Conductor Job |

All tests written **before** the production code they validate, per `superpowers:test-driven-development`.

## 12. Risks Specific to Phase 0

1. **Frappe site context inside worker threads.** A worker thread that calls `frappe.get_attr(method)` must run inside `frappe.init`/`frappe.connect` context. Phase 0 binds one worker = one site, so we initialize once at process start and rely on Frappe's per-thread DB connection pool. Validate during implementation.
2. **Click commands wired through `hooks.py`.** Frappe expects `commands = [click_group]`. Confirmed pattern across Frappe community apps; cross-check during scaffolding.
3. **Procfile.conductor + `bench start`.** `bench start` reads the bench-root `Procfile`; auxiliary procfiles need explicit registration. Likely we ship the Procfile snippet and document opt-in (`cat Procfile.conductor >> /path/to/bench/Procfile`) rather than auto-injecting. Decide in implementation.
4. **OTel SDK init globally vs per-process.** Multiple workers in the same bench start process may double-init. Use a once-only guard.
5. **Demo function module path.** `conductor.demo.echo` lives inside the conductor app — must be importable from any process that runs the doctor.

## 13. Definition of Done (Phase 0)

All of the following must hold simultaneously, on a clean `frappe.localhost` install:

- [ ] `bench install-app conductor` succeeds; `Conductor Operator` role + 4 default queues seeded.
- [ ] `conductor.enqueue("conductor.demo.echo", x="hi")` from `bench console` returns a job_id; a `Conductor Job` row exists at status=QUEUED.
- [ ] `bench conductor worker --queue default` is running.
- [ ] Within ≤ 10s, the row transitions to `SUCCEEDED`; `Conductor Worker` row shows ALIVE with recent heartbeat.
- [ ] `bench conductor doctor --demo` exits 0.
- [ ] Killing the worker with SIGTERM during in-flight: row stays at the appropriate state (RUNNING if not yet finished — known limitation, Phase 1 recovers).
- [ ] All pytest + Frappe tests pass.
- [ ] `frappe.enqueue` shim works when a client app sets `override_whitelisted_methods["frappe.enqueue"] = "conductor.frappe_compat.enqueue"`.

## 14. Hand-off to Phase 1

Phase 1 brainstorm starts with these inputs:
- This spec's contracts (DocTypes, message format, worker loop shape) are stable.
- Open question that must be settled in Phase 1's brainstorm: **outbox pattern** decision (master §3 #12).
- Phase 1 adds: `Conductor Job Run`, `Conductor DLQ Entry`, `RetryPolicy`, `@conductor.job` decorator, idempotency lock, execution lock, in-worker delay drainer, stalled-message reclaim.

---

## Change Log

| Date | Change | Author |
|---|---|---|
| 2026-04-27 | Initial Phase 0 spec, approved by user. | osama.m@aau.iq |
