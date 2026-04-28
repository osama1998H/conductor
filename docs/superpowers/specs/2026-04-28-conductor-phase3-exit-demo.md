# Phase 3 Exit-Criterion Demo Runbook

**Date:** 2026-04-28 (or the actual run date)
**Phase:** 3 — Dashboard
**Spec:** [Phase 3 Dashboard](2026-04-28-conductor-phase3-dashboard-design.md)
**Plan:** [Phase 3 Plan](2026-04-28-conductor-phase3-dashboard-plan.md)

**Exit criterion (verbatim from master §4):**
> "Operator can fully diagnose a failed job (find it, see its traceback, retry it) without SSH or `bench console`."

---

## Prerequisites (one-time setup; SSH/bench-console allowed here)

1. Build the dashboard:
   ```bash
   cd apps/conductor/dashboard && yarn install && yarn build && cd -
   ```

2. Clear Frappe's cache so the new `www/conductor-dashboard.html` is served:
   ```bash
   bench --site frappe.localhost clear-cache
   bench --site frappe.localhost clear-website-cache
   ```

3. Ensure a `Conductor Operator` user exists. If you only have a `System Manager` user, grant the role:
   ```bash
   bench --site frappe.localhost add-user-role <user> "Conductor Operator"
   ```

4. Start the worker + scheduler (two long-lived processes):
   ```bash
   bench --site frappe.localhost conductor worker --queue default --concurrency 2
   bench --site frappe.localhost conductor scheduler
   ```

5. Dispatch a job that will fail terminally. From a Python shell:
   ```bash
   bench --site frappe.localhost console
   ```
   ```python
   from conductor.dispatcher import enqueue
   enqueue("conductor.demo.boom", queue="default", max_attempts=2)
   ```

   `conductor.demo.boom` raises `ValueError("intentional boom")` on every call. With `max_attempts=2`, the job fails twice and lands in the DLQ.

---

## Demo (NO SSH or `bench console` allowed past this point)

**Setting:** browser, signed in as the Conductor Operator user.

### 1. Find the failed job

- Navigate to `https://<site>/conductor-dashboard`.
- The dashboard auto-redirects to `#/overview`. Confirm 4 number cards and 2 charts render.
- Click the **Jobs** tab.
- In the status filter dropdown, select `FAILED` (or `DLQ` — both should show the job).
- The failed job appears in the list within ~2 seconds (polling interval).

### 2. See the traceback

- Click the failed job's row. The right detail pane opens with the **Overview** sub-tab active.
- Confirm: status badge says `DLQ` (or `FAILED`); attempt counter says `2/2`; method is `conductor.demo.boom`.
- Confirm: `last_error_message` shows `intentional boom`.
- Click the **Traceback** disclosure. The Python traceback expands, showing the line in `conductor/demo.py` where the `ValueError` was raised.

### 3. Retry the job

- Still in the detail pane, click the **Retry** button.
- Confirm the JS confirm dialog ("Retry <job_id>?"); click OK.
- An alert reports the new job_id (`Re-enqueued as <new-id>`).
- Switch to the **Live Feed** tab. The new job appears at the top, transitioning `QUEUED` → `RUNNING` → `FAILED` → `DLQ` (it's the same `boom` method, so it fails again — the demo verifies the retry mechanism, not the recovery).

### 4. Sub-tab tour

- Click back into the original failed job's detail pane.
- Click the **Runs** sub-tab. Two `Conductor Job Run` rows appear (attempt 1, attempt 2), each with start/finish timestamps and the same traceback.
- Click the **Args** sub-tab. The decoded args + kwargs render as JSON.
- Click the **Trace** sub-tab. `trace_id` shows; `sentry_url` is empty (Phase 4 wires those exporters).

### 5. Section sanity check

- Click each remaining tab (DLQ, Schedules, Workers). Each renders without errors.
- DLQ: the failed job appears as a `PENDING_REVIEW` entry. Discard / edit-and-retry buttons are hidden (the Operator user lacks `System Manager`).
- Workers: at least one worker shows `ALIVE` with a fresh heartbeat.
- Schedules: lists any active `Conductor Schedule` rows (or "No schedules" if none).

If steps 1–3 work without leaving the browser, the **exit criterion is met**.

---

## Sign-off

Verified by: __________________  Date: __________________

Notes (any rough edges to file as bugs for Phase 3.5):
- ___
- ___
- ___
