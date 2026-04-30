# Schedule jobs

This page covers cron-style schedules: creating one in the Desk, managing schedules from the CLI, and writing the scheduled method so it survives at-least-once delivery.

You succeed when a `Conductor Schedule` row fires its method on the documented cadence and `last_status` flips to `DISPATCHED`.

The scheduler must be running for any of this to work — append `Procfile.conductor` to your bench's `Procfile` and run `bench start`. See [`reference-cli.md`](reference-cli.md#scheduler) for the long form.

---

## Procedure 1 — Create a `Conductor Schedule` in the Desk

1. Open the Desk: `https://<site>/app`. Search for **Conductor Schedule** in the awesome-bar and click **+ New**.

2. Fill the required fields:

    - **Schedule Name** — unique on the site (e.g., `hourly-billing-rollup`).
    - **Cron Expression** — five-field crontab format (`0 * * * *` for hourly on the minute). Validated against `croniter` at save time; bad expressions raise a Frappe validation error.
    - **Timezone** — IANA name (`UTC`, `Asia/Baghdad`, `America/New_York`). Defaults to `UTC` if left blank.
    - **Method** — dotted path to the function the schedule should enqueue (`myapp.tasks.billing_rollup`).
    - **Queue** — link to an enabled `Conductor Queue` row.

3. Optionally add `Args` / `Kwargs`. Both fields accept JSON; the scheduler decodes them and passes the kwargs to the method.

4. Set **Enabled** to checked. Save. The scheduler computes `next_run_at` from the cron expression and the timezone.

5. Confirm the schedule by listing from the CLI:

    ```bash
    bench --site frappe.localhost conductor schedule list
    ```

    The new row appears with `EN=1` and a future `NEXT_RUN`.

---

## Procedure 2 — Manage schedules from the CLI

The CLI is the right surface for fleet operations and on-call use.

```bash
# List all schedules on a site:
bench --site SITE conductor schedule list

# Toggle a schedule on or off:
bench --site SITE conductor schedule enable hourly-billing-rollup
bench --site SITE conductor schedule disable hourly-billing-rollup

# Fire a schedule's payload immediately (out-of-band of cron):
bench --site SITE conductor schedule run-now hourly-billing-rollup
```

`run-now` calls `conductor.enqueue(...)` with the schedule's method, queue, and kwargs. It updates `last_status` (`DISPATCHED` on success, `DISPATCH_FAILED` on failure) and `last_job` (the dispatched job id). It does **not** advance `last_run_at` — the next cron fire happens on its normal cadence.

`enable` and `disable` are System Manager only. `run-now` and `list` are available to Conductor Operator. See [`reference-configuration.md`](reference-configuration.md#roles-and-permissions).

---

## Procedure 3 — Make a scheduled method idempotent

Cron is at-least-once across scheduler crashes. If the holder dies between `conductor.enqueue(...)` and the `next_run_at` write, the next holder re-fires the schedule. The method runs twice.

The fix is at the method, not the schedule.

1. Identify a stable business key for "this run". Examples: the calendar hour, the billing period start, the report id.

2. Check whether work for that key is already done before doing it again:

    ```python
    import frappe

    def billing_rollup():
        period = frappe.utils.now_datetime().strftime("%Y-%m-%dT%H:00")
        if frappe.db.exists("Billing Rollup", {"period": period}):
            return  # already ran this hour
        ...  # do the work and insert the row
    ```

3. If the work cannot easily check itself (it calls an external API), wrap it with `idempotency_key=`:

    ```python
    @conductor.job(idempotency_key=lambda: frappe.utils.now_datetime().strftime("billing:%Y-%m-%dT%H:00"))
    def billing_rollup():
        ...
    ```

4. Verify by running the schedule twice in quick succession:

    ```bash
    bench --site SITE conductor schedule run-now hourly-billing-rollup
    bench --site SITE conductor schedule run-now hourly-billing-rollup
    ```

    Both calls should print a job id, but the same `job_id` (idempotency hit), and only one row of side-effect should result.

---

## If something went wrong

- **Schedule save fails with `Invalid cron expression`** — the expression does not parse via `croniter`. Test it at <https://crontab.guru> and copy the exact string.
- **Schedule never fires** — no scheduler is running for the site. Check `bench start` is up; check `bench --site SITE conductor schedule list` shows a `NEXT_RUN` in the future, not in the distant past.
- **`run-now` returns "unknown schedule"** — the name is case-sensitive and must match the `Schedule Name` field exactly.
- **`run-now` prints `dispatch failed: …`** — `last_status` was set to `DISPATCH_FAILED`. The error message names the cause (queue disabled, method not importable, JSON kwargs malformed). Fix and re-run.
- **The same calendar hour ran twice** — at-least-once delivery worked as designed; your method is not idempotent yet. Apply Procedure 3.
- **Timezone-related drift** — leaving the timezone blank defaults to UTC. The scheduler computes `next_run_at` against the named timezone, so a 3 a.m. cron expression in `America/New_York` will fire at 8 a.m. UTC.
