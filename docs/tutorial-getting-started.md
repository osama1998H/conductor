# Get started with Conductor

This tutorial walks you through a complete first-run experience: install Conductor on a site, configure Redis, start a worker and the scheduler, enqueue your first job, and verify the install end-to-end. Allow about 10 minutes.

You succeed when `bench conductor doctor --demo` exits 0 with all nine checks green.

This is the operator-first happy path. App-developer use cases (writing job functions, defining workflows) come after.

---

## What you'll build

A Conductor install on one Frappe site, with a worker process that picks up jobs you enqueue from the bench console. By the end you will know how to install, configure, run, and smoke-test a Conductor deployment.

---

## Before you start

You need:

- A Frappe bench (the directory containing `Procfile`, `apps/`, `sites/`).
- Redis running and reachable. The bench's standard `redis_queue` instance works.
- One Frappe site (the rest of the tutorial uses `frappe.localhost`; replace with yours).

---

## Step 1 — Install Conductor on the site

From the bench root:

```bash
bench --site frappe.localhost install-app conductor
```

The installer creates the default `Conductor Queue` rows (`critical`, `default`, `long`, `short`, `workflow`) and registers the role records. Verify:

```bash
bench --site frappe.localhost conductor doctor
```

Expected — exit code 0 and seven lines green. Each `OK` carries a parenthetical detail; the snippet below shows the form:

```
[1/9] Redis connectivity..................................... OK  (redis://…)
[2/9] Default queues seeded.................................. OK  (critical, default, long, short, workflow)
[3/9] Consumer groups exist.................................. OK  (groups created/verified)
[4/9] XADD/XREADGROUP/XACK round-trip........................ OK  (round-trip OK)
[5/9] Takeover queue coverage................................ OK  (takeover disabled — skipped)
[6/9] Pause scheduler when takeover active................... OK  (takeover disabled — skipped)
[7/9] frappe.enqueue shim active............................. OK  (intercept disabled — skipped)

All checks passed. Conductor is healthy.
```

Checks `[5/9]` through `[7/9]` are gated on the bench-wide flags that opt in to Frappe-scheduler takeover and the in-process `frappe.enqueue` patch; they pass with a `skipped` detail until you turn those flags on. The full check table lives in [`reference-cli.md`](reference-cli.md#doctor). To enable them, see [`how-to-route-frappe-scheduled-jobs.md`](how-to-route-frappe-scheduled-jobs.md).

If any check fails, see [If something went wrong](#if-something-went-wrong) at the end of this page before continuing.

---

## Step 2 — Configure the Redis URL

Open `sites/frappe.localhost/site_config.json` and add the `conductor` block:

```json
{
  "conductor": {
    "redis_url": "redis://127.0.0.1:11000/2",
    "default_queue": "default",
    "stream_max_len": 10000
  }
}
```

If you skip this step, Conductor falls back to the bench's `redis_queue` URL with the database forced to `2`. The fallback works for development; set `redis_url` explicitly in production.

The full key reference lives at [`reference-configuration.md`](reference-configuration.md).

---

## Step 3 — Start the worker and scheduler via Procfile

Conductor needs two long-lived processes per site: the worker (executes jobs) and the scheduler (runs cron, drains retries, reaps dead workers).

Add both to the bench's `Procfile`:

```bash
echo "conductor_worker: bench --site frappe.localhost conductor worker --queue default --concurrency 4" >> Procfile
echo "conductor_scheduler: bench --site frappe.localhost conductor scheduler" >> Procfile
```

Then run `bench start`. The bench launches both processes alongside the existing `redis`, `web`, etc. lines. Tail the log to confirm both are alive:

```
13:10:32 conductor_worker.1   | starting worker (queues=['default'], concurrency=4)
13:10:32 conductor_scheduler.1 | scheduler lock acquired
```

---

## Step 4 — Enqueue your first job

Open the bench console:

```bash
bench --site frappe.localhost console
```

Inside, dispatch a built-in Frappe utility (no app code needed):

```python
import conductor
job_id = conductor.enqueue("frappe.utils.now")
print(job_id)
```

The console prints a UUID. The worker log shows:

```
job_dispatched   job_id=<uuid> method=frappe.utils.now queue=default
job_started      job_id=<uuid> attempt=1
job_succeeded    job_id=<uuid>
```

---

## Step 5 — Watch it on the dashboard

Open `https://frappe.localhost/conductor-dashboard` (or your site's equivalent URL). Click the **Live Feed** tab. The job you just enqueued appears at the top with status `SUCCEEDED`. Click the row to see the full lifecycle, args, and result preview.

Other useful tabs at this point:

- **Overview** — number cards (queue depth, active workers, DLQ pending) and the queue depth bar chart.
- **Workers** — your `conductor_worker` process appears as `ALIVE`.

The dashboard polls `conductor.api.dashboard.get_state` every 2 seconds by default (configurable per site, see [`reference-configuration.md`](reference-configuration.md)).

---

## Step 6 — Run the full doctor

Now that a worker is running, the doctor's end-to-end demo passes too:

```bash
bench --site frappe.localhost conductor doctor --demo
```

Expected — all **nine** checks pass and exit code 0. Each `OK` carries a parenthetical detail (`(round-trip OK)`, `(takeover disabled — skipped)`, etc.); the lines below elide it for readability:

```
[1/9] Redis connectivity..................................... OK
[2/9] Default queues seeded.................................. OK
[3/9] Consumer groups exist.................................. OK
[4/9] XADD/XREADGROUP/XACK round-trip........................ OK
[5/9] Takeover queue coverage................................ OK
[6/9] Pause scheduler when takeover active................... OK
[7/9] frappe.enqueue shim active............................. OK
[8/9] End-to-end demo dispatch (conductor.demo.echo)......... OK
[9/9] Result round-trip...................................... OK

All checks passed. Conductor is healthy.
```

The demo dispatches `conductor.demo.echo`, waits for the worker to run it, and verifies the result round-trip. If `[8/9]` or `[9/9]` fails, the worker is not consuming the `default` queue — recheck `bench start` is running and that the `conductor_worker` line is alive.

---

## What's next

You have a working Conductor install. From here:

- [`how-to-enqueue-jobs.md`](how-to-enqueue-jobs.md) — write your own job functions and dispatch them from a Frappe app.
- [`how-to-schedule-jobs.md`](how-to-schedule-jobs.md) — set up cron-driven schedules.
- [`explanation-architecture.md`](explanation-architecture.md) — how Conductor is built (Redis streams, scheduler singleton, pool worker model).
- [`reference-cli.md`](reference-cli.md) — every `bench conductor *` subcommand.
- [`how-to-triage-failures.md`](how-to-triage-failures.md) — when (not if) something fails in production.

---

## If something went wrong

- **`doctor` step 1 (Redis connectivity) fails** — Redis is not running, or `conductor.redis_url` points at the wrong port. Check `redis-cli -p <port> ping` returns `PONG`.
- **Step 2 fails** — the install did not seed the default queues. Re-run `bench --site SITE install-app conductor`. If that fails, look at the install log for a stacktrace.
- **Step 3 fails** — Redis is reachable but rejected the consumer-group create. Usually a permissions issue on a managed Redis. Check the user has `XGROUP` access.
- **Step `[8/9]` or `[9/9]` fails with "demo job did not terminate within 10s"** — no worker is consuming the `default` queue. Confirm `bench start` is running and the `conductor_worker` line is alive.
- **Dashboard 404** — Conductor is installed but the static assets are not built. Run `cd apps/conductor/dashboard && yarn install && yarn build`, then `bench --site SITE clear-cache`.
- **`ImportError: No module named 'conductor'` in the console** — Conductor is not installed on the site you opened the console for. Install with `bench --site SITE install-app conductor`.
