# Day-0 Baseline

**Captured:** 2026-04-30 19:38 UTC+3
**Site:** frappe.localhost
**Conductor branch:** v2/certification (commit `348d5a9`, base develop `54d2504`)
**Bench:** /Users/osamamuhammed/frappe_15
**Apps installed on site:** frappe, erpnext, hrms, datavalue_theme_15, conductor

## `bench conductor doctor --demo`

```text
[1/6] Redis connectivity.............................................. OK  (redis://127.0.0.1:11000/2)
[2/6] Default queues seeded........................................... OK  (critical, default, kpi-conductor, long, short, workflow)
[3/6] Consumer groups exist........................................... OK  (groups created/verified)
[4/6] XADD/XREADGROUP/XACK round-trip................................. OK  (round-trip OK)
[5/6] End-to-end demo dispatch (conductor.demo.echo).................. OK  (job_id=5071e994-8cd6-4a82-a458-f55f24a397de succeeded)
[6/6] Result round-trip............................................... OK  (round-trip preserved)

All checks passed. Conductor is healthy.
```

Exit code: **0**.

## Redis keyspace

Total `conductor:frappe.localhost:*` keys at port 11000 / db 2: **66**.

Sample keys (first 5):

```
conductor:frappe.localhost:dlq:default
conductor:frappe.localhost:dlq:kpi-conductor
conductor:frappe.localhost:idem:02897679ea64335194c1233f6580ed287a4c23b880f7619a289e53bbf322b13e
conductor:frappe.localhost:idem:0698702c89ec6d7d09e45dc60051d768951ccbdf5d05d73e7b81be8ad85c18e7
conductor:frappe.localhost:idem:0745b82539580b6bb94556c1e02f56d7a028631bcf60b1cf4e23d6126f429240
```

Most keys are pre-existing idempotency locks from prior testing — expected.

## MariaDB row counts

| DocType | Rows |
|---|---|
| Conductor Job | 191 |
| Conductor Job Run | 273 |
| Conductor DLQ Entry | 56 |
| Conductor Schedule | 4 |
| Conductor Worker | 507 |
| Conductor Workflow Run | 14 |
| Conductor Workflow Step Run | 60 |

These rows are pre-existing from the user's prior testing on this site. The
M2 campaign matrix (`scheduled-jobs.md`) must filter Conductor Job rows by
creation time after the M1 patch goes live, not absolute count, so pre-existing
rows do not pollute pass/fail counts.

## Active Scheduled Job Types

Active rows (`stopped = 0`) in `tabScheduled Job Type`: **105**.

This is the campaign target — M2 will force-trigger every one of these.

## Bench process state at capture time

- `honcho start` (= `bench start`) running, PID 33372
- One `bench worker` (RQ worker), PID 33403
- No `bench --site frappe.localhost conductor worker` process yet
- No `bench --site frappe.localhost conductor scheduler` process yet

This baseline precedes the M1 changes (Task 7 below). After Task 7, RQ worker
is stopped and conductor processes take over.

## M1 operational changes (Task 7) — applied 2026-04-30 19:39

- Set `conductor_intercept_frappe_enqueue: true` in `common_site_config.json`.
- Commented out the `worker:` entry in bench `Procfile`; added
  `conductor_worker:` and `conductor_scheduler:` lines.
- Backups: `Procfile.pre-v2`, `sites/common_site_config.json.pre-v2`.
- Restoration: `cp Procfile.pre-v2 Procfile && cp sites/common_site_config.json.pre-v2 sites/common_site_config.json`.

## M1 finding (real bug, fixed in commit `97dccae`)

The first restart after Task 7 had `flag in conf: True` but
`patch installed: False`. Root cause: the original bootstrap read the flag
at install time, but conductor is imported during Frappe's app discovery —
**before** `frappe.init()` populates `frappe.conf`. The bootstrap saw an
empty conf, silently no-op'd, and never re-fired.

Fix: bootstrap installs the patch unconditionally on conductor import; the
flag check moves into the patched function (call-time read from
`frappe.conf`). When the flag is unset, calls transparently fall through
to the original `frappe.enqueue` — zero behavior change for users who
haven't opted in.

After the fix and a fresh `bench start`:

```
flag in conf: True
patch installed: True
intercept enabled: True
site has conductor: True
```

## Bench process state after M1

- `honcho start`, PID 62473 (post-pivot restart)
- `bench --site frappe.localhost conductor worker --queue default --concurrency 4`, PID 62495
- `bench --site frappe.localhost conductor scheduler`, PID 62494 (now runs the new `frappe_scheduled_loop` thread)
- `bench schedule`, PID 62491 — running but **paused** via `pause_scheduler: 1`
- No RQ `bench worker` process

## M1 finding #2 — path A→B pivot (commits `0561cc4`, `7fbe354`)

The first smoke test against the live bench demonstrated that the in-process
`frappe.enqueue` patch does **not** catch Frappe scheduler ticks.
`Scheduled Job Type.enqueue()` does `from frappe.utils.background_jobs
import enqueue` at module load and calls that local binding — which the
patch on `frappe.enqueue` never sees. The smoke run produced zero
`Conductor Job` rows.

Pivot: Conductor's scheduler grew a fifth daemon loop
(`conductor/frappe_scheduled_loop.py`) that reads `tabScheduled Job Type`
directly, calls each row's `is_event_due()` for the cron-math, and
dispatches due rows through `conductor.dispatcher.enqueue`. No
monkey-patching. Frappe's own scheduler is paused via the bench-wide
`pause_scheduler: 1` flag.

The in-process patch ships and stays as a complementary catch-net for
direct in-process callers (application code, custom scripts, request
handlers) but is no longer the primary mechanism for scheduler ticks.

## M1 smoke (Task 8) — passes

After enabling `conductor_take_over_frappe_scheduler: true` and restarting
bench, the new loop fired on its first tick. From `conductor_scheduler.log`
at 2026-04-30T16:59:17Z:

```
event=frappe_scheduled_loop_started
event=job_enqueued ... (×14)
event=frappe_scheduled_loop_fired count=14
```

MariaDB confirms 14 Conductor Job rows created, all `SUCCEEDED` after one
attempt:

| method | status |
|---|---|
| erpnext.manufacturing.doctype.bom_update_log.bom_update_log.resume_bom_cost_update_jobs | SUCCEEDED |
| frappe.automation.doctype.reminder.reminder.send_reminders | SUCCEEDED |
| frappe.deferred_insert.save_to_db | SUCCEEDED |
| frappe.email.doctype.email_account.email_account.notify_unreplied | SUCCEEDED |
| frappe.email.doctype.email_account.email_account.pull | SUCCEEDED |
| frappe.email.queue.flush | SUCCEEDED |
| frappe.email.queue.retry_sending_emails | SUCCEEDED |
| frappe.integrations.doctype.google_calendar.google_calendar.sync | SUCCEEDED |
| frappe.model.utils.link_count.update_link_count | SUCCEEDED |
| frappe.monitor.flush | SUCCEEDED |
| frappe.search.sqlite_search.build_index_if_not_exists | SUCCEEDED |
| frappe.utils.global_search.sync_global_search | SUCCEEDED |
| frappe.utils.telemetry.pulse.client.send_queued_events | SUCCEEDED |
| hrms.hr.doctype.interview.interview.send_interview_reminder | SUCCEEDED |

End-to-end through Conductor: 14/14. Path B is verified live.
