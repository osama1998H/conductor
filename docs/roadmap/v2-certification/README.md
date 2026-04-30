# Conductor v2 — Certification Artifacts

This directory holds the evidence produced by the v2 campaign described in
`docs/roadmap/v2.md`.

| Artifact | Phase | Shape |
|---|---|---|
| `baseline.md` | M1 | Day-0 snapshot of Redis keys + `tabConductor *` row counts before the campaign starts |
| `scheduled-jobs.md` | M2 | 105-row matrix: every `Scheduled Job Type` × `[force_trigger_outcome, conductor_job_id, attempts, duration_ms, soak_observed, notes]` |
| `cli.md` | M3 | Every `bench conductor` subcommand × `[command, args, expected, observed, pass]` |
| `dashboard.md` | M4 | Every (route, control) × `[page, control, expected, observed, screenshot, pass]` |
| `multi-worker.md` | M5 | Findings from multi-worker concurrency + reclaim test |
| `soak.md` | M6 | 7-day natural-cron observations |

A row counts as **pass** only when an actual `Conductor Job` row records the run end-to-end. Inline-only execution counts as fail.
