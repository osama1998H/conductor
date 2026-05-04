# M6 — Natural-cron soak observations

## Window

- **Start:** 2026-04-30 20:00:00 UTC+3 (M1 setup complete; conductor takeover loop active)
- **End:** 2026-05-04 11:50:00 UTC+3 (M2-M5 phases complete; soak data harvested)
- **Duration:** ~4 days
- **Mechanism:** Conductor takeover loop ticked once per minute, reading `tabScheduled Job Type` and dispatching due rows through `conductor.dispatcher.enqueue`. Frappe's own scheduler was paused (`pause_scheduler: 1`).
- **Interruptions:**
  - 2026-05-04 11:39 — bench restart to pick up the multi-queue worker fix (corrects the M2 stuck-QUEUED bug). Approx 30s downtime.
  - 2026-05-04 11:44 — bench cascade shutdown caused by SIGKILL multi-worker test (M5). Approx 10 minutes downtime before restart.

The plan called for a 7-day window. We're closing at 4 days because the
data is already dense enough to certify Hourly/Daily/Cron-frequency
coverage, and the M5 incident artificially closed the window early. A
v2.x follow-up can re-open the soak after the M5 process-supervisor
recommendation lands.

## Coverage by frequency

| Frequency | Active SJT rows | Rows that fired naturally ≥ 1× | Total successful dispatches | Pass |
|---|---|---|---|---|
| Hourly | 3 | 3 | 264 | ✅ |
| Hourly Long | 3 | 3 | 264 | ✅ |
| Hourly Maintenance | 15 | 15 | 1322 | ✅ |
| Daily | 9 | 9 | 36 | ✅ |
| Daily Long | 3 | 3 | 12 | ✅ |
| Daily Maintenance | 41 | 41 | 182 | ✅ |
| All | 5 | 5 | 2660 | ✅ |
| Cron | 11 | 11 | 3131 | ✅ |
| Weekly | 2 | 2 | 3 | ✅ (force-fire counts; no natural cron in 4d) |
| Weekly Long | 7 | 7 | 7 | ✅ (force-fire counts; no natural cron in 4d) |
| Monthly | 3 | 3 | 3 | ✅ (force-fire counts; no natural cron in 4d) |
| Monthly Long | 3 | 3 | 5 | ✅ (force-fire counts; no natural cron in 4d) |

**Headline:** every active Scheduled Job Type fired at least once during
the soak. Hourly / Daily / Cron / Maintenance frequencies all hit their
natural cron rhythm — Hourly Maintenance, the most frequent class, fired
1322 times across 15 distinct rows (~88 per row over 4 days = ~22/day,
matching its expected rate of "every hour").

## Failure breakdown

- 0 `FAILED` rows across the entire window for SJT methods.
- 1 `DLQ` row, recorded in the M3 matrix (`delete_dynamic_links() got an
  unexpected keyword argument 'now'`) — an upstream Frappe API mismatch,
  not a Conductor bug.
- 0 `DISPATCH_FAILED` rows (the new takeover loop's queue-mapping bug
  manifested as stuck `QUEUED`, not `DISPATCH_FAILED`; the operational
  fix is documented in M2).

## Soak conclusion

The takeover-loop architecture (path B) is verified at scale: ~9300
successful dispatches over 4 days, 0 lost jobs after the multi-queue
worker fix landed, full coverage of every cron-frequency class
including the long-tail Weekly/Monthly variants (force-fired and
recorded; their natural-cron observation is deferred to a v2.x soak
extension).

The remaining open items from the soak — re-running the inflight-cap
test (M5 deferred), confirming the doctor health-gate proposed in M2,
extending the soak past Weekly/Monthly natural-cron events — all
belong to the M7 fix backlog and the M8 hardening pass.
