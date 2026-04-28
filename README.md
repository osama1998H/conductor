# Conductor

Reliability-first background job platform for Frappe / ERPNext.

![image](conductor.png)


Phase 0 ships the skeleton: dispatcher, worker, doctor, and the three core
DocTypes (`Conductor Queue`, `Conductor Job`, `Conductor Worker`). No retries,
no DLQ, no scheduler — those land in Phase 1+.

## Install

```bash
cd <bench>
bench get-app conductor <repo-url>           # or copy the app into apps/
bench --site <site> install-app conductor
bench --site <site> conductor doctor --demo  # acceptance test
```

## Run a worker (foreground)

```bash
bench --site <site> conductor worker --queue default --concurrency 4
```

## Run a worker via `bench start`

`bench start` reads `Procfile` at the bench root. Append our line:

```bash
cat apps/conductor/Procfile.conductor >> Procfile
```

## Use it

```python
import conductor
job_id = conductor.enqueue("myapp.tasks.send_email", queue="default", invoice="INV-001")
```

Or opt the whole app in by overriding `frappe.enqueue` in a client app's
`hooks.py`:

```python
override_whitelisted_methods = {"frappe.enqueue": "conductor.frappe_compat.enqueue"}
```

## Health check

```bash
bench --site <site> conductor doctor          # 4 checks, exit 0/1
bench --site <site> conductor doctor --demo   # adds full dispatch round-trip
```

## Configuration

In `sites/<site>/site_config.json`:

```json
{
  "conductor": {
    "redis_url": "redis://127.0.0.1:11000/2",
    "default_queue": "default",
    "stream_max_len": 10000
  }
}
```

If `conductor.redis_url` is not set, Conductor falls back to `redis_queue`
with DB **2** forced.

## Status

Phase 2 of 6. See `docs/superpowers/specs/2026-04-27-conductor-master-design.md`
for the full roadmap.

## Operations (Phase 2+)

Conductor has two long-lived processes per site:

- **`bench conductor worker`** — executes jobs from queue streams.
- **`bench conductor scheduler`** — singleton per site; owns the cron loop, retry-delay drain, dead-worker reap, and orphan sweep.

### Procfile

A typical bench Procfile entry alongside the existing services:

```
conductor_worker:    bench --site frappe.localhost conductor worker --queue default --concurrency 4
conductor_scheduler: bench --site frappe.localhost conductor scheduler
```

Multiple `conductor_scheduler` instances are safe — only one holds the lock; the others poll. If the lock holder dies, a peer takes over within ~20 s (master Phase 2 exit criterion).

### Schedule admin

```
$ bench --site SITE conductor schedule list
$ bench --site SITE conductor schedule enable <name>
$ bench --site SITE conductor schedule disable <name>
$ bench --site SITE conductor schedule run-now <name>
```

`run-now` fires the schedule's payload immediately via `conductor.enqueue` and updates `last_status` / `last_job` on the schedule row, but does **not** advance `last_run_at` — the cron cadence is unchanged.

### Schedules in the Desk

Create / edit schedules in **Conductor Schedule** under the Conductor module. Required fields: `cron_expression`, `timezone` (defaults to UTC), `method` (dotted path), `queue`. Validation runs the cron expression through `croniter` on save; bad expressions are rejected with a Frappe validation error.

Cron is at-least-once across scheduler crashes — if a scheduler dies between `conductor.enqueue(...)` and the `next_run_at` update, the next holder re-fires the schedule. Make your `method` idempotent if duplicate execution would corrupt state.

## Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/conductor
pre-commit install
```

## License

MIT
