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
   `--queue default --queue long`. **Plan-2 follow-up:** doctor
   health-gate that warns when worker queue coverage doesn't match the
   queue-map's range.
3. **`bench conductor dlq list` does NOT inherit bench's `--site`**
   (M3). CLI inconsistency. **Plan-2 follow-up:** make `dlq list`
   default `--site` from the bench context like every other subcommand.
4. **Honcho cascades a worker SIGKILL into a full bench outage** (M5).
   Operational, not a Conductor bug. **Plan-2 follow-up:** add a
   "process supervision" section to
   `docs/explanation-architecture.md` recommending systemd /
   supervisord / per-worker honcho instances over single-Procfile
   honcho for production multi-worker deployments.
5. **Inflight-cap test deferred** (M5). The test was interrupted by
   the SIGKILL cascade. Cheap to re-run.
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

## What's next

- **Plan-2 (M7).** Write after this session, informed by the findings
  backlog above. Items 2, 3, 4, 5, 7 are concrete code/doc changes.
- **Plan-3 (M8 + M9).** Stretch hardening (Procfile.conductor rewrite,
  `add_to_apps_screen` enable, doctor health-gate, optional CI smoke
  loop) + v2.0.0 release.
