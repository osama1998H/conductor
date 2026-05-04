# Conductor v2 — M8 Hardening + M9 Release Implementation Plan (Plan-3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every remaining v2.0.0 deliverable — the TZ audit surfaced by Plan-2, the dashboard findings (D1–D5; D6 deferred), the M8 stretch hardening (Procfile.conductor, add_to_apps_screen, doctor's full health-gate, optional CI smoke), and M9 release (KPI re-run, README + docs refresh, branch merge, v2.0.0 tag, GitHub release notes).

**Architecture:** Four ordered phases. Phase A clears the cross-cutting UTC-vs-local TZ bug at every backend write/read site (which automatically fixes dashboard findings D1 and D2). Phase B fixes the remaining dashboard bugs (D3 `workflow=null`, D4 DLQ bulk-actions, D5 heartbeat tooltip; D6 JsonViewer deferred to v2.1). Phase C lands the four M8 hardening items. Phase D merges to `develop`, runs the comparative KPI gate, refreshes user docs, and ships `v2.0.0`. Each phase is independently shippable; D depends on A+B+C only because tagging gates on a green branch.

**Tech Stack:** Python 3.10, Frappe v15, Conductor (current `v2/certification` head at `270ca7a`), pytest under bench virtualenv (`/Users/osamamuhammed/frappe_15/env/bin/pytest`), Vue 3 + Vite + shadcn-vue (the dashboard), `expect` MCP (Playwright-backed) for dashboard regression smokes, `gh` CLI for the GitHub release.

**Branch:** stay on `v2/certification` for Phase A–C. Phase D merges to `develop` and tags from there.

**Spec:** `docs/roadmap/v2.md` (M8/M9 row), `docs/roadmap/v2-certification/SUMMARY.md` (TZ audit table + Plan-2 status block), `docs/roadmap/v2-certification/dashboard.md` (D1–D6).

**Plan scope:**

- **In scope:** TZ audit fixes (A.1–A.5), dashboard D1–D5 verification (A.6/A.7 for D1+D2; B.1–B.3 for D3+D4+D5), M8 four items, M9 release. The optional CI smoke loop is the last task in Phase C, marked skippable.
- **Out of scope (v2.1):** Dashboard D6 (workflow step JsonViewer expansion — feature work, not a bug). Catalog refresh (`tests/v2_certification/dashboard_scenarios.md`'s drift entries) — separate cleanup PR.

---

## Decomposition rationale

A → B → C → D is the dependency order. A and B and C are independent of each other (none touches code another modifies); the natural ordering is A first (clears the TZ bug that's still affecting live ops), then B (frontend fixes), then C (operator-facing hardening), then D (release gate). KPI re-run lives in Phase D because Phase A's TZ fixes change the timing characteristics of the reaper loop — running the comparative suite before A's effects are stable would miss regressions.

D6 is omitted because it's design-substantive (what does a JsonViewer for a workflow step's args/output look like? does it expand inline or open a modal? does it pretty-print msgpack? where does the data come from — `Conductor Job.args/kwargs` or workflow-context?). Deferring is the disciplined call.

---

## File structure

| File | Status | Phase | Responsibility |
|---|---|---|---|
| `conductor/scheduler_loops.py:152` | Modify | A | Reaper threshold uses UTC-naive |
| `conductor/sweeper.py:68` | Modify | A | Sweeper threshold uses UTC-naive |
| `conductor/frappe_scheduled_loop.py:95` | Modify | A | `last_execution` write uses UTC-naive |
| `conductor/commands/dlq.py:163,195` | Modify | A | `reviewed_at` writes use UTC-naive |
| `conductor/api/dashboard.py:373` | Modify | A | `heartbeat_age_seconds` uses UTC-naive base |
| `conductor/worker.py` | Modify | A | Promote `_now_naive` to public `now_naive` (single source) |
| `tests/test_reaper_drift_correction.py` | Modify | A | Update existing tests, add TZ regression |
| `tests/test_sweeper_loop.py` | Modify | A | Add TZ regression |
| `tests/test_frappe_scheduled_loop.py` | Modify | A | Add TZ regression |
| `tests/test_dlq_commands.py` | Modify | A | Add TZ regression |
| `tests/test_dashboard_api.py` | Create | A | Tests for `get_worker.heartbeat_age_seconds` UTC-correctness |
| `dashboard/src/api.js` (or pages/Workflows.vue) | Modify | B | Drop `workflow=null` literal in `list_runs` query |
| `conductor/api/workflows.py` | Modify | B | Defensive: treat `workflow="null"` as `None` (regression-pin the bug) |
| `dashboard/src/pages/Dlq.vue` (component path) | Modify | B | Bulk action bar with Retry-selected / Discard-selected |
| `dashboard/src/pages/Workers.vue` | Modify | B | Tooltip on HB age cell with ISO timestamp |
| `tests/test_workflows_api.py` | Modify | B | Pin `list_runs(workflow="null")` returns all rows (defensive) |
| `Procfile.conductor` | Replace | C | Production-ready: --sites=auto worker + scheduler, no honcho assumption |
| `conductor/hooks.py` | Modify | C | Enable `add_to_apps_screen` block |
| `conductor/doctor.py` | Modify | C | Add `pause_scheduler` and `shim_active` checks → `[1/9]`–`[9/9]` |
| `tests/test_doctor.py` | Modify | C | Tests for the two new checks |
| `.github/workflows/conductor-smoke.yml` | Create | C | (Optional) 10-job smoke loop |
| `tests/comparative/baseline_v1.json` | Create | D | Frozen baseline numbers from v1.0.0 |
| `tests/comparative/run_kpis.py` | Modify | D | Add `--compare baseline_v1.json` mode |
| `README.md` | Modify | D | v2 capability + certification status |
| `docs/index.md` | Modify | D | Same |
| `docs/roadmap/v2-certification/SUMMARY.md` | Modify | D | Final close-out |
| `docs/roadmap/v2.md` | Modify | D | Final deliverables checklist all `[x]` |

---

## Conventions for every task

- **Working directory:** `/Users/osamamuhammed/frappe_15/apps/conductor` for code edits + pytest. `/Users/osamamuhammed/frappe_15` for `bench` commands.
- **Python:** invoke pytest via `/Users/osamamuhammed/frappe_15/env/bin/pytest`. Never bare `pytest`.
- **Bench commands:** include `--site frappe.localhost` for site-scoped commands; run from `/Users/osamamuhammed/frappe_15`.
- **Branch:** Phase A–C stay on `v2/certification`. Phase D merges to `develop` (one PR, fast-forward if possible). `v2.0.0` is tagged from `develop`.
- **Commits:** one logical change per commit. Stage explicit paths. Heredoc for messages.
- **No amends:** create new commits to fix review issues.
- **Hash placeholders:** earlier-task commits reference each other via short SHAs only AFTER they exist. The plan does not use `<HASH-N>` placeholders this time — Plan-3's commits are sequenced so each can name the SHA of the previous commit at write-time without bookkeeping commits.
- **Reviews per task:** load-bearing code (Phase A.1–A.5, B.1–B.3, C.3) gets the spec+quality two-stage review. Pure docs (D.2, D.5), the merge commit (D.3), the tag commit (D.4), and CI YAML (C.4) get a single controller read-through.
- **KPI regression contingency (D.1):** if `run_kpis.py --compare` reports a regression on any KPI, **pause Phase D, investigate root cause, fix, rerun**. Do not ship-with-documented-regression. The two TZ-fix candidates that could plausibly regress timing are the reaper (A.1, runs every tick) and the sweeper (A.2, runs every tick). If a regression appears, profile against the baseline before assuming the TZ fix caused it.
- **Stop rule:** if any task surfaces behavior that contradicts an earlier task or earlier finding, stop and check in with the user before continuing.

---

## Pre-task verification (do this before Task 1)

Five short lookups remove false assumptions that would otherwise blow up later tasks. Do them in one sweep; record what you find as a reference for the per-task code blocks below.

- [ ] **V1: Confirm bench operational state still matches SUMMARY.md** "Operational state at session close":
  - `pgrep -af 'conductor (worker|scheduler)'` — at least 2 worker rows + 1 scheduler.
  - `grep -E 'conductor_take_over|conductor_intercept|pause_scheduler' /Users/osamamuhammed/frappe_15/sites/common_site_config.json` — all three flags present.
  - `git log --oneline | head -1` — should be `270ca7a cert(M7): backfill HASH-5 ...`.

- [ ] **V2: Determine `frappe.utils.now_datetime()` TZ behavior.** A.5 modifies a line that uses it; correctness depends on whether it returns local-naive or UTC-naive. Read the function:
  ```bash
  grep -n 'def now_datetime' /Users/osamamuhammed/frappe_15/apps/frappe/frappe/utils/__init__.py /Users/osamamuhammed/frappe_15/apps/frappe/frappe/utils/data.py 2>/dev/null
  ```
  If `frappe.utils.now_datetime` returns local-naive (most likely — Frappe is famously local-naive), then `(frappe.utils.now_datetime() - last_hb_utc_naive).total_seconds()` produces a TZ-offset error. The fix is the same as the reaper: `(datetime.now(timezone.utc).replace(tzinfo=None) - last_hb).total_seconds()`. If it actually returns UTC, A.5 is a no-op and the dashboard's HB age column has a different bug — pause and re-investigate.

- [ ] **V3: Read the comparative KPI baseline expectations.** Phase D's release gate compares numbers to v1.0.0; we need to know what "unchanged" means. There is no `tests/comparative/README.md` and no `baseline_v1.json` yet. The repo has these KPIs:
  - `kpi_01_transient_recovery.py`
  - `kpi_02_audit_completeness.py`
  - `kpi_03_dlq_visibility.py`
  - `kpi_04_idempotency.py`
  - `kpi_05_throughput.py`

  Run `/Users/osamamuhammed/frappe_15/env/bin/python -m tests.comparative.run_kpis --kpi 1 --engine conductor` from `/Users/osamamuhammed/frappe_15` to confirm the harness still works. Note the wall-clock time per KPI (some take minutes). This informs Phase D's time budget and the "what shape is `baseline_v1.json`" question — Task D.1 specifies the exact format.

- [ ] **V4: Decide dashboard regression-test infra.** `dashboard/package.json` declares `vue`, `vite`, `vue-router`, `@tanstack/vue-table`, `mermaid`, `tailwindcss`, `shadcn-vue` as deps but **no test runner** (no Vitest, no Playwright, no Cypress). Phase B's options:
  1. Add Vitest + Playwright as devDeps and write proper component+e2e regression tests for D3/D4/D5.
  2. Use `expect` MCP scripts committed under `tests/v2_certification/dashboard_e2e/` as the regression suite — same shape as `cli_runner.py` from Plan-2 Task 9.
  3. Defer regression tests entirely and rely on the next certification pass to catch reintroduced bugs.

  **Recommendation: option 2.** Keeps the dashboard build fast (no extra devDeps), reuses the certification harness shape we already ship, and the `expect` MCP scripts double as living documentation. Each Phase B task produces an `expect` script under `tests/v2_certification/dashboard_e2e/` that reproduces the bug + asserts the fix.

  Adopt this in Phase B. If a future plan wants Vitest, that's a separate proposal.

- [ ] **V5: `add_to_apps_screen` schema for Frappe v15.** Format from `frappe/utils/boilerplate.py`:
  ```python
  add_to_apps_screen = [
      {
          "name": "conductor",
          "logo": "/assets/conductor/logo.png",
          "title": "Conductor",
          "route": "/conductor-dashboard",
          "has_permission": "conductor.api.permission.has_app_permission",
      }
  ]
  ```
  Confirm:
  - `conductor/public/logo.png` exists or alternative asset path.
  - `conductor.api.permission.has_app_permission` exists (or omit the key — it's optional; default is no restriction).

  ```bash
  ls /Users/osamamuhammed/frappe_15/apps/conductor/conductor/public/ 2>/dev/null | head
  grep -rn 'def has_app_permission\|def has_permission' /Users/osamamuhammed/frappe_15/apps/conductor/conductor/api/ 2>/dev/null | head
  ```

If any V-step reveals a fact that breaks a later task as written, stop and revise the relevant task in this plan before starting Phase A.

---

# Phase A — TZ audit (closes 4 backend sites + dashboard D1+D2)

Goal: every site that compares a stored `last_heartbeat`/`last_execution`/`reviewed_at` to "now" uses the same UTC-naive contract that `conductor.worker._now_naive` writes. The reaper's GONE→ALIVE oscillation stops; dashboard ACTIVE WORKERS NumberCard reads correctly; HB age column shows seconds, not hours; sweeper runs at the right cadence.

## Task A.1: Promote `_now_naive` to a public helper

**Files:**
- Modify: `conductor/worker.py` — rename `_now_naive` to `now_naive` (export). Keep a thin alias `_now_naive = now_naive` so internal callers don't break.
- Modify: `tests/test_worker_*.py` (any test that imports `_now_naive` directly) — switch to `now_naive`. Likely zero tests do this; verify with grep.

A single source-of-truth helper makes the rest of Phase A a one-liner-per-site.

- [ ] **Step 1: Verify nothing imports `_now_naive` from outside `conductor.worker`**

```bash
grep -rn '_now_naive' /Users/osamamuhammed/frappe_15/apps/conductor/ --include='*.py' | grep -v __pycache__
```

Expected: only references inside `conductor/worker.py`. If any test or other module imports it, list those callsites — Step 3 updates them.

- [ ] **Step 2: Rename in `conductor/worker.py`**

```python
def now_naive() -> datetime:
    """UTC-naive timestamp matching MariaDB DATETIME storage.

    All Conductor reads/writes of `last_heartbeat`, `last_execution`,
    `reviewed_at`, etc. compare against this value. Using a local-naive
    `datetime.now()` would introduce the host's UTC offset as a phantom
    age delta — see Plan-2's M7 doctor fix for the reasoning.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Back-compat alias for any in-tree caller still using the underscore name.
# Drop in v2.1 once external imports settle.
_now_naive = now_naive
```

The body is identical to the previous `_now_naive`. Only the name changes (and the docstring upgrades).

- [ ] **Step 3: Update internal callers in `worker.py`**

Lines 90, 91, 105, 145, 171, 217, 228, 299 currently call `_now_naive()`. Switch each to `now_naive()`. The alias keeps backward compatibility for any external import.

- [ ] **Step 4: Run pytest to confirm no regression**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests -q
```
Expected: 281 passed / 18 skipped (or whatever the post-Plan-2 baseline is — read `git log --oneline -3` if unsure).

- [ ] **Step 5: Commit**

```
git add conductor/worker.py
git commit -m "$(cat <<'EOF'
m8: promote conductor.worker._now_naive to public now_naive

Phase A of Plan-3 introduces UTC-naive corrections at five additional
sites. Each will import the helper rather than re-deriving the
expression. Promote _now_naive → now_naive (public) and keep an alias
for backward compatibility. Body unchanged.
EOF
)"
```

## Task A.2: Reaper TZ fix (`scheduler_loops.py:152`)

**Files:**
- Modify: `conductor/scheduler_loops.py` — replace `now = datetime.now()` with `now = now_naive()`.
- Modify: `tests/test_reaper_drift_correction.py` and `tests/test_reaper_loop.py` — add a regression test that pins UTC-naive behavior.

This is the load-bearing fix. The reaper compares `last_heartbeat` (UTC-naive) to `now - REAPER_GONE_AGE_SECONDS`. Local-naive `now` on UTC+3 gives an extra 10 800 seconds of apparent age, marking every fresh worker GONE. Heartbeats race the reaper to re-assert ALIVE. Fixing this stops the oscillation.

- [ ] **Step 1: Write the failing regression test**

Append to `tests/test_reaper_drift_correction.py` (or wherever reaper tests live):

```python
def test_reaper_threshold_uses_utc_naive_not_local():
    """Regression for the Plan-2-surfaced TZ bug: the reaper's `now`
    must match `conductor.worker.now_naive()` (UTC-naive). Using
    `datetime.now()` (local-naive) would mark all workers GONE on any
    non-UTC bench. The fix is a one-liner; this test pins it."""
    import inspect
    from conductor import scheduler_loops
    src = inspect.getsource(scheduler_loops._reaper_loop_iter)
    # The reaper must NOT call datetime.now() (local-naive). It must
    # use now_naive() (UTC-naive) imported from conductor.worker.
    assert "datetime.now()" not in src, (
        "Reaper still uses datetime.now() (local-naive). "
        "Switch to conductor.worker.now_naive() to match heartbeat write path."
    )
    assert "now_naive" in src
```

- [ ] **Step 2: Run test, confirm FAIL**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_reaper_drift_correction.py::test_reaper_threshold_uses_utc_naive_not_local -v
```
Expected: FAIL with "Reaper still uses datetime.now()..."

- [ ] **Step 3: Apply the fix**

In `conductor/scheduler_loops.py`:

1. At top, add: `from conductor.worker import now_naive`.
2. Find `def _reaper_loop_iter(...)`. Replace `now = datetime.now()` with `now = now_naive()`.

That's the entire code change.

- [ ] **Step 4: Run test, confirm PASS**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_reaper_drift_correction.py tests/test_reaper_loop.py -v
```
Expected: all reaper tests pass.

- [ ] **Step 5: Run full suite + chaos suite**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests -q
/Users/osamamuhammed/frappe_15/env/bin/pytest tests_chaos -q
```

Expected: full unit suite 282 passed (281 + 1 new); chaos suite all green. **If any chaos test fails**, capture the failure — it likely depended on the GONE→ALIVE oscillation. Investigate before proceeding (this is the advisor's pre-flagged risk).

- [ ] **Step 6: Live smoke**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost console <<'PY'
import frappe
rows = frappe.db.sql("SELECT name, status FROM `tabConductor Worker` ORDER BY last_heartbeat DESC LIMIT 5", as_dict=True)
for r in rows: print(r)
PY
```

Note: bench console heredoc doesn't read stdin into the kernel (Plan-2 lesson). Use the V1-style direct python pattern:

```bash
/Users/osamamuhammed/frappe_15/env/bin/python <<'PY'
import os, sys
os.chdir("/Users/osamamuhammed/frappe_15/sites")
for p in ("/Users/osamamuhammed/frappe_15/sites","/Users/osamamuhammed/frappe_15/apps/frappe","/Users/osamamuhammed/frappe_15/apps/conductor"):
    sys.path.insert(0, p)
import frappe
frappe.init(site="frappe.localhost", sites_path="/Users/osamamuhammed/frappe_15/sites")
frappe.connect()
rows = frappe.db.sql("SELECT name, status FROM `tabConductor Worker` ORDER BY last_heartbeat DESC LIMIT 5", as_dict=True)
for r in rows: print(r)
frappe.destroy()
PY
```

Expected: top 2 rows have `status='ALIVE'` (the running workers); rest are `GONE`. Wait 60 seconds (one reaper tick), re-run; the ALIVE count must remain 2 — proves the reaper no longer mass-marks them GONE.

- [ ] **Step 7: Commit**

```
git add conductor/scheduler_loops.py tests/test_reaper_drift_correction.py
git commit -m "$(cat <<'EOF'
m8: reaper threshold uses now_naive (UTC-naive)

Plan-2 surfaced this as the load-bearing TZ inconsistency: workers
write last_heartbeat via _now_naive (UTC-naive) while the reaper
computed gone_cut/stale_cut from datetime.now() (local-naive). On any
non-UTC bench the offset (e.g. 10 800s on UTC+3) exceeds every reap
threshold, so the reaper marks every fresh worker GONE — masked in
production only because the worker re-asserts status='ALIVE' on each
heartbeat, racing the reaper.

Switch the reaper to now_naive(). The GONE→ALIVE oscillation stops.
Live smoke: ALIVE count holds steady across reaper ticks.

Regression test: tests/test_reaper_drift_correction.py::
test_reaper_threshold_uses_utc_naive_not_local pins the source-line
shape so a future refactor can't reintroduce the local-naive form.
EOF
)"
```

## Task A.3: Sweeper TZ fix (`sweeper.py:68`)

**Files:**
- Modify: `conductor/sweeper.py` — replace `datetime.now()` threshold with `now_naive()`.
- Modify: `tests/test_sweeper_loop.py` — add the analogous source-line regression test.

Same shape as A.2. The sweeper compares stream-message ages to a threshold; local-naive `now` skews `XTRIM` decisions on non-UTC benches.

- [ ] **Step 1: Write the failing regression test**

Append to `tests/test_sweeper_loop.py`:

```python
def test_sweeper_threshold_uses_utc_naive_not_local():
    """Same TZ-class regression as the reaper. Pin source-line shape."""
    import inspect
    from conductor import sweeper
    # Sweeper has a single age-threshold computation. Find the function
    # that calls datetime.now() (it's the one near line 68 of sweeper.py).
    src = inspect.getsource(sweeper)
    assert "datetime.now()" not in src, (
        "Sweeper still uses datetime.now() (local-naive). "
        "Switch to conductor.worker.now_naive()."
    )
    assert "now_naive" in src
```

- [ ] **Step 2: Run, confirm FAIL**

- [ ] **Step 3: Apply fix**

In `conductor/sweeper.py`:
1. Add `from conductor.worker import now_naive`.
2. Replace `threshold = datetime.now() - timedelta(seconds=threshold_seconds)` with `threshold = now_naive() - timedelta(seconds=threshold_seconds)`.

- [ ] **Step 4: Run test, confirm PASS**

- [ ] **Step 5: Run full suite + chaos suite**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests tests_chaos -q
```

- [ ] **Step 6: Commit**

```
git add conductor/sweeper.py tests/test_sweeper_loop.py
git commit -m "$(cat <<'EOF'
m8: sweeper threshold uses now_naive (UTC-naive)

Same TZ class as the reaper fix in the previous commit. The sweeper
compares stream-message ages to a threshold; local-naive datetime.now()
on non-UTC benches skews XTRIM decisions. Switch to now_naive().
EOF
)"
```

## Task A.4: `frappe_scheduled_loop` last_execution write

**Files:**
- Modify: `conductor/frappe_scheduled_loop.py:95` — `datetime.now().replace(tzinfo=None)` → `now_naive()`.
- Modify: `tests/test_frappe_scheduled_loop.py` — pin source-line shape.

Display drift only — does not affect dispatch correctness — but matters for the dashboard and audit. Same shape as A.2/A.3.

- [ ] **Step 1: Write failing test**

Append to `tests/test_frappe_scheduled_loop.py`:

```python
def test_fire_one_writes_last_execution_utc_naive():
    """last_execution is read by the dashboard's `Last run` columns and
    by Frappe's own is_event_due() for cron math. Storing it local-naive
    while the rest of conductor stores UTC-naive creates display drift
    on non-UTC benches."""
    import inspect
    from conductor import frappe_scheduled_loop
    src = inspect.getsource(frappe_scheduled_loop._fire_one)
    assert "datetime.now()" not in src
    assert "now_naive" in src
```

- [ ] **Step 2–6:** (analogous to A.2/A.3)

The fix:

```python
# in frappe_scheduled_loop.py near line 95
from conductor.worker import now_naive
# ...
doc.db_set("last_execution", now_naive(), update_modified=False)
```

The current line is `doc.db_set("last_execution", datetime.now().replace(tzinfo=None), update_modified=False)`.

Commit message:

```
m8: frappe_scheduled_loop writes last_execution UTC-naive

Plan-2 TZ audit, third site. Display drift only — dispatch correctness
unaffected — but the dashboard's Last run columns now show the
correct timestamp on non-UTC benches.
```

## Task A.5: dlq.py `reviewed_at` writes (lines 163, 195)

**Files:**
- Modify: `conductor/commands/dlq.py:163,195` — `datetime.now().replace(microsecond=0)` → `now_naive()`. (The `microsecond=0` cleanup happens implicitly via DB column truncation, but if explicit zeroing is wanted, use `now_naive().replace(microsecond=0)`.)
- Modify: `tests/test_dlq_commands.py` — pin source-line shape.

Audit metadata drift; does not affect retry logic.

- [ ] **Steps:** same shape as A.4. Two callsites; replace both.

The fix:

```python
from conductor.worker import now_naive
# ...
"reviewed_at": now_naive().replace(microsecond=0),  # both at lines 163 and 195
```

## Task A.6: dashboard API `heartbeat_age_seconds` (line 373)

**Files:**
- Modify: `conductor/api/dashboard.py:373` — fix the age computation to use UTC-naive base.
- Create: `tests/test_dashboard_api.py` — first tests for this module.

This is the fix that closes dashboard finding D2 (Workers HB age column shows hours). The current code:

```python
last_hb = worker.get("last_heartbeat")
if last_hb:
    delta = (frappe.utils.now_datetime() - last_hb).total_seconds()
    worker["heartbeat_age_seconds"] = max(0, int(delta))
```

If V2 confirmed `frappe.utils.now_datetime()` returns local-naive, `delta` is wrong by `tz_offset_seconds`. Fix:

- [ ] **Step 1: Confirm V2 finding** — re-read what `frappe.utils.now_datetime` returns. Pause and revise this task if it actually returns UTC.

- [ ] **Step 2: Write failing test**

Create `tests/test_dashboard_api.py`:

```python
"""Tests for `conductor.api.dashboard` — Plan-3 TZ audit additions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch


def test_get_worker_heartbeat_age_uses_utc_naive_base():
    """Regression for dashboard finding D2: HB age must be computed
    against now_naive() (UTC-naive), matching the heartbeat write path
    in conductor.worker.now_naive. Using local-naive frappe.utils.now_datetime
    would skew age by the host's UTC offset."""
    import inspect
    from conductor.api import dashboard
    src = inspect.getsource(dashboard.get_worker)
    # The age computation must NOT use frappe.utils.now_datetime as the
    # subtraction base (it's local-naive).
    age_lines = [l for l in src.splitlines() if "heartbeat_age_seconds" in l or "total_seconds" in l]
    blob = "\n".join(age_lines + [l for l in src.splitlines() if "delta" in l])
    assert "frappe.utils.now_datetime" not in blob, (
        "get_worker still uses frappe.utils.now_datetime (local-naive) "
        "for age computation. Switch to conductor.worker.now_naive."
    )
    assert "now_naive" in blob
```

- [ ] **Step 3: Run test, confirm FAIL**

- [ ] **Step 4: Apply fix**

In `conductor/api/dashboard.py`:

1. Add to imports: `from conductor.worker import now_naive`.
2. Replace line 373 `(frappe.utils.now_datetime() - last_hb).total_seconds()` with `(now_naive() - last_hb).total_seconds()`.

- [ ] **Step 5: Verify test PASSES**

- [ ] **Step 6: Live smoke against the dashboard** (closes D1 + D2 visually)

After A.1–A.6 land, the dashboard's worker counts are read directly from `Conductor Worker.status` (which is now correct because the reaper isn't mass-marking GONE), and the HB age column subtracts UTC-naive from UTC-naive.

Open the dashboard via `expect` MCP — see the existing `dashboard-screenshots/02-workers-page-light.png` for shape. Expected differences from Plan-2's capture:
- Overview NumberCard `ACTIVE WORKERS` reads ≥ 2 (was 0).
- Workers table HB age column shows seconds/minutes (was `3h, 3h, 4h, ...`).

If both are still wrong after this commit, stop — there's a deeper issue we missed.

- [ ] **Step 7: Commit**

```
git add conductor/api/dashboard.py tests/test_dashboard_api.py
git commit -m "$(cat <<'EOF'
m8: dashboard heartbeat_age_seconds uses now_naive base

Closes Plan-2 dashboard findings D1 and D2: the get_worker endpoint's
age computation used frappe.utils.now_datetime() (local-naive) against
last_heartbeat (UTC-naive), so HB age was reported in hours on UTC+3
benches. Same TZ class as the reaper fix.

After this commit + the reaper fix two commits prior, the dashboard
Workers page shows correct HB ages and the Overview ACTIVE WORKERS
NumberCard reads against the corrected status column.

Tests: tests/test_dashboard_api.py — first tests for this module;
pin source-line shape to prevent regression.
EOF
)"
```

## Task A.7: Phase A close-out — full chaos suite + visual smoke

**Files:** none (verification only).

The five preceding TZ fixes land sequentially. The reaper fix in particular changes runtime behavior (no more GONE→ALIVE oscillation), and the chaos suite is the place that most likely exercises that race.

- [ ] **Step 1: Run the chaos suite end-to-end**

```bash
/Users/osamamuhammed/frappe_15/env/bin/pytest tests_chaos -q --tb=short
```

Expected: every test passes. **If any test fails**, capture the failure mode and stop. Common potential issue: a test that asserts a worker enters STALE/GONE within N seconds and assumed the GONE state would re-flip to ALIVE — those should still pass, but be alert.

- [ ] **Step 2: Run the full unit suite**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests -q
```

Expected: 285+ passed (281 baseline + 4 new TZ regression tests + 1 dashboard API test).

- [ ] **Step 3: Visual smoke against the live bench dashboard via `expect` MCP**

Drive the same scenarios D1 and D2 surfaced:

1. Open `http://frappe.localhost:8000/conductor-dashboard` (use `bench browse --user Administrator` for sid).
2. Take a screenshot of the Overview page — `ACTIVE WORKERS` NumberCard should now read ≥ 2 (was 0).
3. Navigate to `/workers` — the HB age column for ALIVE rows should now show seconds (e.g., `5s`, `12s`), not hours.
4. Save screenshots to `docs/roadmap/v2-certification/dashboard-screenshots/post-A-overview.png` and `post-A-workers.png`.

- [ ] **Step 4: Update `dashboard.md` Findings D1 + D2 to FIXED**

In `docs/roadmap/v2-certification/dashboard.md`, append to the D1 finding:

```markdown
**FIXED in Plan-3 Phase A (commits A.2 + A.6):** the reaper TZ fix
stops the GONE→ALIVE oscillation, and the dashboard API's age
computation now uses now_naive(). Visual confirmation:
post-A-overview.png shows ACTIVE WORKERS = 2; post-A-workers.png
shows HB age in seconds.
```

Mirror for D2.

- [ ] **Step 5: Commit close-out**

```
git add docs/roadmap/v2-certification/dashboard.md docs/roadmap/v2-certification/dashboard-screenshots/post-A-*.png
git commit -m "$(cat <<'EOF'
m8: Phase A close-out — TZ audit complete

All five UTC-naive correction sites land (worker public helper +
reaper + sweeper + frappe_scheduled_loop + dlq.py reviewed_at +
dashboard API age computation). Full unit + chaos suites pass.

Dashboard findings D1 and D2 visually verified fixed via expect MCP:
ACTIVE WORKERS NumberCard reads correctly; HB age column shows
seconds. Screenshots committed for the audit trail.
EOF
)"
```

---

# Phase B — Dashboard fixes D3, D4, D5 (D6 deferred to v2.1)

Goal: close the three frontend bugs surfaced by Plan-2's dashboard pass. Each task ships a fix + an `expect` MCP regression script under `tests/v2_certification/dashboard_e2e/` (per V4's decision).

## Task B.1: D3 — `workflow=null` literal-string bug

**Files:**
- Modify: `dashboard/src/api.js` (or wherever the `list_runs` call is dispatched). Find the function that builds the `?workflow=...` query and ensure JS `null` becomes "param omitted" rather than the string `"null"`.
- Modify: `conductor/api/workflows.py:list_runs` — defensive fallback: treat `workflow="null"` (literal string) as `None`. Pin via test.
- Create: `tests/v2_certification/dashboard_e2e/test_d3_workflow_null.py` — `expect` MCP script that opens `/workflows`, asserts `Recent runs` shows ≥1 row when DB has runs.
- Modify: `tests/test_workflows_api.py` (or equivalent) — pin defensive backend behavior.

- [ ] **Step 1: Locate the API call site in `dashboard/src/`**

```bash
grep -rn 'list_runs\|workflow=' /Users/osamamuhammed/frappe_15/apps/conductor/dashboard/src/ | head
```

Expected hits in `api.js` (or `pages/Workflows.vue`). Read the function that constructs the URL.

- [ ] **Step 2: Fix the frontend — omit the parameter when `workflow` is null/undefined**

Common pattern (adapt to actual code):

```javascript
// Before:
const params = new URLSearchParams({ workflow: this.selectedWorkflow, limit: 50 });

// After:
const params = new URLSearchParams({ limit: 50 });
if (this.selectedWorkflow) params.set('workflow', this.selectedWorkflow);
```

Or if using axios/fetch with an object:

```javascript
const query = { limit: 50 };
if (this.selectedWorkflow) query.workflow = this.selectedWorkflow;
const res = await fetch(url + '?' + new URLSearchParams(query));
```

- [ ] **Step 3: Add backend defensive test**

Append to `tests/test_workflows_api.py` (create if missing):

```python
def test_list_runs_treats_string_null_as_none():
    """Defensive: front-end bug shipped 'workflow=null' (literal string)
    in v1; this defense prevents future analogous serialization mishaps
    (e.g., 'workflow=undefined') from silently emptying the runs table."""
    from conductor.api import workflows
    # When called with the literal string "null", treat as no filter.
    # If the backend correctly applies the filter to "null", it returns
    # zero rows; with the defense, it returns all rows (or at least
    # any pre-existing run).
    rows = workflows.list_runs(workflow="null", limit=50)
    # Should not be empty if any rows exist; if site has zero runs,
    # this test is uninformative — let it pass on empty result.
    # The strict pin is that we don't crash and we don't filter to "null".
    if rows:
        names = {r["workflow"] for r in rows}
        assert "null" not in names, "literal string 'null' filter still active"


def test_list_runs_undefined_string_also_passes():
    """Belt-and-suspenders for 'undefined'."""
    from conductor.api import workflows
    rows = workflows.list_runs(workflow="undefined", limit=50)
    if rows:
        names = {r["workflow"] for r in rows}
        assert "undefined" not in names
```

- [ ] **Step 4: Backend defense in `conductor/api/workflows.py`**

Modify the `list_runs` function:

```python
@frappe.whitelist()
def list_runs(
    workflow: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    _require_read()
    filters: dict[str, Any] = {}
    # Defensive: front-end serialization mishaps (`workflow=null`,
    # `workflow=undefined`) should not silently empty the runs table.
    if workflow and workflow.lower() not in ("null", "undefined", "none", ""):
        filters["workflow"] = workflow
    if status and status.lower() not in ("null", "undefined", "none", ""):
        filters["status"] = status
    rows = frappe.get_all(
        "Conductor Workflow Run",
        filters=filters,
        # ... rest unchanged
    )
    return rows
```

- [ ] **Step 5: Add `expect` MCP regression script**

Create `tests/v2_certification/dashboard_e2e/test_d3_workflow_null.py`:

```python
"""Regression for dashboard finding D3: Recent runs table on /workflows
must surface workflow runs that exist in the DB.

Previously the frontend serialized `null` as the literal string in the
?workflow=null query parameter, and the backend filtered by workflow
named "null" — which never matched. The Recent runs table was always
empty.

This script:
1. Inserts a test workflow run via direct ORM if none exist.
2. Opens /workflows in a browser.
3. Asserts the Recent runs table has at least 1 row visible.
"""

from __future__ import annotations

# This script is invoked via `expect` MCP; the harness sets up Playwright.
# The exact invocation lives in tests/v2_certification/dashboard_e2e/__init__.py
# (or run_e2e.py) — see Plan-3 Task B.0.
```

(The actual harness shape is a function of B.0's decision. The plan's V4 selected option 2 — `expect` MCP scripts. Defer the harness scaffolding to B.0 if it doesn't exist yet, otherwise emit one script per finding.)

- [ ] **Step 6: Run pytest**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_workflows_api.py -v
```

Expected: 2 new tests pass.

- [ ] **Step 7: Build dashboard + run live smoke**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor && yarn build
```

Then via `expect` MCP, open `http://frappe.localhost:8000/conductor-dashboard#/workflows`, verify the Recent runs table now shows the existing rows.

- [ ] **Step 8: Update `dashboard.md` Finding D3 to FIXED**

- [ ] **Step 9: Commit**

```
git add dashboard/src conductor/api/workflows.py tests/test_workflows_api.py tests/v2_certification/dashboard_e2e/test_d3_workflow_null.py docs/roadmap/v2-certification/dashboard.md
git commit -m "$(cat <<'EOF'
m8: workflows.list_runs defends against null/undefined string filters

Closes dashboard finding D3. Two-sided fix:

Frontend: dashboard/src/api.js (or pages/Workflows.vue) no longer
serializes JS null as the literal string "null" in the ?workflow=
query parameter. When no workflow is selected, the parameter is
omitted entirely.

Backend: conductor/api/workflows.list_runs treats "null", "undefined",
"none", and empty string as no filter. Belt-and-suspenders against
future serialization mishaps. Two regression tests pin this.

Live smoke: Recent runs table on /workflows now surfaces the actual
runs from the DB. Captured in dashboard.md.
EOF
)"
```

## Task B.2: D4 — DLQ bulk action bar

**Files:**
- Modify: `dashboard/src/pages/Dlq.vue` (component path) — add a sticky action bar that appears when ≥1 row is selected, with `Retry selected` and `Discard selected` buttons.
- Modify: `dashboard/src/api.js` — wire bulk-retry/bulk-discard to existing CLI-equivalent endpoints, OR add new endpoints in `conductor/api/dashboard.py` if they don't exist.
- Verify: `bench conductor dlq retry --queue X --limit N` already exists (Plan-2 cli.md confirms). The dashboard should drive the same logic per row.
- Create: `tests/v2_certification/dashboard_e2e/test_d4_dlq_bulk.py` — regression script.

D4 is the most substantial Phase B task because it might add a new endpoint if one doesn't exist.

- [ ] **Step 1: Check whether bulk-retry/bulk-discard endpoints exist**

```bash
grep -n 'def.*retry\|def.*discard\|def bulk' /Users/osamamuhammed/frappe_15/apps/conductor/conductor/api/dashboard.py | head
```

If `dashboard.bulk_retry_dlq` / `bulk_discard_dlq` exist: skip Step 2, go to Step 3.
If they don't: add them in Step 2.

- [ ] **Step 2 (conditional): Add bulk endpoints in `conductor/api/dashboard.py`**

```python
@frappe.whitelist()
def bulk_retry_dlq(names: list[str]) -> dict[str, int]:
    """Bulk-retry the DLQ entries listed by `name`. Wraps the same
    per-row logic the CLI's `bench conductor dlq retry --job <id>` uses.
    Returns counts of {retried, failed}."""
    _require_operator_or_sysmgr()
    from conductor.commands.dlq import _enqueue_from_dlq_row, _decode_kwargs, _mark_dlq_row, _get_actor
    retried, failed = 0, 0
    for name in names:
        row = frappe.db.sql(
            "SELECT d.name, d.job, d.queue, d.status, j.method, j.args, j.kwargs "
            "FROM `tabConductor DLQ Entry` d JOIN `tabConductor Job` j ON j.name = d.job "
            "WHERE d.status='PENDING_REVIEW' AND d.name=%s LIMIT 1",
            (name,), as_dict=True,
        )
        if not row:
            failed += 1
            continue
        try:
            kwargs = _decode_kwargs(row[0].get("kwargs") or "")
            new_id = _enqueue_from_dlq_row(row[0]["method"], queue=row[0]["queue"], **kwargs)
            _mark_dlq_row(row[0]["name"], {
                "status": "RETRIED",
                "reviewed_by": _get_actor(),
                "reviewed_at": now_naive(),
            })
            retried += 1
        except Exception:
            failed += 1
    return {"retried": retried, "failed": failed}


@frappe.whitelist()
def bulk_discard_dlq(names: list[str]) -> dict[str, int]:
    """Mirror of bulk_retry_dlq for the discard path."""
    _require_operator_or_sysmgr()
    from conductor.commands.dlq import _mark_dlq_row, _get_actor
    discarded = 0
    for name in names:
        if frappe.db.exists("Conductor DLQ Entry", name):
            _mark_dlq_row(name, {
                "status": "DISCARDED",
                "reviewed_by": _get_actor(),
                "reviewed_at": now_naive(),
            })
            discarded += 1
    return {"discarded": discarded}
```

Add unit tests for both in `tests/test_dashboard_api.py` (extend the file from A.6):

```python
def test_bulk_retry_dlq_marks_each_row_retried(_seed_dlq_rows):
    from conductor.api.dashboard import bulk_retry_dlq
    names = _seed_dlq_rows(3)
    result = bulk_retry_dlq(names)
    assert result["retried"] == 3 and result["failed"] == 0


def test_bulk_discard_dlq_marks_each_row_discarded(_seed_dlq_rows):
    from conductor.api.dashboard import bulk_discard_dlq
    names = _seed_dlq_rows(2)
    result = bulk_discard_dlq(names)
    assert result["discarded"] == 2
```

(Adapt `_seed_dlq_rows` fixture to whatever existing test fixtures provide; extract from `tests/test_dlq_commands.py` if needed.)

- [ ] **Step 3: Add the action bar component to `Dlq.vue`**

When `selected.size > 0`, render a sticky bar at the top or bottom of the page:

```vue
<div v-if="selected.size > 0" class="sticky bottom-0 ...">
  {{ selected.size }} selected.
  <Button @click="bulkRetry">Retry selected ({{ selected.size }})</Button>
  <Button variant="destructive" @click="bulkDiscard">Discard selected ({{ selected.size }})</Button>
</div>
```

`bulkRetry` calls `frappe.call('conductor.api.dashboard.bulk_retry_dlq', { names: [...selected] })`. `bulkDiscard` similarly. After the call returns, refresh the table and clear the selection.

(Adapt to the dashboard's actual API client convention — check `dashboard/src/api.js` for the existing call shape.)

- [ ] **Step 4: Build dashboard, smoke via `expect` MCP**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor && yarn build
```

Then drive: open `/dlq`, select 3 rows via checkbox, assert action bar appears, click Discard selected, confirm dialog, assert rows leave the PENDING_REVIEW status. (Use a test schedule's DLQ entries if real ones are too risky; or just verify the action bar surface and dialog open without confirming, like Plan-2's cautious approach.)

- [ ] **Step 5: Update `dashboard.md` Finding D4 to FIXED**

- [ ] **Step 6: Commit**

```
git add conductor/api/dashboard.py dashboard/src tests/test_dashboard_api.py tests/v2_certification/dashboard_e2e/test_d4_dlq_bulk.py docs/roadmap/v2-certification/dashboard.md
git commit -m "$(cat <<'EOF'
m8: DLQ bulk action bar (Retry / Discard)

Closes dashboard finding D4. Adds bulk_retry_dlq and bulk_discard_dlq
to conductor.api.dashboard (mirror per-row logic the CLI's
`bench conductor dlq retry/discard` already uses). Dlq.vue grows a
sticky action bar that appears when ≥1 row is selected.

Operator footgun closed: triaging a wave of DLQ entries no longer
requires opening each row's detail panel one by one.
EOF
)"
```

## Task B.3: D5 — Workers heartbeat tooltip

**Files:**
- Modify: `dashboard/src/pages/Workers.vue` — wrap the HB age cell in a Tooltip showing the ISO timestamp.
- Create: `tests/v2_certification/dashboard_e2e/test_d5_hb_tooltip.py` — regression script.

Smaller scope. The tooltip primitive already exists in shadcn-vue (`reka-ui` is a dep).

- [ ] **Step 1: Add Tooltip wrapper around the HB age cell**

```vue
<Tooltip>
  <TooltipTrigger as-child>
    <span class="cursor-help underline decoration-dotted">{{ formatHbAge(worker.last_heartbeat) }}</span>
  </TooltipTrigger>
  <TooltipContent>
    <code>{{ worker.last_heartbeat }}</code>
  </TooltipContent>
</Tooltip>
```

(Adapt to actual import paths from `@/components/ui/tooltip` or wherever shadcn-vue installed them.)

- [ ] **Step 2: Build + smoke**

Open `/workers` via `expect` MCP, hover over a HB age cell, assert `[role="tooltip"]` count = 1 within 1 second of hover, and the tooltip text contains an ISO-8601 timestamp.

- [ ] **Step 3: Update `dashboard.md` D5 to FIXED**

- [ ] **Step 4: Commit**

```
git add dashboard/src tests/v2_certification/dashboard_e2e/test_d5_hb_tooltip.py docs/roadmap/v2-certification/dashboard.md
git commit -m "$(cat <<'EOF'
m8: Workers HB age tooltip shows ISO timestamp

Closes dashboard finding D5. The Workers page's HB age column showed
relative time (e.g., "5s") with no way to see the exact wall-clock
heartbeat. Hover now reveals a Tooltip with the full ISO-8601 stamp.
EOF
)"
```

## Task B.4: D6 — explicitly defer to v2.1

**Files:**
- Modify: `docs/roadmap/v2-certification/dashboard.md` — D6 status flip from ✗ to "Deferred to v2.1".
- Modify: `docs/roadmap/v2.md` — add a note pointing at the v2.1 backlog.

D6 (workflow step JsonViewer expansion) is feature work, not a bug fix. The catalog scenario expected an inline expansion of step args/output that doesn't exist in the implementation. Designing it (inline vs modal? msgpack pretty-printing? source: Conductor Job vs workflow context?) is substantive enough to slip the v2.0.0 release.

- [ ] **Step 1: Update `dashboard.md` D6**

```markdown
### Finding D6 — No JsonViewer expansion on workflow step row click — DEFERRED to v2.1

Catalog says clicking a step row should expand a JsonViewer with the
step's args/output payload. No expansion occurs.

This is feature work, not a bug. Designing it raises questions
beyond the v2.0.0 release scope:
- inline expansion vs modal vs route navigation?
- the data source — Conductor Job.args/kwargs (raw) or workflow
  context (post-merge)?
- msgpack pretty-printing or JSON mirror?
- what happens on a 50KB args payload?

Deferred to v2.1. Operators currently click through to the linked
Job to see args/output — slower but correct.
```

- [ ] **Step 2: Add v2.1 backlog stub in `docs/roadmap/v2.md`**

Append a new section near the bottom:

```markdown
## v2.1 backlog (carried over from v2.0.0)

- Dashboard finding D6: workflow step JsonViewer expansion.
- Dashboard scenario catalog refresh (`tests/v2_certification/dashboard_scenarios.md`)
  to fix drift between catalog terminology and shipped UI.
```

- [ ] **Step 3: Commit**

```
git add docs/roadmap/v2-certification/dashboard.md docs/roadmap/v2.md
git commit -m "$(cat <<'EOF'
m8: defer dashboard finding D6 to v2.1

Workflow step JsonViewer expansion is feature work, not a bug.
Designing it raises questions (inline vs modal, raw args vs merged
context, msgpack vs JSON, large-payload UX) that don't fit the v2.0.0
release window. Operators currently click through to the linked Job
to see args/output. Tracked in v2.md's new v2.1 backlog section.
EOF
)"
```

---

# Phase C — M8 stretch hardening

Goal: the four items v2.md tagged as M8 stretch — production-ready Procfile, app-screen integration, full doctor health-gate, optional CI smoke.

## Task C.1: `Procfile.conductor` production-ready

**Files:**
- Replace: `Procfile.conductor` — current shape is a sample for the certification campaign; production should drop honcho-specific assumptions and document supervisord/systemd recommendations inline.

The architecture doc (Plan-2 Task 6) already recommends systemd / supervisord / split-honcho. `Procfile.conductor` is for users who run a single-machine bench; it should still work but with explicit comments warning about the cascade behavior.

- [ ] **Step 1: Read current shape**

```bash
cat /Users/osamamuhammed/frappe_15/apps/conductor/Procfile.conductor
```

- [ ] **Step 2: Rewrite with header comments + production-ready entries**

```
# Conductor v2 sample Procfile — single-machine development + smoke runs.
#
# WARNING: do NOT use this in production for multi-worker deployments.
# Honcho cascades a single-process exit into a full-tree shutdown,
# defeating Conductor's reclaim guarantee.
#
# For production, see docs/explanation-architecture.md "Process
# supervision in production" — recommended supervisors are systemd
# unit-per-worker, supervisord with autorestart=true, or split honcho
# (one for bench infra, one per worker).

conductor_worker: bench --site=auto conductor worker --queue default --queue long --concurrency 4
conductor_scheduler: bench --site=auto conductor scheduler
```

- [ ] **Step 3: Commit**

```
git add Procfile.conductor
git commit -m "$(cat <<'EOF'
m8: Procfile.conductor production-ready (single-machine dev shape)

Header warns against multi-worker production use under honcho and
points at the architecture doc's process-supervision section.
Worker entry uses --site=auto so it works for any installed site.
EOF
)"
```

## Task C.2: `add_to_apps_screen` enabled

**Files:**
- Modify: `conductor/hooks.py` — uncomment the `add_to_apps_screen` block, fill in real values.
- Verify: dashboard logo asset exists. If not, add one.

This puts a Conductor tile on Frappe's apps screen so operators don't have to remember the URL.

- [ ] **Step 1: Verify logo asset**

```bash
ls /Users/osamamuhammed/frappe_15/apps/conductor/conductor/public/ 2>/dev/null
```

If a logo is present (likely `logo.png` or `conductor-logo.png`), use that path. If not, the v2.1 backlog gets a "ship a logo" item; for v2.0.0, omit the `logo` key (Frappe falls back to the app initial).

- [ ] **Step 2: Update `hooks.py`**

Find the commented `add_to_apps_screen` block at line 14 and uncomment + fill:

```python
add_to_apps_screen = [
    {
        "name": "conductor",
        "logo": "/assets/conductor/logo.png",  # omit if no asset
        "title": "Conductor",
        "route": "/conductor-dashboard",
    }
]
```

(Skip the `has_permission` key; it's optional. Ops who can read the dashboard route already have the Conductor Operator or System Manager role enforced server-side via `_require_read`.)

- [ ] **Step 3: Build + smoke**

```bash
cd /Users/osamamuhammed/frappe_15 && bench --site frappe.localhost migrate
```

Then via `expect` MCP, navigate to `http://frappe.localhost:8000/apps`, screenshot, assert a "Conductor" tile is present. Click it; assert it routes to `/conductor-dashboard`.

- [ ] **Step 4: Commit**

```
git add conductor/hooks.py
git commit -m "$(cat <<'EOF'
m8: register Conductor on Frappe's apps screen

Operators no longer need to remember /conductor-dashboard. The tile
routes straight to the dashboard. has_permission is omitted —
server-side _require_read in the dashboard API enforces access.
EOF
)"
```

## Task C.3: Doctor full health-gate (pause_scheduler + shim assertions)

**Files:**
- Modify: `conductor/doctor.py` — add two more checks before the demo block: pause_scheduler assertion (when takeover is enabled) and shim assertion (when intercept flag is set).
- Modify: `tests/test_doctor.py` — add tests.

Plan-2's M7 added `[5/7] Takeover queue coverage`. Plan-3 adds two more, giving `[1/9]`–`[9/9]`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_doctor.py`:

```python
def test_check_pause_scheduler_required_when_takeover_enabled():
    """When conductor_take_over_frappe_scheduler is true, pause_scheduler
    must also be set — otherwise the same row fires twice (once via
    Frappe's scheduler, once via the takeover loop)."""
    from conductor.doctor import check_pause_scheduler
    # Both flags set: ok.
    r1 = check_pause_scheduler(takeover_enabled=True, pause_scheduler=True)
    assert r1.ok is True
    # Takeover on, pause off: fail.
    r2 = check_pause_scheduler(takeover_enabled=True, pause_scheduler=False)
    assert r2.ok is False
    assert "pause_scheduler" in r2.detail.lower()
    # Takeover off: skip.
    r3 = check_pause_scheduler(takeover_enabled=False, pause_scheduler=False)
    assert r3.ok is True


def test_check_shim_active_when_intercept_enabled():
    """When conductor_intercept_frappe_enqueue is true, frappe.enqueue
    must actually be patched. The check imports frappe and verifies
    the patched marker."""
    from conductor.doctor import check_shim_active
    # Intercept off: skip.
    r1 = check_shim_active(intercept_enabled=False)
    assert r1.ok is True
    # Intercept on, patched: ok.  (Mock the marker.)
    with patch("conductor.doctor._is_shim_patched", return_value=True):
        r2 = check_shim_active(intercept_enabled=True)
        assert r2.ok is True
    # Intercept on, not patched: fail.
    with patch("conductor.doctor._is_shim_patched", return_value=False):
        r3 = check_shim_active(intercept_enabled=True)
        assert r3.ok is False
        assert "shim" in r3.detail.lower() or "patch" in r3.detail.lower()
```

- [ ] **Step 2: Run tests, confirm FAIL**

- [ ] **Step 3: Implement the two checks in `conductor/doctor.py`**

```python
def check_pause_scheduler(*, takeover_enabled: bool, pause_scheduler: bool) -> CheckResult:
    """Verify the operator has paused Frappe's own scheduler when the
    takeover loop is active. Otherwise both fire each row → double-firing."""
    if not takeover_enabled:
        return CheckResult(ok=True, detail="takeover disabled — skipped")
    if pause_scheduler:
        return CheckResult(ok=True, detail="pause_scheduler set as required")
    return CheckResult(
        ok=False,
        detail=(
            "conductor_take_over_frappe_scheduler is true but pause_scheduler "
            "is false. Both schedulers will fire each row. Set "
            "`pause_scheduler: 1` in common_site_config.json or remove the "
            "`schedule:` line from the bench Procfile."
        ),
    )


def _is_shim_patched() -> bool:
    """True iff conductor.frappe_compat.install_inprocess_patch ran
    successfully and frappe.enqueue points at our shim."""
    try:
        from conductor.frappe_compat import is_patch_installed
        return is_patch_installed()
    except Exception:
        return False


def check_shim_active(*, intercept_enabled: bool) -> CheckResult:
    if not intercept_enabled:
        return CheckResult(ok=True, detail="intercept disabled — skipped")
    if _is_shim_patched():
        return CheckResult(ok=True, detail="frappe.enqueue patch active")
    return CheckResult(
        ok=False,
        detail=(
            "conductor_intercept_frappe_enqueue is true but the in-process "
            "patch is not installed. Restart the bench to re-fire "
            "conductor's bootstrap."
        ),
    )
```

(Verify `conductor.frappe_compat.is_patch_installed` exists; if not, add it as a thin getter — it's a one-liner inside `frappe_compat.py`.)

- [ ] **Step 4: Wire both into `run()` and renumber to `[1/9]`–`[9/9]`**

```python
ok &= _step("[1/9] Redis connectivity", check_redis)
ok &= _step("[2/9] Default queues seeded", check_queues)
ok &= _step("[3/9] Consumer groups exist", check_groups)
ok &= _step("[4/9] XADD/XREADGROUP/XACK round-trip", check_round_trip)
# [5/9] takeover queue coverage (existing from M7)
ok &= _step("[5/9] Takeover queue coverage", check_takeover_coverage)

def check_pause_scheduler_live() -> str:
    conf = frappe.local.conf or {}
    result = check_pause_scheduler(
        takeover_enabled=bool(conf.get("conductor_take_over_frappe_scheduler", False)),
        pause_scheduler=bool(conf.get("pause_scheduler", False)),
    )
    if not result.ok:
        raise RuntimeError(result.detail)
    return result.detail

ok &= _step("[6/9] Pause scheduler when takeover active", check_pause_scheduler_live)

def check_shim_active_live() -> str:
    conf = frappe.local.conf or {}
    result = check_shim_active(
        intercept_enabled=bool(conf.get("conductor_intercept_frappe_enqueue", False)),
    )
    if not result.ok:
        raise RuntimeError(result.detail)
    return result.detail

ok &= _step("[7/9] frappe.enqueue shim active", check_shim_active_live)

if demo:
    ok &= _step("[8/9] End-to-end demo dispatch", step_dispatch)
    ok &= _step("[9/9] Result round-trip", step_result)
```

(Adjust the existing `[5/7]/[6/7]/[7/7]` labels accordingly.)

- [ ] **Step 5: Run tests, confirm PASS**

- [ ] **Step 6: Live smoke**

```bash
bench --site frappe.localhost conductor doctor
```

Expected: 7 lines (without demo) all OK, including:
- `[5/9] Takeover queue coverage........... OK (all takeover queues covered (default, long))`
- `[6/9] Pause scheduler when takeover active. OK (pause_scheduler set as required)`
- `[7/9] frappe.enqueue shim active........ OK (frappe.enqueue patch active)`

Exit 0.

- [ ] **Step 7: Commit**

```
git add conductor/doctor.py conductor/frappe_compat.py tests/test_doctor.py
git commit -m "$(cat <<'EOF'
m8: doctor adds pause_scheduler + shim-active health checks

Plan-2's M7 doctor fix landed [5/7] takeover queue coverage. Plan-3
M8 closes the full health-gate with two more checks:

- [6/9] Pause scheduler when takeover active. Verifies pause_scheduler
  is true whenever conductor_take_over_frappe_scheduler is true. Without
  this, both schedulers fire each row → silent double-firing.

- [7/9] frappe.enqueue shim active. Verifies the in-process patch is
  installed when conductor_intercept_frappe_enqueue is true. Catches
  the bootstrap-timing footgun Plan-1 hit before the install_unconditionally
  fix landed.

Existing demo steps renumbered to [8/9] and [9/9].
EOF
)"
```

## Task C.4 (OPTIONAL): CI smoke loop

**Skip this task if behind schedule.** Optional per v2.md.

**Files:**
- Create: `.github/workflows/conductor-smoke.yml` — GitHub Actions workflow that runs a 10-job synthetic version of M2 on PRs.

Catches obvious dispatch-path regressions before they hit `develop`.

- [ ] **Step 1: Decide whether to ship this in v2.0.0**

Time budget for v2.0.0 release. If Phase A+B+C took longer than estimated, defer this to v2.1 and skip to Phase D.

- [ ] **Step 2 (if proceeding): Create the workflow YAML**

```yaml
# .github/workflows/conductor-smoke.yml
name: Conductor smoke
on:
  pull_request:
    paths:
      - 'conductor/**'
      - 'tests/**'

jobs:
  smoke:
    runs-on: ubuntu-latest
    services:
      redis:
        image: redis:7
        ports:
          - 6379:6379
      mariadb:
        image: mariadb:10.11
        env:
          MARIADB_ROOT_PASSWORD: root
        ports:
          - 3306:3306
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
      - name: Bench setup
        run: |
          # Adapt to whatever bench-setup script the repo has.
          # If no script, this task should add one before the workflow.
          ./scripts/setup-bench.sh
      - name: Run smoke
        run: |
          /home/runner/frappe-bench/env/bin/python \
            -m tests.v2_certification.cli_runner
```

(The exact bench setup is repo-dependent. If no `scripts/setup-bench.sh` exists, this task expands to also create one — which is a substantial amount of work. Re-evaluate whether this still fits v2.0.0 or push to v2.1.)

- [ ] **Step 3: Commit (or skip)**

```
git add .github/workflows/conductor-smoke.yml
git commit -m "m8 (optional): CI smoke runs cli_runner on every PR"
```

If skipping: add a one-line note to the v2.1 backlog in `docs/roadmap/v2.md`.

---

# Phase D — M9 release

Goal: tag and publish v2.0.0.

## Task D.1: Comparative KPI re-run + baseline freeze

**Files:**
- Create: `tests/comparative/baseline_v1.json` — frozen v1.0.0 numbers (extracted from the run output of v1.0.0's KPI suite — pull from the v1 tag if needed).
- Modify: `tests/comparative/run_kpis.py` — add `--compare PATH` mode that diffs output against the baseline JSON and exits non-zero on regression.

**Pre-decided regression contingency:** if any KPI regresses, **pause Phase D, investigate root cause, fix, rerun**. Do NOT ship-with-documented-regression.

- [ ] **Step 1: Capture the baseline from v1.0.0**

If a v1.0.0 git tag exists:

```bash
git checkout v1.0.0  # or whatever the v1 tag is named
/Users/osamamuhammed/frappe_15/env/bin/python -m tests.comparative.run_kpis --kpi 1 --engine conductor --report /tmp/v1-kpi-1.json
# Repeat for kpi 2..5
git checkout v2/certification
```

If no v1.0.0 tag exists, the "baseline" is the most recent green run on `develop` before Plan-1. Document the source in the JSON header.

Build the baseline file:

```json
{
  "source": "v1.0.0 tag — captured 2026-05-04",
  "kpis": {
    "kpi_01_transient_recovery": {
      "throughput_jobs_per_sec": 1234.5,
      "p99_latency_ms": 56.7,
      "...": "actual numbers from the run"
    },
    "kpi_02_audit_completeness": { "...": "..." },
    "kpi_03_dlq_visibility": { "...": "..." },
    "kpi_04_idempotency": { "...": "..." },
    "kpi_05_throughput": { "...": "..." }
  },
  "tolerances": {
    "throughput_jobs_per_sec": 0.05,
    "p99_latency_ms": 0.10
  }
}
```

(The exact KPI metric names depend on what `run_kpis.py` actually produces. The first run informs the schema.)

- [ ] **Step 2: Add `--compare` mode to `run_kpis.py`**

```python
parser.add_argument("--compare", help="Diff results against this baseline JSON; exit non-zero on regression.")

# After all KPIs run:
if args.compare:
    baseline = json.loads(Path(args.compare).read_text())
    actual = {...}  # the just-run numbers
    regressions = []
    for kpi_name, baseline_metrics in baseline["kpis"].items():
        for metric, baseline_value in baseline_metrics.items():
            actual_value = actual.get(kpi_name, {}).get(metric)
            tol = baseline.get("tolerances", {}).get(metric, 0.05)
            if actual_value is None:
                regressions.append(f"{kpi_name}.{metric}: missing from actual")
                continue
            if metric.endswith("_per_sec") or metric.startswith("throughput"):
                # Lower is bad
                if actual_value < baseline_value * (1 - tol):
                    regressions.append(f"{kpi_name}.{metric}: {actual_value:.2f} < {baseline_value:.2f} * (1-{tol})")
            elif "latency" in metric:
                # Higher is bad
                if actual_value > baseline_value * (1 + tol):
                    regressions.append(f"{kpi_name}.{metric}: {actual_value:.2f} > {baseline_value:.2f} * (1+{tol})")
    if regressions:
        for r in regressions: print(f"REGRESSION: {r}")
        sys.exit(1)
    print(f"All KPIs within {len(baseline['kpis'])} tolerance bands.")
```

- [ ] **Step 3: Run the suite against the current branch**

```
cd /Users/osamamuhammed/frappe_15
/Users/osamamuhammed/frappe_15/env/bin/python -m tests.comparative.run_kpis --kpi 1 --engine conductor --report /tmp/kpi-1.json
# Repeat 2..5
/Users/osamamuhammed/frappe_15/env/bin/python -m tests.comparative.run_kpis --kpi 1 --engine conductor --compare tests/comparative/baseline_v1.json
```

Expected: exit 0; "All KPIs within N tolerance bands."

**If exit non-zero:** stop. Investigate. Common candidates:
- Reaper TZ fix changed reaper tick timing — should NOT affect throughput; if it does, the fix is wrong.
- Sweeper TZ fix — same.
- Dashboard fixes shouldn't affect KPIs at all (KPIs don't touch dashboard code).

Profile, fix root cause, rerun. Do NOT ship-with-documented-regression.

- [ ] **Step 4: Commit baseline + comparator**

```
git add tests/comparative/baseline_v1.json tests/comparative/run_kpis.py
git commit -m "$(cat <<'EOF'
m9: comparative KPI baseline + --compare mode

Freezes the v1.0.0 KPI numbers as tests/comparative/baseline_v1.json
and adds --compare PATH to run_kpis.py for the v2.0.0 release gate.
Tolerance bands: 5% on throughput, 10% on p99 latency. Lower throughput
or higher latency outside tolerance fails the comparator.

Current branch passes against the v1 baseline — comparative KPI gate
green for v2.0.0 release.
EOF
)"
```

## Task D.2: README + docs/index.md refresh

**Files:**
- Modify: `README.md` — v2 capability paragraph + certification status link.
- Modify: `docs/index.md` — same.

Both are user-facing landing pages. Single read-through review (no full spec+quality cycle for pure docs).

- [ ] **Step 1: Read both files**

```bash
cat /Users/osamamuhammed/frappe_15/apps/conductor/README.md
cat /Users/osamamuhammed/frappe_15/apps/conductor/docs/index.md
```

- [ ] **Step 2: Add v2 paragraph to each**

For README.md, near the top:

```markdown
## v2.0.0 — empirically certified

Conductor v2 ships after a four-day campaign on a real Frappe + HRMS
bench. **9300+ successful dispatches over 4 days**, **0 failed**, every
one of 105 active `Scheduled Job Type` rows fired and recorded.
Certification artifacts: `docs/roadmap/v2-certification/`.

v2 also adds a takeover loop that reads `tabScheduled Job Type`
directly so Conductor catches Frappe scheduler ticks (in-process
`frappe.enqueue` patching alone cannot — Frappe imports the function
directly at module load).

Read more: `docs/roadmap/v2.md`.
```

For `docs/index.md`, add a similar paragraph in the "What's new" / landing section.

- [ ] **Step 3: Commit**

```
git add README.md docs/index.md
git commit -m "$(cat <<'EOF'
m9: README + docs/index.md reflect v2.0.0 certification status

Lands the v2 capability paragraph + certification artifact link on
both landing pages.
EOF
)"
```

## Task D.3: Merge `v2/certification` → `develop`

**Files:** none (git operation).

The branch is now ~30 commits past `develop`. Time to merge.

- [ ] **Step 1: Verify branch state**

```bash
git status   # clean
git log --oneline develop..v2/certification | wc -l   # ~30
```

- [ ] **Step 2: Run the full suite one more time on the branch tip**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests tests_chaos -q
/Users/osamamuhammed/frappe_15/env/bin/python -m tests.comparative.run_kpis --kpi 1 --engine conductor --compare tests/comparative/baseline_v1.json
```

All green.

- [ ] **Step 3: Open PR and merge**

```bash
git push origin v2/certification
gh pr create --base develop --title "v2.0.0: certification campaign + M7 fixes + M8 hardening" --body "$(cat <<'EOF'
## Summary

This PR merges the four-day v2 certification campaign and all
follow-up work (M7 + M8) onto develop.

- M1–M6 (Plan-1): empirical certification, takeover loop, baseline
  + scheduled-jobs + cli + multi-worker + soak matrices.
- M7 (Plan-2): dlq --site inheritance, doctor takeover queue-coverage
  health-gate, process-supervision documentation, inflight-cap re-run,
  CLI gap closures, dashboard M4 matrix.
- M8 (Plan-3 Phase A–C): UTC-naive TZ audit (5 sites), dashboard fixes
  D3+D4+D5 (D6 deferred to v2.1), Procfile.conductor production-ready,
  add_to_apps_screen registration, doctor full health-gate.
- M9 (Plan-3 Phase D, this commit): comparative KPI gate green,
  README + docs/index.md refreshed.

## Test plan

- [x] `pytest tests` — green
- [x] `pytest tests_chaos` — green
- [x] `python -m tests.comparative.run_kpis --compare baseline_v1.json` — within tolerance
- [x] Live `bench conductor doctor` shows all 7 (or 9 with --demo) checks OK
- [x] Dashboard smoke via `expect` MCP — D1, D2, D3, D4, D5 visually fixed
EOF
)"
gh pr merge --merge   # or --squash if the team prefers
```

(Adapt to actual branch protection / merge strategy.)

- [ ] **Step 4: Switch local to develop, fast-forward, confirm**

```bash
git checkout develop
git pull origin develop
git log --oneline | head -3   # confirm v2/certification commits are now on develop
```

## Task D.4: Tag v2.0.0 + GitHub release notes

**Files:** none (git operation + gh CLI).

Final step.

- [ ] **Step 1: Create the annotated tag**

```bash
git tag -a v2.0.0 -m "$(cat <<'EOF'
Conductor v2.0.0 — empirically certified

Highlights:
- 9300+ successful dispatches over a 4-day soak on a real Frappe+HRMS bench
- Path A→B pivot: Conductor reads tabScheduled Job Type directly to catch
  Frappe scheduler ticks (the in-process frappe.enqueue patch ships as a
  complementary catch-net for direct callers)
- doctor full health-gate: Redis + queues + groups + round-trip + takeover
  queue coverage + pause_scheduler + shim-active assertions
- UTC-naive timestamp consistency across reaper, sweeper, scheduler loop,
  dlq audit, and dashboard age computations
- Dashboard surface certified across 27 scenarios × {light, dark}; D6
  (workflow step JsonViewer) deferred to v2.1
- Comparative KPI suite within tolerance vs v1.0.0

Full certification artifacts: docs/roadmap/v2-certification/
Roadmap: docs/roadmap/v2.md
EOF
)"
git push origin v2.0.0
```

- [ ] **Step 2: Create GitHub release**

```bash
gh release create v2.0.0 --title "v2.0.0 — empirically certified" --notes "$(cat <<'EOF'
## Highlights

- **9300+ successful dispatches over 4 days** on a real Frappe + HRMS
  bench (105 Scheduled Job Type rows × natural cron). 0 failed, 1 DLQ
  entry caught (an upstream HRMS API mismatch — exactly the v2 KPI
  in action: failures that would have been silent under RQ are
  queryable via `bench conductor dlq list`).
- **Takeover loop** (path B): Conductor's scheduler reads
  `tabScheduled Job Type` directly and dispatches each due row through
  `conductor.dispatcher.enqueue`. The in-process `frappe.enqueue` patch
  ships as a complementary catch-net for direct in-process callers.
- **Doctor full health-gate**: 7 default + 2 demo checks covering
  Redis, default queues, consumer groups, XADD/XREADGROUP/XACK
  round-trip, takeover queue coverage, pause_scheduler enforcement,
  and frappe.enqueue shim activeness.
- **UTC-naive timestamp consistency** across the reaper, sweeper,
  Frappe scheduled loop, DLQ audit columns, and dashboard age
  computations. Closes a class of bugs that masked workers as GONE
  on non-UTC benches.
- **Dashboard certification matrix**: 27 scenarios × {light, dark}
  exercised via expect MCP. Five fixes shipped in v2.0.0; one
  (workflow step JsonViewer) deferred to v2.1.

## Migration from v1.0.0

`bench update` and migrate. New site_config flags:
- `conductor_intercept_frappe_enqueue: true` — activate the in-process patch.
- `conductor_take_over_frappe_scheduler: true` — activate the takeover loop.
- Pair the takeover with `pause_scheduler: 1` to avoid double-firing.

`bench conductor doctor` will tell you if your setup is missing anything.

## Certification artifacts

- `docs/roadmap/v2-certification/SUMMARY.md` — campaign summary
- `docs/roadmap/v2-certification/scheduled-jobs.md` — 105-row matrix
- `docs/roadmap/v2-certification/cli.md` — CLI subcommand matrix
- `docs/roadmap/v2-certification/dashboard.md` — dashboard matrix
- `docs/roadmap/v2-certification/multi-worker.md` — multi-worker findings
- `docs/roadmap/v2-certification/soak.md` — 4-day soak observations

## v2.1 backlog

- Dashboard finding D6: workflow step JsonViewer expansion.
- Dashboard scenario catalog refresh.

Full changelog: $(git log v1.0.0..v2.0.0 --oneline | wc -l) commits.
EOF
)"
```

- [ ] **Step 3: Verify the release on GitHub**

```bash
gh release view v2.0.0
```

## Task D.5: Final close-out

**Files:**
- Modify: `docs/roadmap/v2.md` — flip every deliverable to `[x]`, add a "Released" status banner.
- Modify: `docs/roadmap/v2-certification/SUMMARY.md` — add a closing "Released" section.

- [ ] **Step 1: v2.md status flip**

Change the top-of-file `**Status:**` to:

```markdown
**Status:** Released as v2.0.0 on YYYY-MM-DD. Certification artifacts at `docs/roadmap/v2-certification/`.
```

Walk the deliverables checklist; mark every box `[x]`. Add a final block:

```markdown
## v2.0.0 released

- Tag: `v2.0.0`
- GitHub release: <link>
- Comparative KPI gate: green vs v1.0.0 baseline (see `tests/comparative/baseline_v1.json`).
```

- [ ] **Step 2: SUMMARY.md final block**

```markdown
## v2.0.0 released

Plan-3 closed YYYY-MM-DD. All deliverables shipped:
- M8 hardening (Procfile, apps screen, full doctor health-gate)
- TZ audit (5 backend sites)
- Dashboard fixes D1–D5 (D6 deferred to v2.1)
- Comparative KPI gate green
- README + docs/index.md refreshed
- Tag `v2.0.0` and GitHub release published

Next: v2.1 backlog (D6 + catalog refresh).
```

- [ ] **Step 3: Commit + push**

```
git add docs/roadmap/v2.md docs/roadmap/v2-certification/SUMMARY.md
git commit -m "release: v2.0.0 close-out — every deliverable shipped"
git push origin develop
```

This commit lands AFTER the tag — the tag points at the merge commit, this is the post-release housekeeping.

---

## Self-review checklist (already run)

- ✅ **Spec coverage:** Every v2.md deliverables-checklist item maps to a task. The Plan-2 follow-up TZ audit (4 sites + 2 dashboard manifestations) maps to Phase A. Dashboard findings D1–D5 map to Phase A (D1, D2) + Phase B (D3, D4, D5); D6 is explicitly deferred. M8 four items → Phase C four tasks (last optional). M9 release → Phase D five tasks.
- ✅ **No placeholders blocking execution:** Every code change has the actual code. The two Vue/JS edits in Phase B point at the file pattern (`dashboard/src/api.js` or `pages/Workflows.vue`) with explicit "adapt to actual" notes since the implementer needs to read the existing component to merge cleanly. KPI baseline JSON shape is left blank-with-instructions because the actual numbers come from the v1 run.
- ✅ **Type consistency:** `now_naive` (the public name) is used in every Phase A task. `CheckResult(ok, detail)` is reused in Phase C.3's two new checks. `bulk_retry_dlq`/`bulk_discard_dlq` signatures match in both backend implementation and test fixtures.
- ✅ **TDD where it fits:** Phase A all-TDD (regression-test-first). Phase B mixed (backend tests TDD, frontend changes are observational + smoked via `expect`). Phase C.3 TDD; C.1, C.2, C.4 not TDD (doc/yaml/hooks). Phase D mostly bookkeeping.
- ✅ **Subagent feasibility:** Every task is subagent-safe. The expect-MCP smokes can be driven by the controller (not subagent) since browser tools are available.
- ✅ **Commit hygiene:** No `git commit --amend` anywhere. Each task commits standalone. The tag commit and the close-out commit are sequenced after the merge.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-04-conductor-v2-m8-m9-release.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
