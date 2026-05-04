# Conductor v2 — Certification Campaign Summary

**Branch:** `v2/certification` (28 commits ahead of `develop`)
**Window:** 2026-04-30 — 2026-05-04 (M1–M6 of the v2 plan)
**Status:** Plan-1 complete. Ready for Plan-2 (M7 fix backlog) and Plan-3 (M8–M9 hardening + release).

## Headline

The path A → B pivot was the campaign's load-bearing finding: the
in-process `frappe.enqueue` patch alone cannot catch Frappe scheduler
ticks because Frappe imports `enqueue` directly from
`frappe.utils.background_jobs` at module load. Conductor's scheduler
gained a fifth daemon loop that reads `tabScheduled Job Type` directly
and dispatches each due row through `conductor.dispatcher.enqueue`.

Over the 4-day soak after that pivot, **9299 successful dispatches**,
**0 failed**, **1 DLQ entry** (an upstream HRMS API mismatch caught and
recorded by Conductor — exactly the v2 KPI in action).

## What's done

| Phase | Artifact | Status |
|---|---|---|
| M1 | In-process patch + bootstrap + tests | ✅ commits d2fb465, 86296a9, a3543db, 97dccae |
| M1 | Takeover loop (path B) + tests | ✅ commit 7fbe354 |
| M1 | `baseline.md` | ✅ commits 9ab5109, 5951508, 955ffd4 |
| M2 | `scheduled-jobs.md` (105 rows × 4-day soak) | ✅ commit e40589a |
| M3 | `cli.md` (7 automated scenarios + interactive) | ✅ commit e05f8f8 |
| M4 | `dashboard.md` (27 scenarios via `expect` MCP) | ⏳ deferred — needs user-driven `expect` session |
| M5 | `multi-worker.md` (concurrency + reclaim findings) | ✅ commit 4e7ab7e |
| M6 | `soak.md` (4-day natural-cron coverage) | ✅ commit 0c428f0 |

## Findings backlog (for Plan-2 / M7)

1. **Path A bypass** (architectural; resolved by path B in this plan).
   Documented in `baseline.md` and the design doc
   `docs/superpowers/specs/2026-04-30-conductor-frappe-scheduler-takeover-design.md`.
2. **Queue-mismatch operator footgun** (M2). Takeover loop's queue-map
   sends Daily/Weekly/Monthly to `long`. If the bench worker doesn't
   listen on `long`, jobs strand silently. **Fix:** Procfile updated to
   `--queue default --queue long`. **M7 fix landed in commit `72a54aa`:**
   `bench conductor doctor` now warns when worker queue coverage doesn't
   match the takeover queue-map's range.
3. **`bench conductor dlq list` does NOT inherit bench's `--site`**
   (M3). CLI inconsistency. **Plan-2 follow-up:** make `dlq list`
   default `--site` from the bench context like every other subcommand.
4. **Honcho cascades a worker SIGKILL into a full bench outage** (M5).
   Operational, not a Conductor bug. **M7 resolution:** added the
   "Process supervision in production" section to
   `docs/explanation-architecture.md` recommending systemd /
   supervisord / split-Honcho over single-Procfile honcho for
   production multi-worker deployments. Reclaim correctness itself
   is unchanged and continues to be verified by
   `tests_chaos/test_kill_during_run.py`.
5. **Inflight-cap test deferred** (M5). **M7 resolution:** re-ran on
   2026-05-04 with `max_concurrent = 2` against the two-worker setup;
   inflight stayed ≤ 2 for the entire 60-second window across 200
   jobs and all reached SUCCEEDED. Captured in `multi-worker.md`. (Commit `032fd65`.)
6. **Real upstream-Frappe DLQ entry** caught: `delete_dynamic_links()
   got an unexpected keyword argument 'now'` (M3 finding). Not a
   Conductor bug; an HRMS/erpnext API mismatch. Demonstrates the v2
   KPI: failures that would have been silent under RQ are queryable
   via `bench conductor dlq list`.
7. **Dashboard surface (M4)** not exercised in this plan. Requires
   `expect` MCP session driven by user. Plan-2 should fold this in.

## Test surface

- 274 passed / 17 skipped at session close.
- 21 new tests for the in-process patch.
- 12 new tests for the takeover loop.
- 10 new tests for the v2-cert harnesses (scheduler driver + cli runner).
- No regressions in the existing v1 suite.

## Operational state at session close

- Bench `frappe.localhost` running with takeover active:
  - `conductor_take_over_frappe_scheduler: true` and
    `conductor_intercept_frappe_enqueue: true` in
    `common_site_config.json`.
  - `pause_scheduler: 1` so Frappe's own scheduler is the no-op
    cron-driver passthrough.
  - Two `bench --site frappe.localhost conductor worker --queue
    default --queue long --concurrency 4` workers under honcho.
- Backups for restoration: `Procfile.pre-v2`,
  `sites/common_site_config.json.pre-v2`.

## Plan-2 (M7) status — 2026-05-04

- ✅ Finding 3: dlq subcommands inherit --site (commit `c4d0bde`, follow-up `c94d044`)
- ✅ Finding 2: doctor warns on takeover queue-coverage gap (commit `72a54aa`, follow-ups `b1ea19b` + `a801881`)
- ✅ Finding 4: process-supervision recommendation in architecture doc (commit `d81f3b0`)
- ✅ Finding 5: inflight-cap test re-run; pass (commit `032fd65`)
- ✅ CLI gaps: cancel + schedule run-now automated (commit `c4a5f6f`)
- ⏳ Finding 7: M4 dashboard matrix — DEFERRED. Requires a human-driven `expect` MCP browser session walking the 27 scenarios in `tests/v2_certification/dashboard_scenarios.md`. Cannot be subagent-driven; the user picks this up when they next have an `expect` MCP session available. When done, the dashboard.md matrix lands and this bullet flips to ✅ with `<HASH-5>`.

Plan-2 closes the M7 fix backlog as far as automation reaches. The
five fix-and-document items are all green; the dashboard pass remains
open as a user task. Comparative KPI re-run + M8 stretch hardening +
v2.0.0 release belong to Plan-3.

## Pre-existing finding surfaced during Plan-2

Plan-2 Tasks 4+5 surfaced an existing TZ inconsistency in
`conductor/scheduler_loops.py:152` — the reaper computes its
heartbeat-age threshold via `datetime.now()` (local-naive) while
workers write `last_heartbeat` via `_now_naive()` (UTC-naive). The
reaper has been incorrectly marking workers GONE on any non-UTC
bench, but the workers re-assert `status='ALIVE'` every heartbeat,
which races the reaper's mark and masks the bug in production. The
new doctor check correctly uses UTC-naive (`b1ea19b`); the reaper
fix is a one-liner that belongs in Plan-3 alongside the rest of the
hardening pass.

## What's next

- **Dashboard M4** (this plan, deferred to user): walk
  `tests/v2_certification/dashboard_scenarios.md` × {light, dark}
  via `expect` MCP, populate
  `docs/roadmap/v2-certification/dashboard.md`, mark Finding 7 ✅.
- **Plan-3 (M8 + reaper TZ fix + KPI re-run + v2.0.0 release).**
  Stretch hardening (Procfile.conductor production shape,
  add_to_apps_screen enable, doctor's full health-gate including
  pause_scheduler assertion + shim assertion, optional CI smoke loop),
  reaper TZ fix surfaced above, comparative KPI re-run as a release
  gate, README + docs/index.md refresh, and the v2.0.0 tag + GitHub
  release notes.
