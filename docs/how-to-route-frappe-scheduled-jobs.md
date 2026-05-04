# Route Frappe `Scheduled Job Type` rows through Conductor

This page covers a single task: take over the existing **`Scheduled Job Type`** rows that ship with Frappe / ERPNext / HRMS so each tick is dispatched as a `Conductor Job` instead of an RQ job — without rewriting any application code.

You succeed when `bench --site SITE conductor doctor` reports **`[5/9]` Takeover queue coverage** and **`[6/9]` Pause scheduler when takeover active** as `OK`, and a forced trigger of one `Scheduled Job Type` row produces a matching `Conductor Job` row.

> **Not this — that.**
> If you want a *new* cron entry created in Conductor's own DocType, use [`how-to-schedule-jobs.md`](how-to-schedule-jobs.md). That page covers `Conductor Schedule` rows. **This** page is for the existing Frappe `Scheduled Job Type` rows you already have (`tabScheduled Job Type` — typically 100+ rows on a stock HRMS bench).

---

## Why two flags

Conductor catches Frappe scheduler ticks in **two complementary** ways:

| Flag | What it catches | Where it runs |
|---|---|---|
| `conductor_intercept_frappe_enqueue` | Direct in-process callers (application code, custom scripts, request handlers that call `frappe.enqueue(...)` from Python) | Every Frappe process at import time |
| `conductor_take_over_frappe_scheduler` | Frappe's own `bench schedule` ticks for `Scheduled Job Type` rows | The `conductor scheduler` process |

The intercept patch alone is **not** enough for `Scheduled Job Type` rows: Frappe's scheduler imports `enqueue` directly from `frappe.utils.background_jobs`, bypassing the patched `frappe.enqueue` reference. The takeover loop is what catches those ticks.

Set both flags on a bench that wants every job — application + scheduler — flowing through Conductor.

---

## Procedure 1 — Enable takeover

1. Stop bench (`Ctrl-C` on `bench start`).

2. Edit `sites/common_site_config.json` and add the takeover flag plus `pause_scheduler`:

    ```json
    {
      "conductor_take_over_frappe_scheduler": true,
      "pause_scheduler": 1
    }
    ```

    `pause_scheduler` stops Frappe's own scheduler from firing the same row. **Both schedulers fire each row → silent double-execution** if you skip this. The `[6/9]` doctor check guards the contract, but only after the fact.

3. (Recommended.) Also enable the in-process patch so application code is caught too:

    ```json
    {
      "conductor_intercept_frappe_enqueue": true,
      "conductor_take_over_frappe_scheduler": true,
      "pause_scheduler": 1
    }
    ```

4. Make sure `conductor_scheduler` is in your bench `Procfile`. The takeover loop runs as a thread inside the scheduler process; without that line the loop never starts.

    ```
    conductor_scheduler: bench --site <site> conductor scheduler
    ```

5. Make sure `conductor_worker` consumes `default` **and** `long`. The default queue map sends daily / weekly / monthly frequencies to `long`, hourly and minute frequencies to `default`. A worker that only consumes `default` will leave daily rows pending forever.

    ```
    conductor_worker: bench --site <site> conductor worker --queue default --queue long --concurrency 4
    ```

6. Restart bench (`bench start`) and verify:

    ```bash
    bench --site <site> conductor doctor
    ```

    Look for these three lines green:

    ```
    [5/9] Takeover queue coverage................................ OK  (all takeover queues covered (default, long))
    [6/9] Pause scheduler when takeover active................... OK  (pause_scheduler set as required)
    [7/9] frappe.enqueue shim active............................. OK  (frappe.enqueue patch active)
    ```

---

## Procedure 2 — Override the queue map

The default map routes `Daily`, `Weekly`, and `Monthly` rows to the `long` queue and everything else to `default`. To override, add `conductor_frappe_schedule_queue_map` to `common_site_config.json`:

```json
{
  "conductor_take_over_frappe_scheduler": true,
  "pause_scheduler": 1,
  "conductor_frappe_schedule_queue_map": {
    "Daily": "default",
    "Cron": "critical"
  }
}
```

Per-key override only — keys you do not set keep their default. Unknown frequency names fall back to `default`. Restart the scheduler to pick up the new map.

---

## Procedure 3 — Force-trigger one row to verify

The takeover loop only fires rows whose `is_event_due()` returns `True`. To verify a tick end-to-end without waiting for cron:

```bash
bench --site <site> console
```

```python
import frappe
doc = frappe.get_doc("Scheduled Job Type", "<scheduled_job_name>")
doc.last_execution = None  # force is_event_due() to return True
doc.save()
frappe.db.commit()
```

Wait one minute (the loop ticks once per minute). Then:

```bash
bench --site <site> conductor depth
```

The `default` (or `long`) row should show a non-zero stream entry, then `0` once the worker consumes it. Open the dashboard's **Live Feed** tab to watch the job land.

---

## Behavior — what to expect

- **Single attempt.** The takeover loop dispatches each tick with `max_attempts=1`. A failed `Scheduled Job Type` tick will **not** retry on the next cron event — it lands in the DLQ instead. This is intentional: Frappe's own scheduler does not retry either, and double-firing on retries can amplify side effects.
- **At-most-once per cron event** when the loop is up. After a successful dispatch the loop sets `Scheduled Job Type.last_execution`, which suppresses the next `is_event_due()` until the cron expression names a new tick.
- **Recovery on dispatch failure.** A dispatch failure leaves `last_execution` unchanged, so the next loop iteration retries the dispatch. A failure inside the job itself is a Conductor Job failure and lands in the DLQ via the normal retry path.
- **Tick interval.** The loop wakes every 60 s. A row whose cron expression names sub-minute ticks will only fire once per minute.

---

## If something went wrong

- **`[5/9] Takeover queue coverage` fails.** The doctor's error message names the missing queue and prints the exact `--queue` flag to add. Most often `long` is missing — append `--queue long` to your `conductor_worker` Procfile line and restart bench.
- **`[6/9] Pause scheduler when takeover active` fails.** `conductor_take_over_frappe_scheduler: true` is set but `pause_scheduler` is `false`. Set `pause_scheduler: 1` in `common_site_config.json` and restart bench. Without this, both schedulers fire the same row.
- **`[7/9] frappe.enqueue shim active` fails.** `conductor_intercept_frappe_enqueue: true` but the in-process patch did not install. Run `bench restart` to re-fire conductor's import-time bootstrap. If the failure persists, the patch path itself is broken — check the `conductor` logger output.
- **Doctor passes but nothing fires.** Open `Scheduled Job Type` in the Desk and confirm `Stopped` is unchecked on the rows you expect. The loop only enumerates rows where `stopped=0`.
- **Two jobs per cron event.** Frappe's own scheduler is still running. Confirm `pause_scheduler: 1` is set in `common_site_config.json` (not nested under `conductor.*`) and that the bench `Procfile` has no `schedule:` line — either guard alone is enough; both is fine.
- **Daily rows fire but stay `QUEUED`.** No worker is consuming the `long` queue. See Procedure 1 step 5.

---

## See also

- [`reference-configuration.md`](reference-configuration.md#bench-wide-flags-common_site_configjson) — every bench-wide flag.
- [`how-to-schedule-jobs.md`](how-to-schedule-jobs.md) — `Conductor Schedule` rows (Conductor's own cron mechanism, separate from Frappe's `Scheduled Job Type`).
- [`reference-cli.md`](reference-cli.md#doctor) — full `doctor` output.
- [`how-to-triage-failures.md`](how-to-triage-failures.md) — DLQ triage when a `Scheduled Job Type` tick fails.
