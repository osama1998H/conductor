# CLI reference

Reference for every `bench conductor *` subcommand. Each section gives the synopsis, options, examples, and exit codes.

Most subcommands take the site from `bench --site SITE`. Two subcommand groups (`dlq` and `migrate-from-rq`) take `--site` as their own required option instead — examples below use the form each command actually expects.

Run all examples from the **bench root** (e.g. `/path/to/frappe_15`), not from inside `apps/conductor`.

---

## `worker`

Run a long-lived worker process that pulls jobs from one or more queue streams and executes them.

```bash
bench --site SITE conductor worker [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--queue NAME` | `default` | Queue to consume. Repeat the flag to consume more than one queue. |
| `--concurrency N` | `4` | Threadpool size for executing jobs. |
| `--grace SECONDS` | `30` | Graceful shutdown timeout on SIGTERM. |
| `--sites VALUE` | bench `--site` | `auto` walks `sites/<dir>/site_config.json` and keeps sites with `conductor` in `installed_apps`. A comma-separated list (`alpha.test,beta.test`) runs in pool mode for those sites. When set, `--sites` overrides the bench `--site`. |

```bash
# Single-site:
bench --site frappe.localhost conductor worker --queue default --concurrency 8

# Pool mode — one process serves every conductor-installed site:
bench conductor worker --sites=auto --queue default --concurrency 8

# Pool mode — explicit list:
bench conductor worker --sites=alpha.test,beta.test --queue default
```

**Exit codes**

| Code | Meaning |
|---|---|
| `0` | Worker stopped cleanly after SIGTERM. |
| `2` | `--sites=auto` matched zero sites. Pass `--sites=...` explicitly. |

---

## `scheduler`

Run a long-lived scheduler process. The scheduler holds a singleton lock per site and runs the cron loop, the retry-delay drain, the dead-worker reaper, and the orphan sweeper. Multiple `scheduler` processes are safe — only the lock holder advances; the others poll and take over within ~20 s if the holder dies.

```bash
bench --site SITE conductor scheduler [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--lock-ttl-seconds N` | `15` | Singleton lock TTL. |
| `--renew-interval-seconds N` | `5` | How often the holder renews the lock. |
| `--poll-interval-seconds N` | `5` | How often non-holders poll for the lock. |

```bash
bench --site frappe.localhost conductor scheduler
```

---

## `doctor`

Run a fixed set of health checks against the Conductor install on a site. Used both as an acceptance test and as an on-call smoke test.

```bash
bench --site SITE conductor doctor [--demo]
```

| Option | Default | Meaning |
|---|---|---|
| `--demo` | off | After the fixed checks, also run a full enqueue → dispatch → execute → status round-trip. |

```bash
bench --site frappe.localhost conductor doctor
bench --site frappe.localhost conductor doctor --demo
```

**Exit codes**

| Code | Meaning |
|---|---|
| `0` | All checks passed. |
| `1` | One or more checks failed. The failing check name is the last line of stderr. |

---

## `schedule`

Manage cron-style schedules stored as `Conductor Schedule` rows. Schedules are created and edited in the Desk; the CLI is for fleet operations.

### `schedule list`

Print every schedule on a site, newest first.

```bash
bench --site SITE conductor schedule list
```

Columns: `NAME`, `EN` (1 = enabled), `CRON`, `TZ`, `NEXT_RUN`, `LAST_STATUS`.

### `schedule enable NAME`

Enable a schedule and recompute `next_run_at`.

```bash
bench --site SITE conductor schedule enable hourly-billing
```

### `schedule disable NAME`

Disable a schedule and clear `next_run_at`.

```bash
bench --site SITE conductor schedule disable hourly-billing
```

### `schedule run-now NAME`

Fire the schedule's payload immediately via `conductor.enqueue`. Updates `last_status` (`DISPATCHED` on success, `DISPATCH_FAILED` on failure) and `last_job`. Does **not** advance `last_run_at` — the cron cadence is preserved.

```bash
bench --site SITE conductor schedule run-now hourly-billing
```

**Exit codes** (apply to `enable`, `disable`, and `run-now`)

| Code | Meaning |
|---|---|
| `0` | Action succeeded. |
| `1` | Unknown schedule name, or `run-now` dispatch failed. |

---

## `dlq`

Operational subcommands over `Conductor DLQ Entry` rows. Unlike most subcommands, `dlq` takes its own required `--site` option.

### `dlq list`

List DLQ entries, newest first.

```bash
bench conductor dlq list --site SITE [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--site SITE` | required | Frappe site name. |
| `--queue NAME` | all | Filter to one queue. |
| `--status STATE` | all | One of `PENDING_REVIEW`, `RETRIED`, `DISCARDED`. |
| `--limit N` | `50` | Max rows to print. |

```bash
bench conductor dlq list --site frappe.localhost --queue default --limit 20
```

### `dlq retry`

Re-enqueue `PENDING_REVIEW` entries via `conductor.enqueue` and mark each row `RETRIED`. Pinning to a single job uses `--job`.

```bash
bench conductor dlq retry --site SITE [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--site SITE` | required | Frappe site name. |
| `--queue NAME` | all | Filter to one queue. |
| `--limit N` | `50` | Max rows to retry in one invocation. |
| `--job ID` | none | Operate on this specific `Conductor Job` id only. |

```bash
bench conductor dlq retry --site frappe.localhost --queue default --limit 50
bench conductor dlq retry --site frappe.localhost --job <job_id>
```

### `dlq discard`

Mark `PENDING_REVIEW` entries `DISCARDED` without re-enqueuing. Destructive — the underlying job is not run again.

```bash
bench conductor dlq discard --site SITE [OPTIONS]
```

Options match `dlq retry`.

```bash
bench conductor dlq discard --site frappe.localhost --job <job_id>
```

---

## `depth`

Print queue, DLQ, scheduled, and inflight depths per `Conductor Queue` row.

```bash
bench --site SITE conductor depth [--all-sites]
```

| Option | Default | Meaning |
|---|---|---|
| `--all-sites` | off | Walk every site with `conductor` in `installed_apps` and print one table per site. |

```bash
bench --site frappe.localhost conductor depth
bench conductor depth --all-sites
```

Columns: `queue`, `stream` (XLEN), `dlq` (XLEN), `scheduled` (per-site ZCARD), `inflight`, `max_rps`, `max_concurrent`.

---

## `migrate-from-rq`

One-shot migration from Frappe RQ to Conductor. Defaults to a dry-run preview; pass `--commit` to actually move jobs.

```bash
bench conductor migrate-from-rq --site SITE [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--site SITE` | required | Frappe site name. |
| `--queue-map MAP` | `short=short,default=default,long=long` | Comma-separated `rq_queue=conductor_queue` pairs. Unmapped RQ queues fall back to `default`. |
| `--commit` | off | Actually perform the migration. Without this flag, runs as a dry-run preview and prints the first five plan rows. |
| `--force` | off | Ignore the `conductor:{site}:rq_migrated_at` marker — used to re-run a previously-completed migration. |

```bash
# Preview:
bench conductor migrate-from-rq --site frappe.localhost

# Apply:
bench conductor migrate-from-rq --site frappe.localhost --commit

# Re-apply after a prior successful migration:
bench conductor migrate-from-rq --site frappe.localhost --commit --force
```

`--commit` (without `--force`) prompts for confirmation. The report at the end of every run prints: plan rows, moved count, skipped (other-site), skipped (callable method, not a dotted path), failed, and any unmapped RQ queues that fell back to `default`.

---

## `workflow`

Manage workflow definitions and runs.

### `workflow list`

Print every registered workflow plus its current version.

```bash
bench --site SITE conductor workflow list
```

Columns: `NAME`, `V` (version), `EN`, `LAST_BUMP`.

### `workflow run NAME`

Trigger a workflow run.

```bash
bench --site SITE conductor workflow run NAME [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--kwargs JSON` | `{}` | JSON object of input kwargs passed to the workflow. |
| `--idempotency-key KEY` | none | Dedup key — repeat invocations with the same key return the same `run_id`. |

```bash
bench --site frappe.localhost conductor workflow run OrderFulfillment \
  --kwargs '{"order_id": 42}' --idempotency-key ord-42
```

Prints the `run_id` on success. Exit `1` on invalid JSON kwargs or a dispatch failure.

### `workflow status RUN_ID`

Print the run's top-line status plus a per-step table.

```bash
bench --site SITE conductor workflow status <run_id>
```

Columns: `STEP`, `C` (Y if compensation), `STATUS`, `JOB`. Exit `1` on unknown `run_id`.

### `workflow cancel RUN_ID`

Best-effort cancel — sets the run's status to `CANCELLED`. **Does not** run compensations for steps already completed; for that, let the run fail naturally and rely on the compensation path. Exit `1` on unknown `run_id`.

```bash
bench --site SITE conductor workflow cancel <run_id>
```

---

## `cancel`

Soft-cancel a `Conductor Job` by id. The worker checks the cancel flag at lease boundaries; a job already running may finish before the cancel takes effect.

```bash
bench --site SITE conductor cancel JOB_ID
```

**Exit codes**

| Code | Meaning |
|---|---|
| `0` | Cancel flag set. |
| `1` | Already terminal, or unknown job id. |

---

## See also

- [`reference-configuration.md`](reference-configuration.md) — `site_config.json` keys, DocType fields, roles, the job state machine.
- [`how-to-triage-failures.md`](how-to-triage-failures.md) — when to use `dlq retry` vs `dlq discard`.
- [`reference-python-api.md`](reference-python-api.md) — the Python equivalents (`conductor.enqueue`, `run_workflow`, `cancel`).
