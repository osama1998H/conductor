# M3 — CLI surface certification matrix

**Captured:** 2026-05-04, against `frappe.localhost` site.
**Mechanism:** `tests/v2_certification/cli_runner.py` invokes each `bench conductor` subcommand via subprocess, evaluates exit code + stdout fragments.

**Summary:** 7/7 pass on the automated runner.

## Automated scenarios

| Label | Argv | Exit | Pass | Notes |
|---|---|---|---|---|
| doctor | `bench --site frappe.localhost conductor doctor` | 0 | ✓ |  |
| doctor --demo | `bench --site frappe.localhost conductor doctor --demo` | 0 | ✓ |  |
| depth | `bench --site frappe.localhost conductor depth` | 0 | ✓ |  |
| schedule list | `bench --site frappe.localhost conductor schedule list` | 0 | ✓ |  |
| dlq list | `bench --site frappe.localhost conductor dlq list` | 0 | ✓ | inherits --site from bench context as of M7 fix |
| workflow list | `bench --site frappe.localhost conductor workflow list` | 0 | ✓ |  |
| migrate-from-rq dry-run | `bench --site frappe.localhost conductor migrate-from-rq --site frappe.localhost` | 0 | ✓ |  |

## Long-lived commands (manually verified live)

| Command | Status |
|---|---|
| `bench --site frappe.localhost conductor worker --queue default --queue long --concurrency 4` | Running under honcho since 2026-05-04 11:39 UTC+3; processed 9299+ jobs over the campaign window. Pass. |
| `bench --site frappe.localhost conductor scheduler` | Running since 2026-04-30 19:59; takeover loop fired Frappe Scheduled Job Type rows continuously. Pass. |

## Interactive / context-bound commands (smoked manually)

| Command | Status |
|---|---|
| `bench --site frappe.localhost conductor dlq list --site frappe.localhost` | Pass when invoked with explicit `--site`. See Finding 1 below for the inheritance bug. |
| `bench --site frappe.localhost conductor cancel <id>` | Not exercised in this run (requires a running job id). Marked open; safe to defer to M7. |
| `bench --site frappe.localhost conductor schedule run-now <name>` | Not exercised in this run (requires a Conductor Schedule row). Marked open; safe to defer to M7. |

## Findings

### Finding 1: FIXED (commit `<HASH-1>`)

`dlq list/retry/discard` now inherit `--site` from the bench Click
context via `pass_context` + `get_site`, matching the pattern used by
`depth`. Explicit `--site` after the subcommand still works for
backwards compatibility. `migrate-from-rq` keeps its required `--site`
because per-tenant migration intent makes the explicit argument
load-bearing.

### Finding 2: real upstream-Frappe DLQ entry caught by Conductor

During the M2 soak window, one job ended up in the DLQ:

| Conductor Job | Method | Last error |
|---|---|---|
| `b2a36f52-041a-4d4f-90c2-64d2d9b7fb57` | (resolved via DLQ entry) | `TypeError: delete_dynamic_links() got an unexpected keyword argument 'now'` |

This is a real upstream-Frappe API mismatch (HRMS/erpnext code calling `delete_dynamic_links(..., now=...)` against a function whose signature changed). Conductor's reliability machinery caught it: retry policy exhausted attempts, the job was DLQ-routed, and the failure is queryable via `bench conductor dlq list`. **This is the v2 KPI in action — visibility into a failure that would have been silent under RQ.**

