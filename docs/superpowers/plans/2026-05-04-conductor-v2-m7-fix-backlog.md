# Conductor v2 — M7 Fix Backlog Implementation Plan (Plan-2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Task 8 (Dashboard M4) is the lone exception — it must be executed by the human operator inside an `expect` MCP browser session and cannot be subagent-driven.**

**Goal:** Close the M7 fix backlog from the v2 certification campaign (Plan-1 / `docs/roadmap/v2-certification/SUMMARY.md`) so the `v2/certification` branch carries one commit per finding, each with a regression test where the change is code, plus the Dashboard M4 matrix that Plan-1 deferred.

**Architecture:** Two surgical code fixes (CLI inheritance + doctor health-gate), one documentation fix (process-supervision section), one re-run of an interrupted live test, one CLI-coverage extension, and one human-driven dashboard pass. No new modules; every change is bounded to an existing file.

**Tech Stack:** Python 3.10, Frappe v15, Conductor (current `v2/certification` head), pytest under the bench virtualenv (`/Users/osamamuhammed/frappe_15/env/bin/pytest`), Click + `CliRunner`, Redis, `expect` MCP (Playwright) for the dashboard task only.

**Branch:** `v2/certification` (continue; no rebase, no new branch).

**Spec:** `docs/roadmap/v2.md` (M7 row) and `docs/roadmap/v2-certification/SUMMARY.md` (findings backlog 2–5 + 7).

**Plan scope:**

- **In scope:** Findings 2, 3, 4, 5, 7 from `SUMMARY.md`; the two Plan-1 cli.md "deferred to M7" items (`cancel`, `schedule run-now`); writing the Dashboard M4 matrix; SUMMARY.md close-out.
- **Out of scope (Plan-3):** M8 stretch hardening — production-ready `Procfile.conductor`, `add_to_apps_screen` enable, doctor's *full* health-gate (pause_scheduler + shim assertions), optional CI smoke loop, comparative KPI re-run, README/docs landing-page refresh, `v2.0.0` tag.

---

## Decomposition rationale

Each fix is one logical change with its own commit and regression test, so the rollback unit equals the review unit. The doctor health-gate is the largest fix (one new step in `conductor/doctor.py` + worker-queue introspection helper); it sits alone in Task 4. The `dlq` group fix is small but spans three subcommands (`list`, `retry`, `discard`); the consistency argument is strong enough to fix all three at once but only `list` is finding-driven, so the test surface is one commit-worth. The dashboard pass cannot be subagent-driven — it is held to its own task with a clear human-handoff block.

---

## File structure

| File | Status | Responsibility |
|---|---|---|
| `conductor/commands/dlq.py` | Modify | Drop `required=True --site`, switch to `pass_context` + `get_site` like `depth.py`; preserve current explicit-`--site` calling convention |
| `tests/test_dlq_commands.py` | Modify | Add a no-`--site` regression test invoked through `pass_context` |
| `conductor/doctor.py` | Modify | Add `[7/N]` step that runs only when takeover flag is set: warns when worker queue coverage is incomplete |
| `tests/test_doctor.py` | Create | Unit tests for the new takeover queue-coverage check |
| `docs/explanation-architecture.md` | Modify | Append "Process supervision" section (systemd / supervisord / split-honcho recommendations) |
| `tests/v2_certification/cli_runner.py` | Modify | Add `cancel <id>` and `schedule run-now <name>` scenarios with proper preflight (create a row to act on) |
| `docs/roadmap/v2-certification/cli.md` | Modify | Update Finding 1 to "FIXED in commit X"; add new automated rows for `cancel` and `schedule run-now`; update CLI tally |
| `docs/roadmap/v2-certification/multi-worker.md` | Modify | Replace the inflight-cap "DEFERRED" subsection with the re-run results |
| `docs/roadmap/v2-certification/dashboard.md` | Create | M4 matrix: 27 scenarios × `[id, page, control, expected, observed, screenshot, pass]` |
| `docs/roadmap/v2-certification/SUMMARY.md` | Modify | Mark M4 ✅, mark each finding `FIXED in commit Y`, update "What's next" to point at Plan-3 |

---

## Conventions for every task

- **Working directory:** `/Users/osamamuhammed/frappe_15/apps/conductor` for code edits and pytest. `/Users/osamamuhammed/frappe_15` for `bench` commands.
- **Python:** always invoke pytest as `/Users/osamamuhammed/frappe_15/env/bin/pytest`, never bare `pytest`.
- **Bench commands:** always include `--site frappe.localhost`. Run from `/Users/osamamuhammed/frappe_15`.
- **Branch:** stay on `v2/certification`. Do not push to `develop`.
- **Commits:** one logical change per commit. Stage explicit paths (`git add path/...`), never `git add -A`. Use heredoc for the message.
- **Matrix updates:** whenever a fix changes the certification picture, update the matrix file (`cli.md`, `multi-worker.md`, `dashboard.md`, `SUMMARY.md`) in the same commit as the code/doc change.
- **Stop rule:** if any task surfaces behavior that contradicts an earlier task or earlier finding, stop and check in with the user before continuing.
- **Hash cross-references:** when a doc/matrix line wants to point at a commit ("M7 fix landed in commit `<HASH>`"), do NOT amend the original commit to backfill the reference. Leave a `<HASH-N>` placeholder in the doc as you go (one per commit), and fill all of them in Task 10's close-out commit, which is the single bookkeeping commit allowed to read `git log --grep='cert(M7)'`.

---

## Pre-task verification — RESOLVED (controller ran 2026-05-04)

The five lookups have been completed. Use these verified facts when executing the tasks below; do not re-invent.

- **V1: `Conductor Schedule` field names** (relevant for Task 9):
  - PK / unique field: `schedule_name` (Data) — NOT `name` directly.
  - `cron_expression` (Data) — NOT `cron` or `cron_format`.
  - `kwargs` (Long Text) — NOT `kwargs_json`.
  - `args` (Long Text) — NOT `args_json`.
  - Other fields: `enabled` (Check), `timezone` (Data), `method` (Data), `queue` (Link), `max_attempts` (Int), `last_run_at`, `last_status`, `last_job`, `next_run_at`, `description`.
  - **Important:** `schedule_run_now` calls `_decode_kwargs(doc.kwargs) if doc.kwargs else {}` (in `conductor/commands/schedule.py:106-109`). `_decode_kwargs` expects msgpack/base64-encoded data; passing a JSON string will fail. The seed dict in Task 9 should leave `kwargs` and `args` UNSET (so the short-circuit `if doc.kwargs else {}` returns `{}` cleanly).

- **V2: `Conductor Worker.last_heartbeat` is `Datetime`.** The `frappe.get_all(filters={"last_heartbeat": [">=", datetime_obj]})` pattern in Task 5 works as written; no change needed.

- **V3: `bench conductor cancel` argv** (Task 9): positional argument `<job_id>`. Plan's `["conductor", "cancel", job_id]` is correct.

- **V4: `bench conductor schedule run-now` argv** (Task 9): positional argument `<name>`. Plan's `["conductor", "schedule", "run-now", name]` is correct.

- **V5: `frappe.commands.pass_context` and `get_site` contract** (Task 2):
  - `frappe.commands.pass_context` is a wrapper around `click.pass_context`. Before calling the wrapped function, it executes `ctx.obj["profile"]` (line 23 of `frappe/commands/__init__.py`) and then calls `f(frappe._dict(ctx.obj), *args, **kwargs)` (line 29).
  - The wrapped function therefore receives `frappe._dict(ctx.obj)` as its first parameter — NOT a Click `Context`. Convention is to call this parameter `ctx` for symmetry, but it's actually a `_dict`-wrapped copy of the Click context's `obj` dict.
  - `get_site(context)` returns `context.sites[0]` (raises `frappe.SiteNotSpecifiedError` if `sites` is empty/missing).
  - For CliRunner tests: pass `obj={"sites": ["frappe.localhost"], "profile": False}` to `runner.invoke(...)`. Both `profile` and `sites` are required; `frappe._dict(ctx.obj)` would crash if `ctx.obj` is `None`.
  - **Knock-on for Task 3:** the existing dlq tests in `tests/test_dlq_commands.py` invoke `dlq_group` without an `obj=...` argument. Currently they work because `dlq` commands don't use `pass_context`. After the Task 3 refactor adds `@pass_context` to `list_command`, `retry_command`, `discard_command`, **all six existing invocations break** until updated. Task 3 must include adding `obj={"sites": ["frappe.localhost"], "profile": False}` to every `runner.invoke(dlq_group, ...)` call in `tests/test_dlq_commands.py`.

---

## Task 1: Verify the working state before starting

**Files:** none (read-only check).

- [ ] **Step 1: Confirm branch + tree state**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git status
git branch --show-current
git log --oneline -5
```

Expected: clean working tree, current branch is `v2/certification`, top commit is `3c59006 cert: M1-M6 close-out — Plan-1 complete`.

If the tree is dirty, stop and check in with the user.

- [ ] **Step 2: Confirm the existing test suite is green**

Run:

```bash
/Users/osamamuhammed/frappe_15/env/bin/pytest tests -q
```

Expected: 274 passed / 17 skipped (matching the Plan-1 close-out figure in SUMMARY.md). If the count diverges, stop and reconcile before changing code.

- [ ] **Step 3: Confirm the bench is in the same operational state SUMMARY.md describes**

Read `docs/roadmap/v2-certification/SUMMARY.md` "Operational state at session close" section. Verify by hand:

- `frappe.localhost`'s `common_site_config.json` has `conductor_take_over_frappe_scheduler: true` and `conductor_intercept_frappe_enqueue: true`.
- `pause_scheduler: 1` is set bench-wide.
- Bench Procfile has `conductor_worker:` lines on `--queue default --queue long`.

```bash
grep -E 'conductor_take_over|conductor_intercept|pause_scheduler' /Users/osamamuhammed/frappe_15/sites/common_site_config.json
grep -E 'conductor_worker|conductor_scheduler' /Users/osamamuhammed/frappe_15/Procfile
```

Expected: each grep returns its line. If any flag or Procfile line is missing, stop — Plan-1's operational baseline must hold before M7 starts.

- [ ] **Step 4: Confirm bench processes are actually running**

The live smokes in Tasks 5 and 7 depend on a running bench with two `conductor_worker` processes; the docs-only Task 6 does not, but everything else does.

```bash
pgrep -af 'conductor (worker|scheduler)' | head
```

Expected: at least two `bench --site frappe.localhost conductor worker --queue default --queue long ...` lines plus one `bench --site frappe.localhost conductor scheduler` line. If the count is lower, ask the user to start the bench (typically `bench start` from `/Users/osamamuhammed/frappe_15`) before continuing past this task.

---

## Task 2: Fix `dlq list/retry/discard --site` inheritance — write the failing test

**Finding addressed:** Finding 3 in `SUMMARY.md` / Finding 1 in `cli.md`.

**Files:**
- Modify: `tests/test_dlq_commands.py` (add the regression test)

- [ ] **Step 1: Add a regression test that exercises the bench-context inheritance path**

Append the following at the end of `tests/test_dlq_commands.py`. The test invokes `dlq list` *without* `--site` and asserts the bench context's site is used. (Per V5: `frappe.commands.pass_context` calls `f(frappe._dict(ctx.obj), ...)`, so `ctx.obj` must be a dict containing both `"sites"` and `"profile"` — passing `obj=` directly to `CliRunner.invoke` is the right shape.)

```python
def test_dlq_list_inherits_site_from_bench_context():
    """Regression for M7 Finding 3: `bench --site X conductor dlq list` (no
    explicit `--site` after the subcommand) must succeed by inheriting the
    site from the bench Click context, mirroring `conductor depth`'s
    behavior. See docs/roadmap/v2-certification/cli.md Finding 1."""
    from conductor.commands.dlq import dlq_group
    runner = CliRunner()
    captured = {}

    def fake_connect(site):
        captured["site"] = site

    with patch("conductor.commands.dlq._fetch_dlq_rows", return_value=_fake_dlq_rows()), \
         patch("conductor.commands.dlq._connect_to_site", side_effect=fake_connect), \
         patch("conductor.commands.dlq._disconnect"):
        # No --site after the subcommand. The bench context provides it
        # via frappe.commands.pass_context, which reads ctx.obj["sites"][0].
        result = runner.invoke(
            dlq_group,
            ["list"],
            obj={"sites": ["frappe.localhost"], "profile": False},
        )
    assert result.exit_code == 0, result.output
    assert captured.get("site") == "frappe.localhost"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_dlq_commands.py::test_dlq_list_inherits_site_from_bench_context -v
```

Expected: FAIL. The current `list_command` declares `--site` as `required=True`, so `runner.invoke(dlq_group, ["list"])` exits with code `2` and "Missing option '--site'".

If the failure mode is different (e.g., it passes), stop — the existing CLI may have already been refactored, in which case this task is moot.

---

## Task 3: Fix `dlq list/retry/discard --site` inheritance — implementation + commit

**Files:**
- Modify: `conductor/commands/dlq.py`
- Modify: `docs/roadmap/v2-certification/cli.md`

- [ ] **Step 1: Refactor `list_command`, `retry_command`, `discard_command` to use `pass_context`**

Replace the three subcommands' decorators and signatures in `conductor/commands/dlq.py`. Add the `pass_context` import at the top.

Top-of-file imports (new lines marked):

```python
from __future__ import annotations

import base64
from datetime import datetime

import click
import frappe
from frappe.commands import get_site, pass_context  # NEW

from conductor.serialization import loads as msgpack_loads
```

Replace the `list_command` block:

```python
@dlq_group.command("list")
@click.option("--site", default=None,
              help="Frappe site name. Defaults to the bench --site context.")
@click.option("--queue", default=None, help="Filter to one queue.")
@click.option("--status", "status",
              type=click.Choice(["PENDING_REVIEW", "RETRIED", "DISCARDED"]),
              default=None, help="Filter by review status.")
@click.option("--limit", default=50, type=int, help="Max rows to print.")
@pass_context
def list_command(ctx, site, queue, status, limit):
    """List DLQ entries, newest first."""
    site = site or get_site(ctx)
    filters: dict = {}
    if queue:
        filters["queue"] = queue
    if status:
        filters["status"] = status
    _connect_to_site(site)
    try:
        rows = _fetch_dlq_rows(filters, limit)
    finally:
        _disconnect()

    if not rows:
        click.echo("No DLQ entries match.")
        return
    headers = ["name", "job", "queue", "moved_at", "last_error_type", "last_error_message"]
    widths = [max(len(h), 10) for h in headers]
    for r in rows:
        for i, k in enumerate(headers):
            widths[i] = max(widths[i], len(str(r.get(k, "") or "")[:60]))
    sep = "  "
    click.echo(sep.join(h.ljust(w) for h, w in zip(headers, widths)))
    click.echo(sep.join("-" * w for w in widths))
    for r in rows:
        cells = [str(r.get(h, "") or "")[:60] for h in headers]
        click.echo(sep.join(c.ljust(w) for c, w in zip(cells, widths)))
```

Replace the `retry_command` decorator + signature head (body is unchanged):

```python
@dlq_group.command("retry")
@click.option("--site", default=None,
              help="Frappe site name. Defaults to the bench --site context.")
@click.option("--queue", default=None)
@click.option("--limit", default=50, type=int)
@click.option("--job", "job_id", default=None,
              help="Operate on this specific job_id only.")
@pass_context
def retry_command(ctx, site, queue, limit, job_id):
    """Re-enqueue PENDING_REVIEW DLQ entries via conductor.enqueue and mark
    each row RETRIED."""
    site = site or get_site(ctx)
    filters = {"queue": queue} if queue else {}
    _connect_to_site(site)
    # ... (rest unchanged)
```

Replace the `discard_command` decorator + signature head (body is unchanged):

```python
@dlq_group.command("discard")
@click.option("--site", default=None,
              help="Frappe site name. Defaults to the bench --site context.")
@click.option("--queue", default=None)
@click.option("--limit", default=50, type=int)
@click.option("--job", "job_id", default=None)
@pass_context
def discard_command(ctx, site, queue, limit, job_id):
    """Mark PENDING_REVIEW DLQ entries DISCARDED without re-enqueuing."""
    site = site or get_site(ctx)
    filters = {"queue": queue} if queue else {}
    _connect_to_site(site)
    # ... (rest unchanged)
```

**Why both `retry` and `discard` change despite the finding only naming `list`:** the three commands share one calling-convention contract; leaving two of them with `required=True` reintroduces the same operator footgun. `migrate-from-rq` is intentionally narrow (per-tenant migration) and stays as-is.

- [ ] **Step 2: Update existing dlq tests for the new `pass_context` requirement**

Per V5: adding `@pass_context` means every `runner.invoke(dlq_group, ...)` in `tests/test_dlq_commands.py` must now supply `obj={"sites": ["frappe.localhost"], "profile": False}`, otherwise `frappe.commands.pass_context` crashes on `ctx.obj["profile"]`.

Edit each of the six existing tests in `tests/test_dlq_commands.py`:

1. `test_dlq_list_renders_rows` — add `obj={"sites": ["frappe.localhost"], "profile": False}` to its `runner.invoke(dlq_group, ["list", "--site", "frappe.localhost"])` call.
2. `test_dlq_list_filter_by_queue` — same.
3. `test_dlq_list_filter_by_status` — same.
4. `test_dlq_retry_re_enqueues_pending_rows` — same (note this one invokes `["retry", "--site", "frappe.localhost"]`).
5. `test_dlq_retry_skips_non_pending_rows` — same.
6. `test_dlq_discard_marks_row` — same (invokes `["discard", ...]`).

The explicit `--site` argument still wins inside the function body (`site = site or get_site(ctx)` short-circuits), so behavior is unchanged. The `obj=...` is purely to satisfy the wrapper's preamble.

- [ ] **Step 3: Run the dlq test file**

```bash
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_dlq_commands.py -v
```

Expected: every test passes — the six pre-existing tests still pass after the `obj=...` update, and the new `test_dlq_list_inherits_site_from_bench_context` passes.

- [ ] **Step 4: Update `cli.md` matrix**

Edit `docs/roadmap/v2-certification/cli.md`:

1. In the **Automated scenarios** table, change the `dlq list` row's `Exit` to `0`, `Pass` to `✓`, and `Notes` to `inherits --site from bench context as of M7 fix`.
2. Append a new section above "Findings":

```markdown
### Finding 1: FIXED (commit `<HASH-1>`)

`dlq list/retry/discard` now inherit `--site` from the bench Click
context via `pass_context` + `get_site`, matching the pattern used by
`depth`. Explicit `--site` after the subcommand still works for
backwards compatibility. `migrate-from-rq` keeps its required `--site`
because per-tenant migration intent makes the explicit argument
load-bearing.
```

Leave the `<HASH-1>` placeholder. Task 10 backfills it in a single bookkeeping commit at the end of the plan.

- [ ] **Step 5: Commit**

```bash
git add conductor/commands/dlq.py tests/test_dlq_commands.py docs/roadmap/v2-certification/cli.md
git commit -m "$(cat <<'EOF'
cert(M7): dlq subcommands inherit --site from bench context

Finding 3 from SUMMARY.md / cli.md Finding 1: `bench --site X conductor
dlq list` previously failed with "Missing option '--site'" because the
subcommand declared `--site` required. Switch to `pass_context` +
`get_site` (the pattern `conductor depth` already uses). Explicit
`--site` still works.

Apply the same fix to `dlq retry` and `dlq discard` so the group is
consistent. `migrate-from-rq` stays required-`--site` because per-tenant
migration intent makes the argument load-bearing.

Regression test: tests/test_dlq_commands.py::test_dlq_list_inherits_site_from_bench_context.
EOF
)"
```

---

## Task 4: Doctor takeover queue-coverage health-gate — write the failing tests

**Finding addressed:** Finding 2 in `SUMMARY.md` / Finding 1 in `scheduled-jobs.md`.

**Files:**
- Create: `tests/test_doctor.py`

The new check answers one question: when the takeover loop is active, is at least one heartbeat-fresh `Conductor Worker` listening on every queue the takeover loop will dispatch to (per the merged queue-map)?

- [ ] **Step 1: Create the test file with three failing tests**

Write `tests/test_doctor.py`:

```python
"""Tests for `bench conductor doctor`'s takeover queue-coverage check.

The check fires only when `conductor_take_over_frappe_scheduler` is set.
It computes the set of queues the takeover loop's queue-map produces,
introspects heartbeat-fresh `Conductor Worker` rows, and warns when any
queue from the takeover set is not covered by an active worker."""

from __future__ import annotations

import json
from unittest.mock import patch


def test_takeover_queue_coverage_passes_when_workers_cover_every_queue():
    """The default queue-map produces {default, long}. Two heartbeat-fresh
    workers between them covering both queues → check passes."""
    from conductor.doctor import check_takeover_queue_coverage

    workers = [
        {"name": "w1", "queues": json.dumps(["default"]), "stale": False},
        {"name": "w2", "queues": json.dumps(["long"]),    "stale": False},
    ]

    with patch("conductor.doctor._fetch_fresh_workers", return_value=workers):
        result = check_takeover_queue_coverage(
            takeover_enabled=True,
            queue_map={
                "All": "default", "Cron": "default", "Hourly": "default",
                "Daily": "long",  "Weekly": "long", "Monthly": "long",
            },
        )

    assert result.ok is True
    assert "default" in result.detail
    assert "long" in result.detail


def test_takeover_queue_coverage_fails_when_long_queue_uncovered():
    """One worker covers only `default`. The map produces `long` too →
    check fails and names the missing queue."""
    from conductor.doctor import check_takeover_queue_coverage

    workers = [
        {"name": "w1", "queues": json.dumps(["default"]), "stale": False},
    ]

    with patch("conductor.doctor._fetch_fresh_workers", return_value=workers):
        result = check_takeover_queue_coverage(
            takeover_enabled=True,
            queue_map={"Daily": "long", "Hourly": "default"},
        )

    assert result.ok is False
    assert "long" in result.detail
    assert "uncovered" in result.detail.lower() or "missing" in result.detail.lower()


def test_takeover_queue_coverage_skipped_when_takeover_disabled():
    """When the takeover flag is unset, the check is a no-op → ok=True with
    a "skipped" detail string. Doctor must not fail on benches that have
    not opted in."""
    from conductor.doctor import check_takeover_queue_coverage

    result = check_takeover_queue_coverage(
        takeover_enabled=False,
        queue_map={"Daily": "long"},
    )

    assert result.ok is True
    assert "skipped" in result.detail.lower() or "disabled" in result.detail.lower()


def test_takeover_queue_coverage_ignores_stale_workers():
    """A worker whose last heartbeat is older than the freshness threshold
    must NOT count toward queue coverage."""
    from conductor.doctor import check_takeover_queue_coverage

    workers = [
        {"name": "stale-w", "queues": json.dumps(["default", "long"]), "stale": True},
        {"name": "fresh-w", "queues": json.dumps(["default"]),         "stale": False},
    ]

    with patch("conductor.doctor._fetch_fresh_workers", return_value=workers):
        result = check_takeover_queue_coverage(
            takeover_enabled=True,
            queue_map={"Daily": "long", "Hourly": "default"},
        )

    assert result.ok is False
    assert "long" in result.detail
```

- [ ] **Step 2: Run the new tests to verify they fail with ImportError**

```bash
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_doctor.py -v
```

Expected: every test errors with `ImportError: cannot import name 'check_takeover_queue_coverage' from 'conductor.doctor'` (or similar). If they pass, the function already exists — stop and reconcile.

---

## Task 5: Doctor takeover queue-coverage health-gate — implementation + commit

**Files:**
- Modify: `conductor/doctor.py`
- Modify: `docs/roadmap/v2-certification/scheduled-jobs.md`
- Modify: `docs/roadmap/v2-certification/SUMMARY.md`

- [ ] **Step 1: Add the helper, the check, and wire it into `run()`**

At the top of `conductor/doctor.py`, add the new imports and a small named-tuple-style result holder. Insert after the existing imports:

```python
import json
from dataclasses import dataclass
from datetime import timedelta

from conductor.frappe_scheduled_loop import (
    ACTIVATION_FLAG,
    DEFAULT_QUEUE_MAP,
    QUEUE_MAP_KEY,
)

WORKER_FRESHNESS_SECONDS = 90  # heartbeat window — must be > one heartbeat tick


@dataclass
class CheckResult:
    ok: bool
    detail: str
```

Add the helper that introspects worker rows. Place it above `run()`:

```python
def _fetch_fresh_workers() -> list[dict]:
    """Return Conductor Worker rows whose `last_heartbeat` is within the
    freshness window. Each row carries `queues` as the raw JSON string from
    the underlying Long Text field plus a `stale` boolean for tests that
    want to inject staleness without seeding wall-clock data."""
    threshold = datetime.now() - timedelta(seconds=WORKER_FRESHNESS_SECONDS)
    rows = frappe.get_all(
        "Conductor Worker",
        fields=["name", "queues", "last_heartbeat"],
        filters={"last_heartbeat": [">=", threshold]},
        order_by="last_heartbeat desc",
    )
    return [{"name": r["name"], "queues": r["queues"], "stale": False} for r in rows]


def _parse_queues(field_value: str) -> set[str]:
    """`Conductor Worker.queues` is a JSON-encoded list. Return the set of
    queue names. Tolerate empty/None/malformed values by returning an
    empty set — a malformed worker row should not crash doctor."""
    if not field_value:
        return set()
    try:
        parsed = json.loads(field_value)
    except (TypeError, ValueError):
        return set()
    if not isinstance(parsed, list):
        return set()
    return {str(q) for q in parsed}


def check_takeover_queue_coverage(
    *,
    takeover_enabled: bool,
    queue_map: dict[str, str],
) -> CheckResult:
    """Verify every queue the takeover loop dispatches to has at least one
    heartbeat-fresh worker listening. No-op when the takeover flag is unset.

    Pure function: takes the activation flag and the merged queue-map as
    arguments so unit tests can exercise it without seeding site config."""
    if not takeover_enabled:
        return CheckResult(ok=True, detail="takeover disabled — skipped")

    required_queues = set(queue_map.values()) or {"default"}
    fresh = [w for w in _fetch_fresh_workers() if not w.get("stale")]
    covered: set[str] = set()
    for w in fresh:
        covered |= _parse_queues(w.get("queues") or "")

    missing = required_queues - covered
    if missing:
        missing_csv = ", ".join(sorted(missing))
        covered_csv = ", ".join(sorted(covered)) or "none"
        return CheckResult(
            ok=False,
            detail=(
                f"takeover dispatches to {{{', '.join(sorted(required_queues))}}} but "
                f"workers cover {{{covered_csv}}} — uncovered: {missing_csv}. "
                f"Add `--queue {missing_csv}` to a `bench conductor worker` Procfile entry."
            ),
        )
    return CheckResult(
        ok=True,
        detail=f"all takeover queues covered ({', '.join(sorted(required_queues))})",
    )
```

Wire it into `run()`. Replace the four-step counter labels (`[1/6]` through `[6/6]`) with a five/seven-step layout that adds the new check between step 4 and the demo block. The numerator stays accurate whether `--demo` is set or not.

In `run()`, replace the steps section with:

```python
    ok &= _step("[1/7] Redis connectivity", check_redis)
    ok &= _step("[2/7] Default queues seeded", check_queues)
    ok &= _step("[3/7] Consumer groups exist", check_groups)
    ok &= _step("[4/7] XADD/XREADGROUP/XACK round-trip", check_round_trip)

    def check_takeover_coverage() -> str:
        conf = frappe.local.conf or {}
        takeover_enabled = bool(conf.get(ACTIVATION_FLAG, False))
        merged = dict(DEFAULT_QUEUE_MAP)
        merged.update(conf.get(QUEUE_MAP_KEY) or {})
        result = check_takeover_queue_coverage(
            takeover_enabled=takeover_enabled, queue_map=merged,
        )
        if not result.ok:
            raise RuntimeError(result.detail)
        return result.detail

    ok &= _step("[5/7] Takeover queue coverage", check_takeover_coverage)

    if demo:
        # ... existing demo block, but renumber to [6/7] and [7/7]
        ok &= _step("[6/7] End-to-end demo dispatch (conductor.demo.echo)", step_dispatch)
        ok &= _step("[7/7] Result round-trip", step_result)
```

Adjust the existing demo step labels from `[5/6]` and `[6/6]` to `[6/7]` and `[7/7]` so the human-readable counter stays consistent.

- [ ] **Step 2: Run the new doctor tests**

```bash
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_doctor.py -v
```

Expected: all four tests pass.

- [ ] **Step 3: Run the full suite to confirm no regression**

```bash
/Users/osamamuhammed/frappe_15/env/bin/pytest tests -q
```

Expected: 274 + 4 new = 278 passed (or 277/279 ± 1 if the test count of Plan-1 has drifted by a fixture). 17 skipped.

- [ ] **Step 4: Live-bench smoke**

The unit tests prove the function is correct. The live smoke proves the wiring works against the real bench:

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost conductor doctor
```

Expected (since the bench is in the SUMMARY.md state — both workers cover `default,long`): the output now shows seven labelled lines, including:

```
[5/7] Takeover queue coverage......................... OK  (all takeover queues covered (default, long))
```

Exit code 0.

If the line shows `FAIL`, stop. Either the bench drifted from SUMMARY.md's operational state or the worker queues don't actually serialize as the JSON list this code expects — both are reconcilable but require user input.

- [ ] **Step 5: Update `scheduled-jobs.md`**

In `docs/roadmap/v2-certification/scheduled-jobs.md`, update Finding 1's "Operator footgun" line:

```markdown
**Operator footgun:** the doctor health-gate (M7 — landed in commit `<HASH-2>`)
warns when the takeover loop is enabled but the bench worker(s) collectively
don't cover every queue the queue-map produces. Pre-emptively catches the
stuck-QUEUED bug before it strands a single dispatch.
```

Leave `<HASH-2>` for Task 10 to backfill.

- [ ] **Step 6: Update SUMMARY.md**

In `docs/roadmap/v2-certification/SUMMARY.md`, change finding #2's text:

```markdown
2. **Queue-mismatch operator footgun** (M2). Takeover loop's queue-map
   sends Daily/Weekly/Monthly to `long`. If the bench worker doesn't
   listen on `long`, jobs strand silently. **Fix:** Procfile updated to
   `--queue default --queue long`. **M7 fix landed in commit `<HASH-2>`:**
   `bench conductor doctor` now warns when worker queue coverage doesn't
   match the takeover queue-map's range.
```

Leave `<HASH-2>` for Task 10.

- [ ] **Step 7: Commit**

```bash
git add conductor/doctor.py tests/test_doctor.py docs/roadmap/v2-certification/scheduled-jobs.md docs/roadmap/v2-certification/SUMMARY.md
git commit -m "$(cat <<'EOF'
cert(M7): doctor warns on takeover queue-coverage gap

Finding 2 from SUMMARY.md / scheduled-jobs.md Finding 1: when
`conductor_take_over_frappe_scheduler` is true, the queue-map
produces a set of queues the takeover loop dispatches to. If the
bench worker(s) don't collectively cover every one of those queues,
dispatches XADD into a stream nobody reads — jobs strand in QUEUED
silently.

Add a new `[5/7]` doctor step that is a no-op when the takeover flag
is unset (so it never fires for users who haven't opted in) and
otherwise compares the merged queue-map's range against the union of
queues from heartbeat-fresh `Conductor Worker` rows. On gap, fail
loud with the specific missing queue names.

Regression tests in tests/test_doctor.py cover: pass case, fail case,
takeover-disabled skip case, stale-worker exclusion. Live smoke against
the M1-state bench shows OK with `default, long` coverage.
EOF
)"
```

---

## Task 6: Process-supervision documentation (Finding 4)

**Finding addressed:** Finding 4 in `SUMMARY.md` / `multi-worker.md` Finding 2.

**Files:**
- Modify: `docs/explanation-architecture.md`
- Modify: `docs/roadmap/v2-certification/SUMMARY.md` (mark resolved)

This task has no test — it is documentation. The honcho cascade is operational, not a Conductor bug, so the deliverable is an explanation that steers production deployments to a non-cascading supervisor.

- [ ] **Step 1: Read the existing architecture doc to find the right insertion point**

```bash
/Users/osamamuhammed/frappe_15/env/bin/python -c "import sys; sys.exit(0)"  # placeholder; just open the file
```

Open `docs/explanation-architecture.md` and identify the heading at end of the document where a new top-level section makes sense. Add the new section as the *last* `##` block so it doesn't disrupt the existing flow.

- [ ] **Step 2: Append the "Process supervision" section**

Append to `docs/explanation-architecture.md`:

```markdown
## Process supervision in production

Conductor's reliability model assumes that workers can crash and the
remaining workers will reclaim their pending entries via `XAUTOCLAIM`
after the configured idle threshold (60s default). The reclaim path
is verified end-to-end by `tests_chaos/test_kill_during_run.py`.

Whether reclaim **actually happens in production** depends on the
process supervisor that runs your `bench conductor worker` instances.
If the supervisor cascades a single-worker crash into a full
fleet shutdown, the surviving workers are killed before the reclaim
window opens — and Conductor's correctness guarantee never gets a
chance to fire.

### Honcho (`bench start`) is not safe for multi-worker production

`bench start` invokes Honcho with the bench `Procfile`. Honcho's
default behavior is *cascade-on-exit*: any unexpected child process
exit triggers SIGTERM to every other process in the tree. The v2
certification campaign reproduced this on 2026-05-04 — a `kill -9`
on one of two `conductor_worker` entries took down Redis, the web
process, the socketio process, the second `conductor_worker`, and
the conductor scheduler. See `docs/roadmap/v2-certification/multi-worker.md`
for the captured cascade.

This is fine for development. It is **not** fine for a production
deployment that depends on Conductor's reclaim guarantee.

### Recommended supervisors for production

| Supervisor | Why it works | Trade-off |
|---|---|---|
| **systemd unit per worker** | Each worker has its own restart policy and unit boundary; one crash does not touch peers | Linux-only; needs root for unit-file installation |
| **supervisord with `autorestart=true`** | Same isolation as systemd, no root needed; auto-restart fills the gap left by the crashed worker without touching peers | Extra dependency; slightly more configuration than systemd |
| **Two separate Honcho processes** | Run bench infrastructure (Redis, web, socketio, schedule, scheduler) under one Honcho and each worker under its own Honcho. Cascade is contained to the per-worker Honcho — bench infra survives | More moving parts than a single `bench start`; needs a custom shell wrapper |
| **Frappe Cloud's supervisor** | Already isolates workers; would not exhibit the cascade observed on local Honcho | Requires Frappe Cloud (out of scope for self-hosted v2.0.0) |

### What this means for the v2 quickstart

The `Procfile.conductor` shipped with v2 is for **single-machine
development and the v2 certification campaign**. The v2.x release
notes will recommend systemd / supervisord for production multi-worker
deployments and link back to this section.

The Conductor reclaim mechanism itself is correct — verified by
`tests_chaos/test_kill_during_run.py`. This is purely guidance about
how to run Conductor's processes so the reclaim path can do its job.
```

- [ ] **Step 3: Mark the finding resolved in SUMMARY.md**

Update finding #4 in `docs/roadmap/v2-certification/SUMMARY.md`:

```markdown
4. **Honcho cascades a worker SIGKILL into a full bench outage** (M5).
   Operational, not a Conductor bug. **M7 resolution:** added the
   "Process supervision in production" section to
   `docs/explanation-architecture.md` recommending systemd /
   supervisord / split-Honcho over single-Procfile honcho for
   production multi-worker deployments. Reclaim correctness itself
   is unchanged and continues to be verified by
   `tests_chaos/test_kill_during_run.py`.
```

- [ ] **Step 4: Commit**

```bash
git add docs/explanation-architecture.md docs/roadmap/v2-certification/SUMMARY.md
git commit -m "$(cat <<'EOF'
cert(M7): document process-supervision recommendation

Finding 4 from SUMMARY.md: Honcho cascades a worker SIGKILL into a
full bench shutdown, defeating Conductor's reclaim guarantee at the
process-supervisor layer. The reclaim mechanism is correct; the
default `bench start` Procfile is just the wrong supervisor for
multi-worker production.

Add a "Process supervision in production" section to the architecture
explanation doc that recommends systemd / supervisord / split-Honcho
over single-Procfile honcho. No code change. Mark the finding
resolved in SUMMARY.md.
EOF
)"
```

---

## Task 7: Re-run the inflight-cap test (Finding 5)

**Finding addressed:** Finding 5 in `SUMMARY.md` / `multi-worker.md` "DEFERRED" subsection.

**Files:**
- Modify: `docs/roadmap/v2-certification/multi-worker.md`
- Modify: `docs/roadmap/v2-certification/SUMMARY.md` (mark resolved)

This is a live observation against the running bench, not a unit test. The chaos suite already covers the inflight-cap mechanism (`tests_chaos/test_concurrency_cap_chaos.py`); this task fills the campaign's reproducer record.

- [ ] **Step 1: Confirm both `conductor_worker` entries are running**

```bash
ps -ef | grep -E 'conductor (worker|scheduler)' | grep -v grep
```

Expected: at least two `bench --site frappe.localhost conductor worker --queue default --queue long --concurrency 4` processes, plus one `conductor scheduler`. If not, ask the user to restart the bench before continuing.

- [ ] **Step 2: Set the inflight cap on the `default` queue to 2**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost console <<'PY'
import frappe
frappe.db.set_value("Conductor Queue", "default", "max_concurrent", 2, update_modified=False)
frappe.db.commit()
print(frappe.db.get_value("Conductor Queue", "default", "max_concurrent"))
PY
```

Expected output ends with `2`.

- [ ] **Step 3: Drive 200 short-sleep jobs into `default`**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost console <<'PY'
import conductor
ids = [conductor.enqueue("conductor.demo.sleep", queue="default", seconds=0.5) for _ in range(200)]
print("enqueued:", len(ids))
PY
```

Expected: `enqueued: 200`. Note the timestamp at the moment this returns.

- [ ] **Step 4: Sample the in-flight count once per second for 60s**

Sample directly from Redis — `bench console` per-iteration init costs 2–5s and would race against the actual jobs draining (200 × 0.5s with cap=2 ≈ 100s drain time). Direct `redis-cli` reads are sub-millisecond and don't compete with the workers' connection pool.

Confirm the Redis port + db from `baseline.md` (currently `redis://127.0.0.1:11000/2`). If your bench's `redis_url` differs, substitute the right `-p` and `-n` values below.

In a separate terminal, started **immediately after Step 3 returns**:

```bash
for i in $(seq 1 60); do
  redis-cli -p 11000 -n 2 GET "conductor:frappe.localhost:inflight:default" \
    | awk -v i="$i" '{print i, "inflight="($1==""?0:$1)}'
  sleep 1
done | tee /tmp/inflight-samples.txt
```

Expected: every printed line shows `inflight=N` with `N <= 2` for the entire 60-second window. The cap holds across both worker processes because it is enforced at claim time via `conductor.inflight.lua` against a shared Redis counter.

Sanity-check the file before moving on:

```bash
awk '{n=$2; sub(/inflight=/,"",n); if (n+0 > 2) print "VIOLATION at second " $1 ": " $2}' /tmp/inflight-samples.txt
```

Expected: no output. Any line printed here means the cap was violated and the test fails — stop and capture the full samples file before reverting `max_concurrent`.

- [ ] **Step 5: Confirm all 200 jobs eventually reach SUCCEEDED**

After the run is fully drained (~3 minutes):

```bash
bench --site frappe.localhost console <<'PY'
import frappe
from datetime import datetime, timedelta
since = datetime.now() - timedelta(minutes=10)
counts = frappe.db.sql("""SELECT status, COUNT(*) FROM `tabConductor Job`
                          WHERE method = 'conductor.demo.sleep' AND creation >= %s
                          GROUP BY status""", (since,), as_dict=True)
for c in counts: print(c)
PY
```

Expected: `[{'status': 'SUCCEEDED', 'COUNT(*)': 200}]` (no FAILED, no QUEUED, no RUNNING).

- [ ] **Step 6: Restore `max_concurrent` to its prior value**

Most likely `0` (= unlimited):

```bash
bench --site frappe.localhost console <<'PY'
import frappe
frappe.db.set_value("Conductor Queue", "default", "max_concurrent", 0, update_modified=False)
frappe.db.commit()
PY
```

- [ ] **Step 7: Update `multi-worker.md`**

Replace the "Inflight cap" section in `docs/roadmap/v2-certification/multi-worker.md`:

```markdown
## Inflight cap (`Conductor Queue.default.max_concurrent`) — PASS

Re-ran the deferred test on 2026-05-04 against the same two-worker
setup after the bench was restored.

Procedure:
1. Set `Conductor Queue.default.max_concurrent = 2`.
2. Enqueued 200 `conductor.demo.sleep(seconds=0.5)` jobs to `default`.
3. Sampled `INCR conductor:frappe.localhost:inflight:default` once
   per second for 60s in a separate console.

Observed: every sample showed `inflight ≤ 2`. After ~3 minutes all 200
jobs reached SUCCEEDED. Zero FAILED, zero stuck-RUNNING.

The cap is enforced shared-globally between the two workers (the
counter lives in Redis, claimed via the `inflight.lua` script before
each XREADGROUP), which is the design contract — verified live for
the campaign record. The chaos test
`tests_chaos/test_concurrency_cap_chaos.py` continues to be the
source of truth for the mechanism's correctness.

`max_concurrent` was restored to `0` after the test.
```

- [ ] **Step 8: Mark the finding resolved in SUMMARY.md**

Update finding #5:

```markdown
5. **Inflight-cap test deferred** (M5). **M7 resolution:** re-ran on
   2026-05-04 with `max_concurrent = 2` against the two-worker setup;
   inflight stayed ≤ 2 for the entire 60-second window across 200
   jobs and all reached SUCCEEDED. Captured in `multi-worker.md`.
```

- [ ] **Step 9: Commit**

```bash
git add docs/roadmap/v2-certification/multi-worker.md docs/roadmap/v2-certification/SUMMARY.md
git commit -m "$(cat <<'EOF'
cert(M7): inflight-cap re-run — pass

Finding 5 from SUMMARY.md: M5 left the inflight-cap test deferred
because the SIGKILL cascade took down the bench mid-run. Re-ran with
the bench restored: max_concurrent=2 on `default`, 200
conductor.demo.sleep jobs, sampled inflight once/sec for 60s, every
sample ≤ 2, all 200 reached SUCCEEDED. Captured in multi-worker.md.

The chaos test tests_chaos/test_concurrency_cap_chaos.py remains the
source of truth for the mechanism — this is a live record for the
campaign matrix.
EOF
)"
```

---

## Task 8: Dashboard M4 — human-driven `expect` MCP pass

**Finding addressed:** Finding 7 in `SUMMARY.md` / M4 row deferred from Plan-1.

**Files:**
- Create: `docs/roadmap/v2-certification/dashboard.md`
- Modify: `docs/roadmap/v2-certification/SUMMARY.md` (mark M4 ✅)

> ⚠️ **Subagent stop:** This task cannot be subagent-driven — it requires the human operator to drive a real browser session via the `expect` MCP. The catalog at `tests/v2_certification/dashboard_scenarios.md` lists 27 scenarios, each with a screenshot. A subagent should *not* attempt to enter this task; it should pause and prompt the user to execute it.

The output is one row per scenario in `dashboard.md` with `[id, page, control, expected, observed, screenshot, pass]` columns. The scenario catalog is already finalized; the human pass populates the matrix.

- [ ] **Step 1 (human, not subagent): Pre-flight the dashboard**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost browse  # or open http://localhost:8000/conductor-dashboard
```

Log in as Administrator. Confirm the dashboard renders before kicking off `expect` MCP.

- [ ] **Step 2 (human): Walk the catalog**

Open `tests/v2_certification/dashboard_scenarios.md`. The 27 scenarios are grouped by page (Overview, Live Feed, Jobs, DLQ, Schedules, Workers, Workflows, Workflow run detail, Theme + responsiveness). For each scenario:

1. Drive the steps via `mcp__expect__playwright`.
2. Capture a screenshot at the end of the scenario via `mcp__expect__screenshot`. Save under a stable name like `docs/roadmap/v2-certification/dashboard-screenshots/scenario-N-light.png` (and `-dark.png` per the catalog instruction "run it twice — once in light, once in dark").
3. Record observed behavior + pass/fail in the matrix you build in Step 3.

Per-scenario boundaries: complete the scenario or mark it failed. Do not chain scenarios that depend on the previous one's state — each scenario assumes a fresh page load except where the catalog explicitly chains (e.g., scenario 5's pause/resume).

- [ ] **Step 3 (human or subagent after Step 2): Write `dashboard.md`**

Create `docs/roadmap/v2-certification/dashboard.md` with the matrix. Header template:

```markdown
# M4 — Dashboard surface certification matrix

**Captured:** <YYYY-MM-DD> against `frappe.localhost` at
http://localhost:8000/conductor-dashboard.
**Mechanism:** `expect` MCP (Playwright-backed) drove every
scenario from `tests/v2_certification/dashboard_scenarios.md`.
Each scenario was run in light mode and dark mode; screenshots are
saved under `docs/roadmap/v2-certification/dashboard-screenshots/`.

## Summary

- Scenarios in catalog: 27
- Run light: <N>
- Run dark:  <N>
- Pass: <N> / 54 (each scenario × 2 modes)
- Fail: <N>
- Findings: <count from below>

## Per-scenario matrix

| # | Page | Control | Expected | Observed (light) | Observed (dark) | Screenshots | Pass |
|---|---|---|---|---|---|---|---|
| 1 | Overview | Loads with stats | 4 NumberCards + 2 QueueChart cards | <fill> | <fill> | <paths> | ✓/✗ |
| 2 | Overview | NumberCard click navigates | Click Workers → /workers | <fill> | <fill> | <paths> | ✓/✗ |
| ... | ... | ... | ... | ... | ... | ... | ... |
| 27 | Theme + responsiveness | Sidebar collapse | <700px → icon-only sidebar | <fill> | <fill> | <paths> | ✓/✗ |

## Findings

<one entry per failed scenario, or "No findings" if all 27 × 2 pass>
```

The full row text per scenario lives in `tests/v2_certification/dashboard_scenarios.md` — copy each scenario's title/expected verbatim into the matrix cells.

- [ ] **Step 4 (subagent or human): Update SUMMARY.md**

In `docs/roadmap/v2-certification/SUMMARY.md`:

1. Change the M4 row in the "What's done" table from `⏳ deferred` to `✅ commit <HASH>`.
2. Update finding #7:

```markdown
7. **Dashboard surface (M4)** — captured 2026-05-<DD> via `expect`
   MCP. 27 scenarios × {light, dark}. See
   `docs/roadmap/v2-certification/dashboard.md`. Findings (if any)
   triaged into either same-commit micro-fix or punted to v2.x with
   a tracking line in dashboard.md.
```

- [ ] **Step 5: Commit**

```bash
git add docs/roadmap/v2-certification/dashboard.md docs/roadmap/v2-certification/dashboard-screenshots docs/roadmap/v2-certification/SUMMARY.md
git commit -m "$(cat <<'EOF'
cert(M4/M7): dashboard surface matrix populated

Plan-1 deferred M4 because populating the dashboard.md matrix needs a
human-driven `expect` MCP browser session that no subagent can run.
Human pass on 2026-05-<DD>: 27 scenarios × {light, dark} = 54 runs,
captured in dashboard.md with one screenshot per scenario per mode.

Findings (if any) listed inline with their disposition: fix-now, or
punt to v2.x. SUMMARY.md updated to mark M4 done.
EOF
)"
```

---

## Task 9: Add `cancel` and `schedule run-now` to the CLI runner

**Gap addressed:** `cli.md` "Interactive / context-bound commands" — `bench conductor cancel <id>` and `bench conductor schedule run-now <name>` were marked "Not exercised in this run … Marked open; safe to defer to M7."

**Files:**
- Modify: `tests/v2_certification/cli_runner.py`
- Modify: `tests/v2_certification/test_cli_runner.py` (if it exists — check first)
- Modify: `docs/roadmap/v2-certification/cli.md`

The cli_runner harness invokes subcommands via subprocess and grades on exit code + stdout fragments. These two commands need a row to act on, so the harness has to seed a row, run the command, then assert the row's terminal state.

- [ ] **Step 0: Confirm pre-task verification facts are still in hand**

This task depends on V1 (`Conductor Schedule` field names), V3 (`bench conductor cancel` argv shape), and V4 (`bench conductor schedule run-now` argv shape) from the Pre-task verification block. If you skipped pre-task verification, run V1/V3/V4 now — every code block below uses placeholder field/argv names that you MUST replace with the actual ones before writing code.

Specifically:
- The seed dict in Step 2's `_scenario_schedule_run_now` uses `cron`, `kwargs_json` — these are placeholders. Use whatever V1 returned (probably `cron_format`, possibly `args_json`).
- The argv lists in Step 2 use the positional form (`["conductor", "cancel", job_id]`, `["conductor", "schedule", "run-now", name]`) — V3/V4 may show the real shape uses `--id` / `--name` flags, in which case adjust.

- [ ] **Step 1: Read the existing cli_runner harness**

Use `Read` to read `tests/v2_certification/cli_runner.py` end-to-end. Identify:
- The function/class that lists the scenarios (likely `SCENARIOS = [...]` or a `scenarios()` generator).
- The shape of one entry (label, argv, expected exit, expected fragments).
- The helper(s) that actually invoke `bench` (subprocess wrappers); the skeleton in Step 2 uses `_run_bench_subcommand`, `_grade`, `_fail` as **placeholders** — adapt to the real names.

- [ ] **Step 2: Add the two scenarios with their pre-flights**

For `cancel <id>`: the scenario must enqueue a long-running job, capture its id, run `cancel`, then assert the job's `status` is `CANCELLED` (or whatever the canonical cancelled-status string is for Conductor — verify via `frappe.db.get_value("Conductor Job", id, "status")`).

For `schedule run-now <name>`: the scenario must create a temporary `Conductor Schedule` row pointing at `conductor.demo.echo`, run `schedule run-now <name>`, then assert a `Conductor Job` row tied to that schedule reaches SUCCEEDED.

Skeleton additions (the field names `cron` / `kwargs_json`, the argv lists `["conductor", "cancel", job_id]` and `["conductor", "schedule", "run-now", name]`, and the helper names `_run_bench_subcommand` / `_grade` / `_fail` are **all placeholders** — replace with the values you confirmed in Step 0/V1/V3/V4 and Step 1):

```python
def _scenario_cancel():
    """Enqueue conductor.demo.sleep(seconds=30); capture id; run
    `bench conductor cancel <id>`; assert status flips to CANCELLED."""
    import conductor
    job_id = conductor.enqueue("conductor.demo.sleep", queue="default", seconds=30)
    rc, stdout, stderr = _run_bench_subcommand(
        ["conductor", "cancel", job_id],
        site="frappe.localhost",
    )
    if rc != 0:
        return _fail("cancel", rc, stderr or stdout)
    # Wait briefly for the worker to observe cancellation.
    deadline = time.time() + 10
    final_status = None
    import frappe
    while time.time() < deadline:
        frappe.db.rollback()
        final_status = frappe.db.get_value("Conductor Job", job_id, "status")
        if final_status in ("CANCELLED", "TIMED_OUT", "SUCCEEDED", "FAILED"):
            break
        time.sleep(0.2)
    return _grade(
        label="cancel",
        rc=rc,
        ok=(final_status == "CANCELLED"),
        notes=f"final_status={final_status}",
    )


def _scenario_schedule_run_now():
    """Create a Conductor Schedule on conductor.demo.echo, fire run-now,
    assert at least one Conductor Job row appears in <10s.

    Field names verified against the doctype JSON: `schedule_name`
    (PK / unique), `cron_expression`, `kwargs` (msgpack/base64 — leave
    UNSET so schedule_run_now's `if doc.kwargs else {}` short-circuits)."""
    import frappe
    name = "v2cert-schedule-run-now"
    if not frappe.db.exists("Conductor Schedule", name):
        frappe.get_doc({
            "doctype": "Conductor Schedule",
            "schedule_name": name,
            "method": "conductor.demo.echo",
            "queue": "default",
            "cron_expression": "* * * * *",  # every minute, but run-now bypasses cron
            "enabled": 1,
        }).insert(ignore_permissions=True)
        frappe.db.commit()
    rc, stdout, stderr = _run_bench_subcommand(
        ["conductor", "schedule", "run-now", name],
        site="frappe.localhost",
    )
    if rc != 0:
        return _fail("schedule run-now", rc, stderr or stdout)
    # Wait for one Conductor Job to appear with this schedule's method.
    deadline = time.time() + 10
    found = False
    while time.time() < deadline:
        frappe.db.rollback()
        rows = frappe.get_all(
            "Conductor Job",
            filters={"method": "conductor.demo.echo"},
            order_by="creation desc",
            limit=1,
        )
        if rows:
            found = True
            break
        time.sleep(0.2)
    return _grade(
        label="schedule run-now",
        rc=rc,
        ok=found,
        notes="dispatched conductor.demo.echo via schedule run-now" if found else "no Conductor Job appeared",
    )
```

(The exact helper names — `_run_bench_subcommand`, `_grade`, `_fail` — must match the existing harness. Adapt the skeleton to whatever `cli_runner.py` already names them.)

Register both scenarios in the harness's scenario list.

- [ ] **Step 3: If a unit test for the harness exists, add coverage; otherwise smoke**

If `tests/v2_certification/test_cli_runner.py` exists, add a small unit test that asserts both new scenario callables exist and have a label string. Skip the actual subprocess invocation in unit tests — the live smoke in Step 4 is the integration check.

```python
def test_new_scenarios_registered():
    from tests.v2_certification.cli_runner import SCENARIOS  # name may differ
    labels = {s["label"] if isinstance(s, dict) else getattr(s, "label", None) for s in SCENARIOS}
    assert "cancel" in labels
    assert "schedule run-now" in labels
```

(Adapt the import path and shape to the harness's actual API.)

Run:

```bash
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/v2_certification/test_cli_runner.py -v
```

Expected: existing tests still pass, the new test passes.

- [ ] **Step 4: Live smoke against the bench**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
/Users/osamamuhammed/frappe_15/env/bin/python -m tests.v2_certification.cli_runner
```

(Adjust if the harness has a different `__main__` entry point.)

Expected: every scenario including the two new ones reports pass.

- [ ] **Step 5: Update `cli.md`**

In `docs/roadmap/v2-certification/cli.md`:

1. In the "Automated scenarios" table, add two rows:

```markdown
| cancel | `bench --site frappe.localhost conductor cancel <jid>` | 0 | ✓ | live; CANCELLED status confirmed via Conductor Job row |
| schedule run-now | `bench --site frappe.localhost conductor schedule run-now v2cert-schedule-run-now` | 0 | ✓ | live; SUCCEEDED Conductor Job created within 10s |
```

2. In the "Interactive / context-bound commands" table, remove the now-covered entries for `cancel` and `schedule run-now` (or mark them "moved to automated").

3. Update the summary line: "**Summary:** 8/8 pass on the automated runner" (was 6/7 in Plan-1; +2 new + Finding 1 fix flipped `dlq list`).

- [ ] **Step 6: Commit**

```bash
git add tests/v2_certification/cli_runner.py tests/v2_certification/test_cli_runner.py docs/roadmap/v2-certification/cli.md
git commit -m "$(cat <<'EOF'
cert(M7): cli_runner covers cancel + schedule run-now

Plan-1's cli.md left `bench conductor cancel <id>` and
`bench conductor schedule run-now <name>` as "deferred to M7" because
the cli_runner harness lacked seed/teardown for the row each command
needs to act on. Add two scenarios:

- cancel: enqueue a 30s sleep, cancel by id, assert status reaches
  CANCELLED within 10s.
- schedule run-now: insert a temp Conductor Schedule on
  conductor.demo.echo, fire run-now, assert a Conductor Job row
  appears within 10s.

Both scenarios run against the live bench with the existing two-worker
setup. cli.md updated: 8/8 automated scenarios pass.
EOF
)"
```

---

## Task 10: Plan-2 close-out — update SUMMARY.md and v2.md

**Files:**
- Modify: `docs/roadmap/v2-certification/SUMMARY.md`
- Modify: `docs/roadmap/v2.md`

- [ ] **Step 1: Backfill commit hashes into placeholders**

Earlier tasks left `<HASH-N>` placeholders in `cli.md`, `scheduled-jobs.md`, and `SUMMARY.md`. Resolve them now in one sweep:

```bash
git log --oneline --grep='cert(M7)' v2/certification --not 3c59006
```

Map each commit subject to the placeholder it owns:

- `<HASH-1>` ← `cert(M7): dlq subcommands inherit --site...` (from Task 3)
- `<HASH-2>` ← `cert(M7): doctor warns on takeover queue-coverage gap` (from Task 5)
- `<HASH-3>` ← `cert(M7): document process-supervision recommendation` (from Task 6)
- `<HASH-4>` ← `cert(M7): inflight-cap re-run — pass` (from Task 7)
- `<HASH-5>` ← `cert(M4/M7): dashboard surface matrix populated` (from Task 8)
- `<HASH-6>` ← `cert(M7): cli_runner covers cancel + schedule run-now` (from Task 9)

For each placeholder, replace it with the captured 7-char short hash via in-place edit of the relevant file. Use `git grep -l '<HASH-' docs/` to locate every remaining placeholder; the close-out commit must leave none behind.

```bash
git grep -l '<HASH-' docs/
```

After your replacements:

```bash
git grep '<HASH-' docs/
```

Expected: empty output.

- [ ] **Step 2: Confirm every M7 item lands**

Review `docs/roadmap/v2-certification/SUMMARY.md`. Each numbered finding in the backlog (1–7) should now read either `(architectural; resolved by path B in this plan.)` for #1, `M7 fix landed in commit ...` for #2/#3/#5, `M7 resolution:` for #4, or `captured 2026-05-<DD>` for #7. Finding #6 was always informational ("real upstream-Frappe DLQ entry caught"); no action required.

- [ ] **Step 3: Add Plan-2 status to SUMMARY.md**

In the "Headline" or "What's next" section of SUMMARY.md, add a new block (the `<HASH-N>` references should already be live hashes after Step 1):

```markdown
## Plan-2 (M7) status — 2026-05-<DD>

- ✅ Finding 3: dlq subcommands inherit --site (commit `<HASH-1>`)
- ✅ Finding 2: doctor warns on takeover queue-coverage gap (commit `<HASH-2>`)
- ✅ Finding 4: process-supervision recommendation in architecture doc (commit `<HASH-3>`)
- ✅ Finding 5: inflight-cap test re-run; pass (commit `<HASH-4>`)
- ✅ Finding 7: M4 dashboard matrix populated (commit `<HASH-5>`)
- ✅ CLI gaps: cancel + schedule run-now automated (commit `<HASH-6>`)

Plan-2 closes the M7 fix backlog. All findings either fixed or
documented. Comparative KPI re-run + M8 stretch hardening + v2.0.0
release belong to Plan-3.
```

- [ ] **Step 4: Mark M7 done in v2.md**

In `docs/roadmap/v2.md`, append to the "Deliverables checklist":

```markdown
- [x] Fix commits on `v2/certification` branch, each with a regression test (Plan-2 / M7, see `docs/roadmap/v2-certification/SUMMARY.md`)
- [x] `docs/roadmap/v2-certification/dashboard.md` — every control triaged (Plan-2 Task 8)
```

If those bullets already exist in some shape, edit them to point at Plan-2.

- [ ] **Step 5: Final test sweep**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
/Users/osamamuhammed/frappe_15/env/bin/pytest tests -q
```

Expected: ≥ 278 passed (the +4 doctor tests; possibly +1 cli_runner registration test) / 17 skipped. No failures, no errors.

- [ ] **Step 6: Commit Plan-2 close-out**

```bash
git add docs/roadmap/v2-certification/SUMMARY.md docs/roadmap/v2-certification/cli.md docs/roadmap/v2-certification/scheduled-jobs.md docs/roadmap/v2.md
git commit -m "$(cat <<'EOF'
cert(M7): Plan-2 close-out — fix backlog complete

Every M7 finding from Plan-1 SUMMARY.md is now either fixed with a
regression test (3, 2, 5) or documented (4, 7). Plan-2 status block
appended to SUMMARY.md with one bullet per fix and its commit hash.
v2.md deliverables checklist updated. Cross-reference hashes from
earlier per-task commits backfilled into cli.md, scheduled-jobs.md,
and SUMMARY.md.

Next up (Plan-3): M8 stretch hardening (Procfile.conductor production
shape, add_to_apps_screen, doctor's full health-gate including
pause_scheduler assertion, optional CI smoke loop), comparative KPI
re-run as a release gate, README + docs/index.md refresh, and the
v2.0.0 tag + GitHub release notes.
EOF
)"
```

Note: include any other doc files that still carry `<HASH-N>` placeholders in your `git add` line. The `git grep '<HASH-' docs/` from Step 1 should have left zero remaining placeholders before you reach this commit.

---

## Self-review checklist (already run)

- ✅ **Spec coverage:** Findings 2, 3, 4, 5, 7 from SUMMARY.md → Tasks 5, 3, 6, 7, 8. CLI gaps → Task 9. Plan-2 close-out → Task 10. Operational precondition → Task 1. Pre-task verification (V1–V5) catches the schema/argv/contract assumptions that would otherwise blow up at execution time. Findings 1 (architectural; pivoted in Plan-1) and 6 (informational) need no action.
- ✅ **No placeholders blocking execution:** Every code block contains the change body. The `<HASH-N>` placeholders are explicit, numbered hand-back points; Task 10 Step 1 backfills them in one bookkeeping commit instead of relying on the no-amend-banned `--amend --no-edit` pattern.
- ✅ **Type consistency:** `CheckResult(ok, detail)` is used in both the doctor implementation step and the four doctor unit tests. The harness helper names in Task 9 (`_run_bench_subcommand`, `_grade`, `_fail`, `SCENARIOS`) plus the seed-row field names (`cron`, `kwargs_json`) are flagged in Task 9 Step 0 as **placeholders to replace** with whatever V1/V3/V4 returns — not invented out of whole cloth.
- ✅ **TDD where it fits:** Tasks 2–3 (dlq) and 4–5 (doctor) follow failing-test-first. Task 9 (cli_runner) does too where it can. Tasks 6 (docs), 7 (live observation), 8 (human-driven) explicitly diverge from TDD because their deliverable is not code.
- ✅ **Subagent feasibility:** Tasks 1, 2–7, 9, 10 are subagent-safe. Task 8 carries an explicit `Subagent stop` block at the top.
- ✅ **Commit hygiene:** No task uses `git commit --amend`. Per-task commits stand alone; the close-out commit is the single bookkeeping commit that ties hashes back into the matrix files.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-04-conductor-v2-m7-fix-backlog.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task (skipping Task 8, which the human runs), review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
