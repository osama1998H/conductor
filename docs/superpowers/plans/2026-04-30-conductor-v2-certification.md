# Conductor v2 — Certification Campaign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the v2 empirical certification campaign — extend the `frappe.enqueue` shim so it intercepts in-process calls, then exercise the running engine on a real Frappe + HRMS site (`frappe.localhost`) and produce three certification matrices that prove every Scheduled Job Type, every CLI subcommand, and every dashboard control runs end-to-end through Conductor.

**Architecture:** Path A\* of the v2 design. M1 extends `conductor.frappe_compat` with a process-level monkey-patch on `frappe.enqueue` that diverts in-process calls into `conductor.enqueue` when the current site has Conductor installed and the bench-wide activation flag is set. The campaign then leans on Frappe's own `bench schedule` daemon as the cron driver — every tick now enters Conductor instead of RQ. M2–M5 build small Python drivers and `expect` MCP browser scenarios that exercise the full surface; outcomes land in markdown matrices under `docs/roadmap/v2-certification/`. M6 closes the soak window and certifies natural-cron coverage.

**Tech Stack:** Python 3.10, Frappe v15, Conductor v1.0.0, pytest (running under the bench virtualenv `/Users/osamamuhammed/frappe_15/env/bin/pytest`), Redis, `bench` CLI, `expect` MCP (Playwright-backed browser automation), markdown matrices.

**Branch:** `v2/certification` (cut from `develop` in Task 1).

**Spec:** `docs/roadmap/v2.md`.

**Plan scope:** M1 through M6 only. The fix backlog (M7) cannot be planned in detail until the campaign produces findings; that plan will be written after Task 32 (M6 close). The hardening + release phases (M8–M9) get their own plan.

---

## Decomposition rationale

This plan stops at M6 because the work it produces — an extended shim plus three populated certification matrices — is independently shippable evidence. M7 (fix backlog) is generated *from* this plan's output and cannot be specified before. M8–M9 are well-defined but smaller and benefit from being planned in light of M2–M6 findings (e.g., the `doctor` health-gate's exact assertions depend on what the patch needs to verify in production).

---

## File structure

| File | Status | Responsibility |
|---|---|---|
| `conductor/frappe_compat.py` | Modify | Add `install_inprocess_patch()` + sentinel guarding; keep existing HTTP shim unchanged |
| `conductor/__init__.py` | Modify | Auto-install the in-process patch when bench-wide flag is set |
| `conductor/hooks.py` | Modify | Document the flag in a comment; no functional change to hook keys |
| `tests/test_frappe_compat_inprocess.py` | Create | Unit tests for the in-process patch |
| `Procfile.conductor` | Modify | Production-ready sample with worker + scheduler entries (the M8 stretch is bigger — this commit just unblocks M1) |
| `/Users/osamamuhammed/frappe_15/sites/common_site_config.json` | Modify | Set `conductor_intercept_frappe_enqueue: true` (bench-wide) |
| `/Users/osamamuhammed/frappe_15/Procfile` | Modify | Comment out RQ `worker:`, add `conductor_worker:` and `conductor_scheduler:` lines |
| `docs/roadmap/v2-certification/README.md` | Create | Index for the certification artifacts |
| `docs/roadmap/v2-certification/baseline.md` | Create | Day-0 baseline snapshot |
| `docs/roadmap/v2-certification/scheduled-jobs.md` | Create | 105-row matrix |
| `docs/roadmap/v2-certification/cli.md` | Create | CLI subcommand matrix |
| `docs/roadmap/v2-certification/dashboard.md` | Create | Dashboard control matrix |
| `docs/roadmap/v2-certification/multi-worker.md` | Create | Multi-worker findings |
| `docs/roadmap/v2-certification/soak.md` | Create | 7-day soak observations |
| `tests/v2_certification/__init__.py` | Create | Package marker |
| `tests/v2_certification/conftest.py` | Create | Shared pytest fixtures (site context, conductor cleanup) |
| `tests/v2_certification/scheduler_driver.py` | Create | Force-trigger driver: enumerates `tabScheduled Job Type`, calls each method, records `Conductor Job` outcome |
| `tests/v2_certification/test_scheduler_driver.py` | Create | Tests for the driver (unit + small integration) |
| `tests/v2_certification/cli_runner.py` | Create | CLI exerciser harness |
| `tests/v2_certification/dashboard_scenarios.md` | Create | Scenario catalog for `expect` MCP runs (one entry per route × control) |

---

## Conventions for every task

- **Working directory:** `/Users/osamamuhammed/frappe_15/apps/conductor` for code edits and pytest. `/Users/osamamuhammed/frappe_15` for `bench` commands.
- **Python:** always invoke pytest as `/Users/osamamuhammed/frappe_15/env/bin/pytest`, never bare `pytest`.
- **Bench commands:** always include `--site frappe.localhost` for site-scoped commands. Run from `/Users/osamamuhammed/frappe_15`.
- **Branch:** `v2/certification`. Never push to `develop` directly.
- **Commits:** one logical change per commit. Stage explicit paths (`git add path/...`), never `git add -A`.
- **Matrix updates:** every campaign run that records a result commits the matrix immediately with a `cert(matrix): ...` message.
- **Stop rule:** if any task surfaces a behavior that contradicts an earlier plan task, stop and check in with the user before continuing.

---

## Task 1: Cut campaign branch and scaffold certification directory

**Files:**
- Create: `docs/roadmap/v2-certification/README.md`

- [ ] **Step 1: Verify current branch state**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git status
git branch --show-current
```

Expected: clean working tree, current branch is `develop`.

- [ ] **Step 2: Cut the campaign branch**

```bash
git checkout -b v2/certification
```

Expected: switched to a new branch `v2/certification`.

- [ ] **Step 3: Create the certification index**

Write `docs/roadmap/v2-certification/README.md`:

```markdown
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
```

- [ ] **Step 4: Commit**

```bash
git add docs/roadmap/v2-certification/README.md
git commit -m "cert: scaffold v2-certification directory + index"
```

---

## Task 2: Write the failing test for the in-process `frappe.enqueue` patch

**Files:**
- Create: `tests/test_frappe_compat_inprocess.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_frappe_compat_inprocess.py` with:

```python
"""Tests for the in-process frappe.enqueue patch.

The v1 frappe_compat shim only catches HTTP /api/method/frappe.enqueue calls.
v2 adds a Python-level patch so that intra-process frappe.enqueue() — used by
bench schedule and by application code that calls frappe.enqueue directly — is
also routed through conductor.enqueue when the bench-wide flag is set.

Activation rules:
- Bench flag `conductor_intercept_frappe_enqueue=True` in common_site_config.json
  turns the patch ON for the whole process.
- The patched function checks at call time whether the current site has
  conductor installed; if not, it falls back to the original frappe.enqueue.
- The patch is idempotent (installing twice is a no-op).
- The patch records the original function so it can be uninstalled in tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from conductor import frappe_compat


def test_install_is_idempotent():
    """Calling install_inprocess_patch twice does not double-wrap."""
    fake_frappe = MagicMock()
    original = MagicMock(return_value="rq-job-id")
    fake_frappe.enqueue = original

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        frappe_compat.install_inprocess_patch()
        first = fake_frappe.enqueue
        frappe_compat.install_inprocess_patch()
        second = fake_frappe.enqueue
        assert first is second, "install_inprocess_patch must be idempotent"


def test_uninstall_restores_original():
    """uninstall_inprocess_patch restores the pre-patch frappe.enqueue."""
    fake_frappe = MagicMock()
    original = MagicMock(return_value="rq-job-id")
    fake_frappe.enqueue = original

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        frappe_compat.install_inprocess_patch()
        assert fake_frappe.enqueue is not original
        frappe_compat.uninstall_inprocess_patch()
        assert fake_frappe.enqueue is original


def test_patched_call_routes_to_conductor_when_site_has_conductor():
    """When the current site has conductor installed, the patch diverts."""
    fake_frappe = MagicMock()
    fake_frappe.local.site = "alpha"
    fake_frappe.enqueue = MagicMock(return_value="rq-job-id")

    with patch.object(frappe_compat, "_frappe_module", fake_frappe), \
         patch.object(frappe_compat, "_site_has_conductor", return_value=True), \
         patch.object(frappe_compat, "_conductor_enqueue", return_value="cnd-1") as cnd:
        frappe_compat.install_inprocess_patch()
        result = fake_frappe.enqueue("foo.bar", queue="default", x=1)

    assert result == "cnd-1"
    cnd.assert_called_once_with("foo.bar", queue="default", x=1)


def test_patched_call_falls_back_when_site_lacks_conductor():
    """When the current site does NOT have conductor, the patch falls back to the original."""
    fake_frappe = MagicMock()
    fake_frappe.local.site = "beta"
    original = MagicMock(return_value="rq-job-id")
    fake_frappe.enqueue = original

    with patch.object(frappe_compat, "_frappe_module", fake_frappe), \
         patch.object(frappe_compat, "_site_has_conductor", return_value=False):
        frappe_compat.install_inprocess_patch()
        result = fake_frappe.enqueue("foo.bar", queue="default", x=1)

    assert result == "rq-job-id"
    original.assert_called_once_with("foo.bar", queue="default", x=1)


def test_patched_call_falls_back_when_conductor_raises_importerror():
    """If conductor cannot be imported at call time, fall back to original."""
    fake_frappe = MagicMock()
    fake_frappe.local.site = "alpha"
    original = MagicMock(return_value="rq-job-id")
    fake_frappe.enqueue = original

    with patch.object(frappe_compat, "_frappe_module", fake_frappe), \
         patch.object(frappe_compat, "_site_has_conductor", return_value=True), \
         patch.object(frappe_compat, "_conductor_enqueue", side_effect=ImportError):
        frappe_compat.install_inprocess_patch()
        result = fake_frappe.enqueue("foo.bar", queue="default")

    assert result == "rq-job-id"
    original.assert_called_once_with("foo.bar", queue="default")


def test_patched_call_signals_dispatch_failure_loudly():
    """Conductor dispatch errors propagate — they do NOT silently fall back."""
    fake_frappe = MagicMock()
    fake_frappe.local.site = "alpha"
    fake_frappe.enqueue = MagicMock(return_value="rq-job-id")

    with patch.object(frappe_compat, "_frappe_module", fake_frappe), \
         patch.object(frappe_compat, "_site_has_conductor", return_value=True), \
         patch.object(frappe_compat, "_conductor_enqueue", side_effect=RuntimeError("redis down")):
        frappe_compat.install_inprocess_patch()
        with pytest.raises(RuntimeError, match="redis down"):
            fake_frappe.enqueue("foo.bar")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_frappe_compat_inprocess.py -v
```

Expected: every test fails with `AttributeError` (e.g., `_frappe_module`, `install_inprocess_patch`, `_site_has_conductor`, `_conductor_enqueue` do not exist on `frappe_compat`).

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/test_frappe_compat_inprocess.py
git commit -m "test: failing tests for in-process frappe.enqueue patch"
```

---

## Task 3: Implement the in-process patch

**Files:**
- Modify: `conductor/frappe_compat.py`

- [ ] **Step 1: Replace `conductor/frappe_compat.py` with the extended module**

```python
"""Drop-in shim with the same call signature as frappe.enqueue.

There are two layers here:

1. **HTTP shim** (v1).  Client apps opt in via:
       override_whitelisted_methods = {"frappe.enqueue": "conductor.frappe_compat.enqueue"}
   in their `hooks.py`. The override rewrites HTTP `/api/method/frappe.enqueue`
   calls so they land here.

2. **In-process patch** (v2).  When the bench-wide flag
       conductor_intercept_frappe_enqueue: true
   is set in `sites/common_site_config.json`, `install_inprocess_patch()` runs
   on conductor import and replaces `frappe.enqueue` at the Python level. The
   patched function diverts to `conductor.enqueue` only when the current site
   has conductor installed; otherwise it falls back to the original
   `frappe.enqueue`.
"""

from __future__ import annotations

from typing import Any, Callable

import frappe

import conductor

# Module-level handles for testability — tests patch these to inject fakes.
_frappe_module = frappe
_conductor_enqueue: Callable[..., str] = conductor.enqueue

# Sentinel attribute set on the patched function so install is idempotent
# and uninstall can restore the original cleanly.
_PATCH_MARKER = "__conductor_inprocess_patch__"
_ORIGINAL_ATTR = "__conductor_original_enqueue__"


@frappe.whitelist()
def enqueue(method: str, queue: str = "default", timeout: int | None = None, **kwargs: Any) -> str:
    """frappe.enqueue-shaped wrapper around conductor.enqueue (HTTP shim entry)."""
    return conductor.enqueue(method, queue=queue, timeout=timeout, **kwargs)


def _site_has_conductor() -> bool:
    """True when the currently-initialized Frappe site has conductor installed."""
    try:
        site = getattr(_frappe_module.local, "site", None)
        if not site:
            return False
        installed = _frappe_module.get_installed_apps()
        return "conductor" in installed
    except Exception:
        return False


def _make_patched_enqueue(original: Callable[..., Any]) -> Callable[..., Any]:
    """Build the replacement frappe.enqueue."""

    def patched(method: str, queue: str = "default", timeout: int | None = None, **kwargs: Any):
        if not _site_has_conductor():
            return original(method, queue=queue, timeout=timeout, **kwargs)
        try:
            return _conductor_enqueue(method, queue=queue, timeout=timeout, **kwargs)
        except ImportError:
            return original(method, queue=queue, timeout=timeout, **kwargs)

    setattr(patched, _PATCH_MARKER, True)
    setattr(patched, _ORIGINAL_ATTR, original)
    return patched


def install_inprocess_patch() -> None:
    """Replace frappe.enqueue with a Conductor-aware version.

    Idempotent: a second call is a no-op. Tests may call uninstall_inprocess_patch()
    to restore the original.
    """
    current = getattr(_frappe_module, "enqueue", None)
    if current is None:
        return
    if getattr(current, _PATCH_MARKER, False):
        return
    _frappe_module.enqueue = _make_patched_enqueue(current)


def uninstall_inprocess_patch() -> None:
    """Restore the un-patched frappe.enqueue (test helper)."""
    current = getattr(_frappe_module, "enqueue", None)
    if current is None:
        return
    if not getattr(current, _PATCH_MARKER, False):
        return
    original = getattr(current, _ORIGINAL_ATTR, None)
    if original is not None:
        _frappe_module.enqueue = original
```

- [ ] **Step 2: Run the new tests**

```bash
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_frappe_compat_inprocess.py -v
```

Expected: all six tests pass.

- [ ] **Step 3: Run the full unit suite to verify no regression**

```bash
/Users/osamamuhammed/frappe_15/env/bin/pytest tests -x --ignore=tests/comparative --ignore=tests/benchmarks
```

Expected: no failures introduced. Existing `tests/conductor/doctype/conductor_job/test_worker_integration.py` may import `frappe_compat`; verify it still passes.

- [ ] **Step 4: Commit**

```bash
git add conductor/frappe_compat.py
git commit -m "feat(frappe_compat): add in-process frappe.enqueue patch"
```

---

## Task 4: Auto-install the patch on conductor import when the bench flag is set

**Files:**
- Modify: `conductor/__init__.py`

- [ ] **Step 1: Read current `__init__.py`**

Open `conductor/__init__.py` and confirm it currently reads:

```python
__version__ = "1.0.0"

from conductor.api import RetryPolicy, cancel, context, enqueue, job  # noqa: E402,F401
from conductor.workflow import run_workflow, cancel_workflow_run  # noqa: E402,F401

__all__ = ["enqueue", "context", "job", "RetryPolicy", "cancel", "run_workflow", "cancel_workflow_run", "__version__"]
```

- [ ] **Step 2: Append the auto-install bootstrap**

Replace the file with:

```python
__version__ = "1.0.0"

from conductor.api import RetryPolicy, cancel, context, enqueue, job  # noqa: E402,F401
from conductor.workflow import run_workflow, cancel_workflow_run  # noqa: E402,F401

__all__ = ["enqueue", "context", "job", "RetryPolicy", "cancel", "run_workflow", "cancel_workflow_run", "__version__"]


def _maybe_install_inprocess_patch() -> None:
    """Install the in-process frappe.enqueue patch when the bench flag is set.

    Reads the flag from common_site_config.json so it applies to the whole bench
    (every process that imports conductor). The patch itself decides per call
    whether to actually divert based on current site state.
    """
    try:
        import frappe
        conf = getattr(frappe, "conf", None) or {}
        if not conf.get("conductor_intercept_frappe_enqueue", False):
            return
        from conductor.frappe_compat import install_inprocess_patch
        install_inprocess_patch()
    except Exception:
        # Bootstrap must never break import. Failures here are visible via
        # `bench conductor doctor` once the M8 health-gate lands.
        pass


_maybe_install_inprocess_patch()
```

- [ ] **Step 3: Add a regression test that import is idempotent**

Append to `tests/test_frappe_compat_inprocess.py`:

```python
def test_bootstrap_skips_when_flag_unset():
    """Importing conductor with no flag does not patch frappe.enqueue."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {}
    original = MagicMock()
    fake_frappe.enqueue = original

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        # Re-run the bootstrap explicitly — module is already imported.
        import conductor
        conductor._maybe_install_inprocess_patch()

    assert fake_frappe.enqueue is original


def test_bootstrap_installs_when_flag_set():
    """Importing conductor with the flag set installs the patch."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {"conductor_intercept_frappe_enqueue": True}
    original = MagicMock()
    fake_frappe.enqueue = original

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        import conductor
        conductor._maybe_install_inprocess_patch()
        # Bootstrap should have replaced enqueue with a patched version.
        assert getattr(fake_frappe.enqueue, frappe_compat._PATCH_MARKER, False)
        # Clean up so other tests are unaffected.
        frappe_compat.uninstall_inprocess_patch()
```

- [ ] **Step 4: Run the suite**

```bash
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_frappe_compat_inprocess.py -v
```

Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add conductor/__init__.py tests/test_frappe_compat_inprocess.py
git commit -m "feat(conductor): bootstrap in-process patch from bench flag"
```

---

## Task 5: Document the new flag in `hooks.py` and `reference-configuration.md`

**Files:**
- Modify: `conductor/hooks.py`
- Modify: `docs/reference-configuration.md`

- [ ] **Step 1: Update the comment in `hooks.py`**

Find the existing override block in `conductor/hooks.py` (around line 179) and replace it with:

```python
# Route HTTP /api/method/frappe.enqueue calls through Conductor's drop-in
# shim. Intra-process Python `frappe.enqueue(...)` calls are also routed when
# `conductor_intercept_frappe_enqueue: true` is set in common_site_config.json
# (installed by conductor.__init__._maybe_install_inprocess_patch).
override_whitelisted_methods = {
    "frappe.enqueue": "conductor.frappe_compat.enqueue",
}
```

- [ ] **Step 2: Document the flag in the configuration reference**

Open `docs/reference-configuration.md`, find the section that lists site_config / common_site_config keys, and append (preserving existing alphabetic order if any):

```markdown
### `conductor_intercept_frappe_enqueue`

**Where:** `sites/common_site_config.json` (bench-wide).
**Default:** `false`.
**Effect:** When `true`, conductor monkey-patches `frappe.enqueue` at process
start so in-process Python calls (e.g., from `bench schedule` ticks) are
routed through `conductor.enqueue`. The patch checks per call whether the
current site has conductor installed; sites without conductor fall back to
the original `frappe.enqueue` and remain on RQ. Set this flag once you have
conductor processes running on every site that needs it.
```

- [ ] **Step 3: Commit**

```bash
git add conductor/hooks.py docs/reference-configuration.md
git commit -m "docs: explain conductor_intercept_frappe_enqueue flag"
```

---

## Task 6: Take the Day-0 baseline snapshot

**Files:**
- Create: `docs/roadmap/v2-certification/baseline.md`

- [ ] **Step 1: Run the doctor demo and capture output**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost conductor doctor --demo > /tmp/v2-doctor-baseline.txt 2>&1
echo "exit=$?"
```

Expected: exit code 0. Save the file path; the contents go into `baseline.md` below.

- [ ] **Step 2: Snapshot Redis key counts**

```bash
redis-cli -p 11000 --scan --pattern 'conductor:frappe.localhost:*' | wc -l > /tmp/v2-redis-keycount.txt
redis-cli -p 11000 --scan --pattern 'conductor:frappe.localhost:*' | sort > /tmp/v2-redis-keys.txt
```

(The default Frappe bench's redis_queue listens on port 11000 — verify with `cat config/redis_queue.conf` if the count looks wrong.)

- [ ] **Step 3: Snapshot `tabConductor *` row counts**

```bash
bench --site frappe.localhost mariadb -e "
SELECT 'Conductor Job' AS doctype, COUNT(*) AS rows FROM \`tabConductor Job\`
UNION ALL SELECT 'Conductor Job Run', COUNT(*) FROM \`tabConductor Job Run\`
UNION ALL SELECT 'Conductor DLQ Entry', COUNT(*) FROM \`tabConductor DLQ Entry\`
UNION ALL SELECT 'Conductor Schedule', COUNT(*) FROM \`tabConductor Schedule\`
UNION ALL SELECT 'Conductor Worker', COUNT(*) FROM \`tabConductor Worker\`
UNION ALL SELECT 'Conductor Workflow Run', COUNT(*) FROM \`tabConductor Workflow Run\`
UNION ALL SELECT 'Conductor Workflow Step Run', COUNT(*) FROM \`tabConductor Workflow Step Run\`;
" > /tmp/v2-mariadb-rows.txt
```

- [ ] **Step 4: Write `baseline.md`**

Create `docs/roadmap/v2-certification/baseline.md`:

```markdown
# Day-0 Baseline

**Captured:** <YYYY-MM-DD HH:MM TZ>
**Site:** frappe.localhost
**Conductor version:** 1.0.0 (commit <SHA>)

## `bench conductor doctor --demo`

```text
<paste contents of /tmp/v2-doctor-baseline.txt>
```

Exit: 0.

## Redis keyspace

Total `conductor:frappe.localhost:*` keys: <N from /tmp/v2-redis-keycount.txt>

Full key list saved at `/tmp/v2-redis-keys.txt` (kept locally; not committed).

## MariaDB row counts

| DocType | Rows |
|---|---|
<paste rows from /tmp/v2-mariadb-rows.txt as a markdown table>
```

Replace every angle-bracket placeholder with actual values from the captured outputs. The plan does not commit `/tmp/v2-redis-keys.txt`; that file is local context only.

- [ ] **Step 5: Commit**

```bash
git add docs/roadmap/v2-certification/baseline.md
git commit -m "cert: M1 day-0 baseline snapshot"
```

---

## Task 7: Enable the bench-wide flag and rewrite the live Procfile

**Files:**
- Modify: `/Users/osamamuhammed/frappe_15/sites/common_site_config.json`
- Modify: `/Users/osamamuhammed/frappe_15/Procfile`

These two files live outside the conductor repo. Their changes are NOT committed to the conductor branch. They are operational state for the local bench during the campaign.

- [ ] **Step 1: Back up both files**

```bash
cp /Users/osamamuhammed/frappe_15/sites/common_site_config.json \
   /Users/osamamuhammed/frappe_15/sites/common_site_config.json.pre-v2

cp /Users/osamamuhammed/frappe_15/Procfile \
   /Users/osamamuhammed/frappe_15/Procfile.pre-v2
```

- [ ] **Step 2: Enable the flag**

Edit `/Users/osamamuhammed/frappe_15/sites/common_site_config.json`. Add the key (preserve existing keys, valid JSON):

```json
{
  "...existing keys...": "...",
  "conductor_intercept_frappe_enqueue": true
}
```

Verify:

```bash
python -c "import json; print(json.load(open('/Users/osamamuhammed/frappe_15/sites/common_site_config.json'))['conductor_intercept_frappe_enqueue'])"
```

Expected: `True`.

- [ ] **Step 3: Stop the bench worker, add conductor processes**

Edit `/Users/osamamuhammed/frappe_15/Procfile`. Comment out the existing `worker:` line and append:

```
# Disabled for v2 campaign — Conductor takes over the worker role.
# worker: OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES NO_PROXY=* bench worker 1>> logs/worker.log 2>> logs/worker.error.log

conductor_worker: OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES NO_PROXY=* bench --site frappe.localhost conductor worker --queue default --concurrency 4 1>> logs/conductor_worker.log 2>> logs/conductor_worker.error.log
conductor_scheduler: OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES NO_PROXY=* bench --site frappe.localhost conductor scheduler 1>> logs/conductor_scheduler.log 2>> logs/conductor_scheduler.error.log
```

Keep all other lines (`redis_cache`, `redis_queue`, `web`, `socketio`, `watch`, `schedule`) unchanged.

- [ ] **Step 4: Document the operational change in `baseline.md`**

Append to `docs/roadmap/v2-certification/baseline.md`:

```markdown
## Operational changes (M1)

- Set `conductor_intercept_frappe_enqueue: true` in `common_site_config.json`.
- Commented out `worker:` line in bench `Procfile`; added `conductor_worker:` and `conductor_scheduler:`.
- Backups: `common_site_config.json.pre-v2`, `Procfile.pre-v2`.
- Restoration procedure: `cp Procfile.pre-v2 Procfile && cp sites/common_site_config.json.pre-v2 sites/common_site_config.json`.
```

- [ ] **Step 5: Restart the bench and verify processes**

```bash
cd /Users/osamamuhammed/frappe_15
# If a bench start is already running, stop it (Ctrl-C) and restart:
bench start &
sleep 10
ps aux | grep -E "conductor (worker|scheduler)" | grep -v grep
```

Expected: two `bench ... conductor worker` and `bench ... conductor scheduler` processes visible.

- [ ] **Step 6: Confirm the patch is live in those processes**

```bash
bench --site frappe.localhost console <<'PY'
import frappe
import conductor.frappe_compat as fc
print("patch_installed=", getattr(frappe.enqueue, fc._PATCH_MARKER, False))
PY
```

Expected: `patch_installed= True`.

- [ ] **Step 7: Commit baseline.md update**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add docs/roadmap/v2-certification/baseline.md
git commit -m "cert: M1 operational changes recorded in baseline"
```

---

## Task 8: Smoke-test the patch with one HRMS scheduled job

**Files:** none new

This is a guard rail before we run all 105. If the patch doesn't catch one tick, it won't catch 105.

- [ ] **Step 1: Pick a deterministic, fast scheduled job**

From the CSV, `hrms.controllers.employee_reminders.send_reminders_in_advance_weekly` is weekly and side-effect-light (sends emails based on Employee state — and a fresh local site has no employees, so it's a no-op).

- [ ] **Step 2: Force-trigger it via Frappe's runner**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost execute hrms.controllers.employee_reminders.send_reminders_in_advance_weekly
```

Expected: the call returns immediately. (`bench execute` runs in-process; this is enough to verify import + entry-point correctness.)

- [ ] **Step 3: Trigger via the Scheduled Job Type's "Run Now"**

Open the Frappe desk in a browser and navigate to:
`http://localhost:8000/app/scheduled-job-type/employee_reminders.send_reminders_in_advance_weekly`

Click "Run Now". This dispatches via Frappe's scheduler internals — the path that uses `frappe.enqueue` in process.

- [ ] **Step 4: Verify a Conductor Job row appeared**

```bash
bench --site frappe.localhost mariadb -e "
SELECT name, method, status, attempts FROM \`tabConductor Job\`
WHERE method = 'hrms.controllers.employee_reminders.send_reminders_in_advance_weekly'
ORDER BY creation DESC LIMIT 5;"
```

Expected: at least one row with `status` in (`Succeeded`, `Running`, `Queued`).

If zero rows appear: the patch is not catching the call. Stop and debug — do not proceed to Task 9 with a broken patch.

- [ ] **Step 5: Append the smoke result to `baseline.md`**

```markdown
## M1 smoke test (Task 8)

Triggered: `hrms.controllers.employee_reminders.send_reminders_in_advance_weekly` via Run Now.
Conductor Job row: <name from query>
Status: <status from query>
Attempts: <attempts from query>
```

- [ ] **Step 6: Commit**

```bash
git add docs/roadmap/v2-certification/baseline.md
git commit -m "cert: M1 smoke verifies in-process patch catches Run Now"
```

---

## Task 9: Build the scheduler driver harness

**Files:**
- Create: `tests/v2_certification/__init__.py`
- Create: `tests/v2_certification/conftest.py`
- Create: `tests/v2_certification/scheduler_driver.py`

The driver enumerates `tabScheduled Job Type`, calls each `Run Now`-equivalent code path, and records what `Conductor Job` row(s) appeared, plus terminal status and attempt count. Output is a JSON blob that gets formatted into `scheduled-jobs.md`.

- [ ] **Step 1: Create the package marker**

```python
# tests/v2_certification/__init__.py
"""Helpers for the v2 certification campaign (M2-M5)."""
```

- [ ] **Step 2: Create `conftest.py`**

```python
# tests/v2_certification/conftest.py
"""Fixtures shared across the campaign harness."""
from __future__ import annotations

import pytest
import frappe


@pytest.fixture()
def frappe_site():
    """Yield the configured Frappe site name and ensure connect/destroy book-ends."""
    site = "frappe.localhost"
    frappe.init(site=site)
    frappe.connect()
    try:
        yield site
    finally:
        frappe.destroy()
```

- [ ] **Step 3: Create the driver**

```python
# tests/v2_certification/scheduler_driver.py
"""Force-trigger every Scheduled Job Type and record the Conductor Job outcome.

Usage (under bench):
    bench --site frappe.localhost execute conductor.tests.v2_certification.scheduler_driver.run_all
or, programmatically from a pytest:
    from tests.v2_certification.scheduler_driver import run_all
    results = run_all()

Output:
    A list of result dicts, one per Scheduled Job Type row, with keys:
        id, method, frequency, conductor_job_id, status, attempts,
        duration_ms, error, notes.
    Also serializes the list to docs/roadmap/v2-certification/scheduled-jobs.json.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import frappe

OUTPUT_PATH = Path(
    "/Users/osamamuhammed/frappe_15/apps/conductor/"
    "docs/roadmap/v2-certification/scheduled-jobs.json"
)

POLL_TIMEOUT_SEC = 60
POLL_INTERVAL_SEC = 0.5


def _list_scheduled_job_types() -> list[dict[str, Any]]:
    return frappe.get_all(
        "Scheduled Job Type",
        fields=["name", "method", "frequency", "stopped"],
        filters={"stopped": 0},
        order_by="method",
    )


def _newest_conductor_job_for(method: str, since_unix: float) -> dict[str, Any] | None:
    rows = frappe.get_all(
        "Conductor Job",
        fields=["name", "status", "attempts", "creation", "modified"],
        filters={"method": method},
        order_by="creation desc",
        limit=1,
    )
    if not rows:
        return None
    return rows[0]


def _wait_for_terminal(job_name: str) -> dict[str, Any]:
    deadline = time.time() + POLL_TIMEOUT_SEC
    while time.time() < deadline:
        row = frappe.db.get_value(
            "Conductor Job",
            job_name,
            ["status", "attempts", "modified"],
            as_dict=True,
        )
        if not row:
            time.sleep(POLL_INTERVAL_SEC)
            continue
        if row["status"] in ("Succeeded", "Failed", "DeadLetter"):
            return row
        time.sleep(POLL_INTERVAL_SEC)
    return frappe.db.get_value("Conductor Job", job_name, ["status", "attempts", "modified"], as_dict=True) or {}


def trigger_one(sjt: dict[str, Any]) -> dict[str, Any]:
    """Trigger a single Scheduled Job Type via Run Now."""
    method = sjt["method"]
    started = time.time()
    result: dict[str, Any] = {
        "id": sjt["name"],
        "method": method,
        "frequency": sjt["frequency"],
        "conductor_job_id": None,
        "status": None,
        "attempts": None,
        "duration_ms": None,
        "error": None,
        "notes": "",
    }
    try:
        sjt_doc = frappe.get_doc("Scheduled Job Type", sjt["name"])
        # `enqueue` on the doc dispatches via frappe.enqueue, which is now patched.
        sjt_doc.enqueue(force=True)
        frappe.db.commit()
    except Exception as exc:
        result["error"] = f"trigger raised: {exc!r}"
        return result

    job = _newest_conductor_job_for(method, since_unix=started)
    if not job:
        result["error"] = "no Conductor Job row created within trigger call"
        return result

    result["conductor_job_id"] = job["name"]
    final = _wait_for_terminal(job["name"])
    result["status"] = final.get("status")
    result["attempts"] = final.get("attempts")
    result["duration_ms"] = int((time.time() - started) * 1000)
    if result["status"] is None:
        result["error"] = f"poll timed out after {POLL_TIMEOUT_SEC}s"
    return result


def run_all() -> list[dict[str, Any]]:
    """Run every active Scheduled Job Type and write the result list."""
    rows = _list_scheduled_job_types()
    results = [trigger_one(row) for row in rows]
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(results, indent=2, default=str))
    return results
```

- [ ] **Step 4: Commit the harness scaffolding**

```bash
git add tests/v2_certification/__init__.py tests/v2_certification/conftest.py tests/v2_certification/scheduler_driver.py
git commit -m "feat(v2-cert): scheduler driver harness for M2"
```

---

## Task 10: Write tests for the driver

**Files:**
- Create: `tests/v2_certification/test_scheduler_driver.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/v2_certification/test_scheduler_driver.py
"""Tests for scheduler_driver.

These run without bench / without a real site — they patch frappe.* into
in-memory fakes. The driver's correctness is verified at the orchestration
level; full end-to-end behavior is exercised by `run_all` in M2.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests.v2_certification import scheduler_driver as sd


def test_list_scheduled_job_types_filters_stopped():
    """Only non-stopped rows are returned."""
    fake_frappe = MagicMock()
    fake_frappe.get_all.return_value = [{"name": "a", "method": "m", "frequency": "Daily", "stopped": 0}]
    with patch.object(sd, "frappe", fake_frappe):
        rows = sd._list_scheduled_job_types()
    fake_frappe.get_all.assert_called_once_with(
        "Scheduled Job Type",
        fields=["name", "method", "frequency", "stopped"],
        filters={"stopped": 0},
        order_by="method",
    )
    assert rows == [{"name": "a", "method": "m", "frequency": "Daily", "stopped": 0}]


def test_trigger_one_records_conductor_job_id_when_dispatched():
    fake_frappe = MagicMock()
    fake_frappe.get_doc.return_value = MagicMock()
    fake_frappe.get_all.return_value = [{
        "name": "CND-JOB-1", "status": "Queued", "attempts": 0,
        "creation": "2026-04-30", "modified": "2026-04-30",
    }]
    fake_frappe.db.get_value.return_value = {"status": "Succeeded", "attempts": 1, "modified": "2026-04-30"}
    sjt = {"name": "x", "method": "x.run", "frequency": "Daily"}
    with patch.object(sd, "frappe", fake_frappe):
        result = sd.trigger_one(sjt)
    assert result["conductor_job_id"] == "CND-JOB-1"
    assert result["status"] == "Succeeded"
    assert result["attempts"] == 1
    assert result["error"] is None


def test_trigger_one_reports_error_when_no_conductor_job_appears():
    fake_frappe = MagicMock()
    fake_frappe.get_doc.return_value = MagicMock()
    fake_frappe.get_all.return_value = []
    sjt = {"name": "x", "method": "x.run", "frequency": "Daily"}
    with patch.object(sd, "frappe", fake_frappe):
        result = sd.trigger_one(sjt)
    assert result["conductor_job_id"] is None
    assert "no Conductor Job row" in (result["error"] or "")


def test_trigger_one_reports_error_when_dispatch_raises():
    fake_frappe = MagicMock()
    fake_frappe.get_doc.side_effect = RuntimeError("kaboom")
    sjt = {"name": "x", "method": "x.run", "frequency": "Daily"}
    with patch.object(sd, "frappe", fake_frappe):
        result = sd.trigger_one(sjt)
    assert result["error"] is not None
    assert "kaboom" in result["error"]


def test_run_all_writes_output_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "OUTPUT_PATH", tmp_path / "out.json")
    fake_frappe = MagicMock()
    fake_frappe.get_all.side_effect = [
        [{"name": "a", "method": "a.run", "frequency": "Daily", "stopped": 0}],
        [{"name": "CND-1", "status": "Queued", "attempts": 0, "creation": "2026-04-30", "modified": "2026-04-30"}],
    ]
    fake_frappe.get_doc.return_value = MagicMock()
    fake_frappe.db.get_value.return_value = {"status": "Succeeded", "attempts": 1, "modified": "2026-04-30"}
    with patch.object(sd, "frappe", fake_frappe):
        results = sd.run_all()
    assert len(results) == 1
    assert (tmp_path / "out.json").exists()
```

- [ ] **Step 2: Run the tests**

```bash
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/v2_certification/test_scheduler_driver.py -v
```

Expected: 5 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/v2_certification/test_scheduler_driver.py
git commit -m "test(v2-cert): scheduler driver unit tests"
```

---

## Task 11: Run the campaign — force-trigger all 105 scheduled jobs

**Files:**
- Modify: `docs/roadmap/v2-certification/scheduled-jobs.md` (will be created by the run)

- [ ] **Step 1: Confirm conductor processes are still running**

```bash
ps aux | grep -E "conductor (worker|scheduler)" | grep -v grep
```

Expected: both processes alive. If not, restart `bench start`.

- [ ] **Step 2: Run the driver**

```bash
cd /Users/osamamuhammed/frappe_15
bench --site frappe.localhost execute tests.v2_certification.scheduler_driver.run_all
```

(If `bench execute` cannot resolve the dotted path because `tests/` is outside the conductor app, run it via console instead:)

```bash
bench --site frappe.localhost console <<'PY'
import sys
sys.path.insert(0, "/Users/osamamuhammed/frappe_15/apps/conductor")
from tests.v2_certification.scheduler_driver import run_all
results = run_all()
print(f"completed {len(results)} rows")
print(f"failures: {sum(1 for r in results if r['error'])}")
PY
```

Expected: prints "completed 105 rows" (or whatever the actual row count is — it may differ slightly from the CSV if HRMS adds/removes rows on install). Output JSON is written to `docs/roadmap/v2-certification/scheduled-jobs.json`.

- [ ] **Step 3: Render the matrix to markdown**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
python3 <<'PY'
import json
from pathlib import Path

src = Path("docs/roadmap/v2-certification/scheduled-jobs.json")
dst = Path("docs/roadmap/v2-certification/scheduled-jobs.md")
results = json.loads(src.read_text())

lines = []
lines.append("# M2 — Scheduled Job Type certification matrix\n")
lines.append("Generated by `tests/v2_certification/scheduler_driver.py::run_all` after the M1 patch is live.\n")
lines.append("**Pass rule:** `status == \"Succeeded\"` AND `conductor_job_id` is set.\n")
lines.append("")
total = len(results)
passed = sum(1 for r in results if r.get("status") == "Succeeded" and r.get("conductor_job_id"))
lines.append(f"**Summary:** {passed}/{total} pass ({passed/total*100:.1f}%).\n")
lines.append("")
lines.append("| # | Method | Frequency | Conductor Job | Status | Attempts | ms | Notes |")
lines.append("|---|---|---|---|---|---|---|---|")
for i, r in enumerate(results, 1):
    note = r.get("error") or r.get("notes") or ""
    lines.append(
        f"| {i} | `{r['method']}` | {r['frequency']} | "
        f"{r.get('conductor_job_id') or '—'} | {r.get('status') or 'TIMEOUT'} | "
        f"{r.get('attempts') or 0} | {r.get('duration_ms') or 0} | {note} |"
    )
dst.write_text("\n".join(lines))
print(f"wrote {dst}")
PY
```

- [ ] **Step 4: Triage**

Open `scheduled-jobs.md`. For every row with status not equal to `Succeeded`:

1. Read the `Notes` column.
2. Check the matching `Conductor Job Run` rows in MariaDB for the traceback:

   ```bash
   bench --site frappe.localhost mariadb -e "
   SELECT name, status, traceback FROM \`tabConductor Job Run\`
   WHERE parent = '<conductor_job_id>' ORDER BY creation;"
   ```

3. Edit the `Notes` column with one of:
   - `bug: <short description>` — to be fixed in M7
   - `fixture-dependent: <what's missing>` — needs HR data the local site lacks
   - `frappe-bug: <short>` — issue in upstream Frappe code, out of scope
   - `documented-limitation: <short>` — not in scope to fix in v2

- [ ] **Step 5: Commit the matrix**

```bash
git add docs/roadmap/v2-certification/scheduled-jobs.md docs/roadmap/v2-certification/scheduled-jobs.json
git commit -m "cert(M2): force-trigger 105 scheduled jobs + initial triage"
```

---

## Task 12: Build the CLI exerciser

**Files:**
- Create: `tests/v2_certification/cli_runner.py`

- [ ] **Step 1: Write the runner**

```python
# tests/v2_certification/cli_runner.py
"""Exercise every `bench conductor` subcommand and record observed output.

This is a fixture-driven harness: scenarios is a list of (label, args, expectation),
where args is appended to `bench --site frappe.localhost conductor`. expectation
is a dict with optional 'exit', 'stdout_contains', 'stderr_contains'.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

BENCH_DIR = "/Users/osamamuhammed/frappe_15"
SITE = "frappe.localhost"
OUTPUT = Path(
    "/Users/osamamuhammed/frappe_15/apps/conductor/"
    "docs/roadmap/v2-certification/cli.json"
)

SCENARIOS: list[dict[str, Any]] = [
    {
        "label": "doctor",
        "args": ["doctor"],
        "expect": {"exit": 0, "stdout_contains": ["OK"]},
    },
    {
        "label": "doctor --demo",
        "args": ["doctor", "--demo"],
        "expect": {"exit": 0, "stdout_contains": ["demo"]},
    },
    {
        "label": "depth",
        "args": ["depth"],
        "expect": {"exit": 0},
    },
    {
        "label": "schedule list",
        "args": ["schedule", "list"],
        "expect": {"exit": 0},
    },
    {
        "label": "dlq list",
        "args": ["dlq", "list"],
        "expect": {"exit": 0},
    },
    {
        "label": "workflow list",
        "args": ["workflow", "list"],
        "expect": {"exit": 0},
    },
    {
        "label": "migrate-from-rq dry-run",
        "args": ["migrate-from-rq", "--site", SITE],
        "expect": {"exit": 0, "stdout_contains": ["plan rows"]},
    },
    # `worker` and `scheduler` are long-lived; we skip them here — the live
    # processes from M1 already exercise both surfaces.
    # `cancel` and `schedule run-now` are exercised in scenario expansions
    # below using ids captured from the running site.
]


def _run(label: str, args: list[str]) -> dict[str, Any]:
    cmd = ["bench", "--site", SITE, "conductor", *args]
    proc = subprocess.run(
        cmd, cwd=BENCH_DIR, capture_output=True, text=True, timeout=120,
    )
    return {
        "label": label,
        "argv": cmd,
        "exit": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _evaluate(observed: dict[str, Any], expected: dict[str, Any]) -> tuple[bool, str]:
    if "exit" in expected and observed["exit"] != expected["exit"]:
        return False, f"exit {observed['exit']} != {expected['exit']}"
    for fragment in expected.get("stdout_contains", []):
        if fragment.lower() not in (observed["stdout"] or "").lower():
            return False, f"stdout missing {fragment!r}"
    for fragment in expected.get("stderr_contains", []):
        if fragment.lower() not in (observed["stderr"] or "").lower():
            return False, f"stderr missing {fragment!r}"
    return True, ""


def run_all() -> list[dict[str, Any]]:
    results = []
    for sc in SCENARIOS:
        run = _run(sc["label"], sc["args"])
        ok, why = _evaluate(run, sc["expect"])
        run["pass"] = ok
        run["fail_reason"] = why
        results.append(run)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(results, indent=2, default=str))
    return results


if __name__ == "__main__":
    import sys
    res = run_all()
    failed = [r for r in res if not r["pass"]]
    print(f"{len(res)} scenarios, {len(failed)} failed")
    sys.exit(1 if failed else 0)
```

- [ ] **Step 2: Test it on a small subset (smoke)**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
python3 tests/v2_certification/cli_runner.py
```

Expected: prints "<N> scenarios, 0 failed". If failures appear, treat them as M3 findings — they go into the `cli.md` matrix. Do not edit `cli_runner.py` to silence them.

- [ ] **Step 3: Commit**

```bash
git add tests/v2_certification/cli_runner.py
git commit -m "feat(v2-cert): CLI runner harness for M3"
```

---

## Task 13: Run the CLI campaign and render the matrix

**Files:**
- Create: `docs/roadmap/v2-certification/cli.md`

- [ ] **Step 1: Run the harness**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
python3 tests/v2_certification/cli_runner.py
```

Output JSON lands at `docs/roadmap/v2-certification/cli.json`.

- [ ] **Step 2: Render to markdown**

```bash
python3 <<'PY'
import json
from pathlib import Path

src = Path("docs/roadmap/v2-certification/cli.json")
dst = Path("docs/roadmap/v2-certification/cli.md")
results = json.loads(src.read_text())

lines = ["# M3 — CLI surface certification matrix\n"]
total = len(results)
passed = sum(1 for r in results if r["pass"])
lines.append(f"**Summary:** {passed}/{total} pass.\n")
lines.append("")
lines.append("| Label | Argv | Exit | Pass | Fail reason |")
lines.append("|---|---|---|---|---|")
for r in results:
    argv = " ".join(r["argv"])
    lines.append(f"| {r['label']} | `{argv}` | {r['exit']} | {'✓' if r['pass'] else '✗'} | {r.get('fail_reason') or ''} |")
dst.write_text("\n".join(lines))
print(f"wrote {dst}")
PY
```

- [ ] **Step 3: Manually exercise the long-lived commands**

`worker` and `scheduler` are already running from M1. Append a manual check section to `cli.md`:

```markdown
## Long-lived commands (manual verification)

| Command | Procfile entry | PID at check time | Status |
|---|---|---|---|
| `bench conductor worker --queue default --concurrency 4` | `conductor_worker:` | <pid from `ps aux | grep conductor_worker`> | Running |
| `bench conductor scheduler` | `conductor_scheduler:` | <pid> | Running |
```

- [ ] **Step 4: Exercise `cancel` and `schedule run-now` interactively**

Pick a queued job from the live site, cancel it, watch the row flip to `Cancelled`. Document in `cli.md`:

```bash
bench --site frappe.localhost conductor cancel <conductor_job_id>
```

For `schedule run-now`, pick a Conductor Schedule row (or create one with `bench execute conductor.demo.seed_demo_schedule` if `demo.py` ships one):

```bash
bench --site frappe.localhost conductor schedule run-now <schedule_name>
```

Append observed outcomes to `cli.md` under "Interactive commands."

- [ ] **Step 5: Commit**

```bash
git add docs/roadmap/v2-certification/cli.md docs/roadmap/v2-certification/cli.json
git commit -m "cert(M3): CLI surface matrix populated"
```

---

## Task 14: Catalog the dashboard scenarios

**Files:**
- Create: `tests/v2_certification/dashboard_scenarios.md`

The `expect` MCP runs Playwright. We don't write code here — we write a checklist that an executing agent (or the user) walks through, marking pass/fail. This separates "what to check" from "how the browser does it."

- [ ] **Step 1: Write the scenario catalog**

```markdown
# v2-cert M4 — Dashboard scenario catalog

Each scenario is a single `expect` MCP run. Use the Playwright tool to execute the
steps; capture a screenshot at the end of each scenario; record pass/fail in
`dashboard.md` (Task 15).

Open URL for every scenario: `http://localhost:8000/conductor-dashboard`
Login as Administrator before the first scenario; subsequent scenarios reuse the session.

For every scenario, run it twice — once in light mode, once in dark mode — using the ModeToggle in the header.

## Overview page

1. **Loads with stats.** Open `/conductor-dashboard`. Expect 4 NumberCards (queue depth, workers, DLQ pending, schedules) + 2 QueueChart cards visible. Screenshot.
2. **NumberCard click navigates.** Click "Workers" card. Expect navigation to `/workers`. Screenshot.
3. **Live queue depths refresh.** Trigger `bench conductor doctor --demo` from terminal; watch QueueChart update within 5s. Screenshot before + after.

## Live Feed page

4. **Stream renders rows.** Navigate to `/feed`. Trigger `bench conductor doctor --demo`. Expect new event Cards to appear in the ScrollArea. Screenshot.
5. **Pause toggle freezes feed.** Click the Pause Switch. Trigger another demo job. Expect no new rows. Click Resume — backlog flushes. Screenshot.

## Jobs page

6. **DataTable renders + sorts.** Navigate to `/jobs`. Click "Created" header. Expect rows reorder. Screenshot.
7. **Faceted status filter.** Click status filter, select "Succeeded". Expect only succeeded rows visible. Screenshot.
8. **Pagination.** Click next-page. Expect rows change. Click prev-page. Screenshot both.
9. **Detail tabs render.** Click any row. Expect Sheet/Card detail with tabs (Overview / Runs / Args). Click each tab. Screenshot.
10. **Retry button works.** Pick a Failed row. Click Retry. Confirm in dialog. Expect new attempt row in Runs tab. Screenshot.
11. **Cancel button works.** Pick a Queued/Running row. Click Cancel. Confirm. Expect status flip. Screenshot.

## DLQ page

12. **DataTable renders.** Navigate to `/dlq`. Screenshot.
13. **Bulk-select + bulk-retry.** Check 3 rows. Click "Retry selected" in sticky action bar. Confirm. Expect rows leave DLQ. Screenshot.
14. **Edit-and-retry dialog.** Click Edit on a row. Modify args JSON. Click Retry. Expect new Conductor Job. Screenshot.
15. **Discard works.** Check 1 row. Click Discard. Confirm. Expect row removed. Screenshot.

## Schedules page

16. **Table renders + Switch toggles.** Navigate to `/schedules`. Click Switch on any enabled row → disabled. Toggle back. Screenshot.
17. **Run Now dispatches.** Click Run Now. Expect new Conductor Job in /jobs. Screenshot before + after.
18. **Detail Sheet opens.** Click row. Expect right-side Sheet with last dispatch + next 10 fires + calendar. Screenshot.

## Workers page

19. **Table renders with heartbeat sort.** Navigate to `/workers`. Expect rows sorted by last heartbeat. Screenshot.
20. **Tooltip shows exact ISO time.** Hover any heartbeat cell. Expect Tooltip with ISO timestamp. Screenshot.

## Workflows page

21. **Definitions card grid renders.** Navigate to `/workflows`. Screenshot.
22. **Recent runs table renders.** Same page. Screenshot.
23. **Click row → run detail.** Click any run. Expect navigation to detail page with Mermaid DAG + step Table. Screenshot.

## Workflow run detail

24. **Mermaid renders.** On a workflow detail page. Expect SVG DAG visible. Screenshot.
25. **Step table renders + JsonViewer expands.** Click any step. Expect args/output JsonViewer. Screenshot.

## Theme + responsiveness

26. **Light/dark toggle persists.** Set dark mode. Reload. Expect dark restored. Switch to light. Reload. Expect light restored.
27. **Sidebar collapse.** Resize viewport to ~700px. Expect sidebar collapses to icon-only. Screenshot.
```

- [ ] **Step 2: Commit the catalog**

```bash
git add tests/v2_certification/dashboard_scenarios.md
git commit -m "docs(v2-cert): dashboard scenario catalog for M4"
```

---

## Task 15: Run the dashboard campaign via `expect` MCP

**Files:**
- Create: `docs/roadmap/v2-certification/dashboard.md`
- Create: `docs/roadmap/v2-certification/screenshots/M4-*.png` (multiple)

This task is operational — driven by the executing agent (or user) using the `expect` MCP browser tools. Each scenario from Task 14 is one Playwright run.

- [ ] **Step 1: Open `expect` and load the dashboard**

```
mcp__expect__open(url="http://localhost:8000/conductor-dashboard")
```

If a login screen appears, sign in as Administrator (use the bench `set-admin-password` value).

- [ ] **Step 2: Run each of the 27 scenarios from `dashboard_scenarios.md`**

For every scenario:
1. Navigate / interact with `mcp__expect__playwright`.
2. Capture with `mcp__expect__screenshot` to `docs/roadmap/v2-certification/screenshots/M4-<NN>-<theme>.png`.
3. If the scenario succeeds, record `pass=true`. If it fails, record `pass=false` with the observed deviation.
4. Repeat for the other theme (light/dark) — that's two runs per scenario.

- [ ] **Step 3: Build the matrix as you go**

Maintain `docs/roadmap/v2-certification/dashboard.md` with this header and one row per (scenario × theme):

```markdown
# M4 — Dashboard surface certification matrix

| # | Scenario | Theme | Expected | Observed | Screenshot | Pass |
|---|---|---|---|---|---|---|
| 1 | Overview loads with stats | dark | 4 NumberCards + 2 charts visible | <observed> | M4-01-dark.png | ✓ |
| 1 | Overview loads with stats | light | same | <observed> | M4-01-light.png | ✓ |
| ... | ... | ... | ... | ... | ... | ... |
```

- [ ] **Step 4: Close the browser session**

```
mcp__expect__close()
```

- [ ] **Step 5: Commit the matrix + screenshots**

```bash
git add docs/roadmap/v2-certification/dashboard.md docs/roadmap/v2-certification/screenshots/
git commit -m "cert(M4): dashboard surface matrix + screenshots"
```

---

## Task 16: Multi-worker concurrency exercise

**Files:**
- Create: `docs/roadmap/v2-certification/multi-worker.md`

- [ ] **Step 1: Set up an extra worker temporarily**

Add a second worker line to `/Users/osamamuhammed/frappe_15/Procfile` — for the duration of M5 only:

```
conductor_worker_2: OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES NO_PROXY=* bench --site frappe.localhost conductor worker --queue default --concurrency 4 1>> logs/conductor_worker_2.log 2>> logs/conductor_worker_2.error.log
```

Restart `bench start`. Confirm two worker processes:

```bash
ps aux | grep "conductor worker" | grep -v grep | wc -l
```

Expected: 2.

- [ ] **Step 2: Drive load**

```bash
bench --site frappe.localhost console <<'PY'
import conductor
for i in range(200):
    conductor.enqueue("conductor.demo.noop_job", idempotency_key=f"m5-{i}")
PY
```

(If `conductor.demo` does not export `noop_job`, use whatever zero-arg demo callable already exists — check `conductor/demo.py`.)

Watch the dashboard's queue depth fall and worker activity climb.

- [ ] **Step 3: Verify inflight cap**

In a separate console, set `Conductor Queue.default.max_concurrent = 2` via Desk. Re-run the 200-job drive. Verify only 2 jobs run at a time across both workers (the cap is per-queue, not per-worker).

```bash
bench --site frappe.localhost mariadb -e "
SELECT status, COUNT(*) FROM \`tabConductor Job\`
WHERE creation > DATE_SUB(NOW(), INTERVAL 2 MINUTE)
GROUP BY status;"
```

Expected: `Running` count ≤ 2 at any sample time.

- [ ] **Step 4: Reset cap and run reclaim test**

Set `max_concurrent` back to a high number. Drive 50 long-running jobs (`conductor.demo.sleep_job(seconds=30)` if it exists; otherwise inline an enqueue with a sleep payload).

While jobs are running, kill ONE worker:

```bash
ps aux | grep "conductor worker" | grep -v grep
kill -9 <one of the PIDs>
```

Watch the surviving worker reclaim the in-flight messages via `XAUTOCLAIM`. Confirm in the matrix that no jobs are lost.

```bash
bench --site frappe.localhost mariadb -e "
SELECT status, COUNT(*) FROM \`tabConductor Job\`
WHERE creation > DATE_SUB(NOW(), INTERVAL 5 MINUTE)
GROUP BY status;"
```

Expected: `Succeeded + Failed + Running + Queued` totals 50. No jobs `Lost`.

- [ ] **Step 5: Write `multi-worker.md`**

```markdown
# M5 — Multi-worker certification

## Setup
- Workers: `conductor_worker`, `conductor_worker_2` (both `--queue default --concurrency 4`)
- Site: `frappe.localhost`

## Concurrency cap test
- `Conductor Queue.default.max_concurrent = 2`
- Drove 200 jobs.
- Sampled `Running` count every 5s for 60s.
- Max observed `Running`: <N>
- Expected: ≤ 2.
- Pass: <yes/no>

## Rate limit test
- `Conductor Queue.default.max_rps = 10`
- Drove 200 jobs.
- Observed dispatch rate: <jobs/sec from row creation timestamps>
- Expected: ≤ 10/s sustained.
- Pass: <yes/no>

## Reclaim test (SIGKILL during run)
- Drove 50 long-running jobs.
- Killed worker PID <N> mid-flight.
- Surviving worker reclaim observed at: <timestamp>
- Final tally: <succeeded>/<failed>/<running>/<queued> = <total>
- Expected: total == 50; no jobs lost.
- Pass: <yes/no>

## Findings
- <bug 1 if any>
- <bug 2 if any>
```

- [ ] **Step 6: Tear down the second worker**

Remove `conductor_worker_2:` from the Procfile (it was M5-only). Restart bench.

```bash
ps aux | grep "conductor worker" | grep -v grep | wc -l
```

Expected: 1.

- [ ] **Step 7: Commit**

```bash
git add docs/roadmap/v2-certification/multi-worker.md
git commit -m "cert(M5): multi-worker concurrency + reclaim findings"
```

---

## Task 17: Close the soak window (M6)

**Files:**
- Create: `docs/roadmap/v2-certification/soak.md`
- Modify: `docs/roadmap/v2-certification/scheduled-jobs.md` (set `soak_observed` per row)

This task runs on Day 7 — that is, 7 calendar days after Task 7 set `conductor_intercept_frappe_enqueue: true`.

- [ ] **Step 1: Verify the patch was active for the full window**

```bash
grep -h "patch_installed" /Users/osamamuhammed/frappe_15/logs/conductor_*.log 2>/dev/null | head -5
ls -la /Users/osamamuhammed/frappe_15/logs/conductor_worker.log
ls -la /Users/osamamuhammed/frappe_15/logs/conductor_scheduler.log
```

Confirm logs span the full 7 days. If there are gaps (machine sleep, restarts), document them in `soak.md`.

- [ ] **Step 2: Query natural-cron coverage per scheduled job**

```bash
bench --site frappe.localhost mariadb -e "
SELECT method, COUNT(*) AS runs, MIN(creation) AS first_run, MAX(creation) AS last_run
FROM \`tabConductor Job\`
WHERE source = 'frappe-scheduler'  -- filter inserted by the patch (verify the actual marker)
   OR creation > DATE_SUB(NOW(), INTERVAL 7 DAY)
GROUP BY method
ORDER BY runs DESC;" > /tmp/v2-soak-counts.txt
```

(The exact filter depends on whether the patch sets a `source` field on the Conductor Job row. If it does not, use creation-time only and trust that no other producer ran during the window.)

- [ ] **Step 3: Update `scheduled-jobs.md` with soak coverage**

For each row, set the `Notes` column suffix:

- `soak: Y (N runs in 7d)` — naturally fired ≥ 1× during soak
- `soak: N` — only force-triggered, never fired naturally (typically Weekly/Monthly rows)

Daily and Hourly rows MUST have `soak: Y` for v2 DoD; if any are `soak: N`, raise a finding.

- [ ] **Step 4: Write `soak.md`**

```markdown
# M6 — Soak observations

## Window
- Start: <ISO datetime from Task 7 setup>
- End:   <ISO datetime now>
- Duration: <hours>
- Interruptions: <list any laptop sleeps, bench restarts, Redis restarts>

## Coverage by frequency

| Frequency | Rows expected to fire ≥1× | Rows that did | Pass |
|---|---|---|---|
| Hourly       | <count> | <count> | <yes/no> |
| Hourly Long  | <count> | <count> | <yes/no> |
| Daily        | <count> | <count> | <yes/no> |
| Daily Long   | <count> | <count> | <yes/no> |
| Daily Maintenance | <count> | <count> | <yes/no> |
| Hourly Maintenance | <count> | <count> | <yes/no> |
| Cron         | <count> | <count> | <yes/no> |
| All          | <count> | <count> | <yes/no> |

Weekly and Monthly rows are not expected to fire during a 7-day soak; they remain force-trigger-only for v2.

## Top 10 most-fired methods
<paste from /tmp/v2-soak-counts.txt>

## Findings
- <issue 1>
- <issue 2>
```

- [ ] **Step 5: Commit**

```bash
git add docs/roadmap/v2-certification/soak.md docs/roadmap/v2-certification/scheduled-jobs.md
git commit -m "cert(M6): soak window closes; natural-cron coverage recorded"
```

---

## Task 18: Final M1–M6 sanity pass + close-out

**Files:** none new

- [ ] **Step 1: Run the full pytest suite to confirm no regression**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor
/Users/osamamuhammed/frappe_15/env/bin/pytest tests -x --ignore=tests/comparative --ignore=tests/benchmarks
```

Expected: all tests pass (including the new `test_frappe_compat_inprocess.py` and `tests/v2_certification/test_scheduler_driver.py`).

- [ ] **Step 2: Diff against `develop`**

```bash
git fetch origin develop
git log --oneline origin/develop..HEAD
git diff --stat origin/develop..HEAD
```

Sanity check: every commit on `v2/certification` should be either a `feat(...)`, `test(...)`, `docs(...)`, or `cert(...)` commit.

- [ ] **Step 3: Verify the v2 deliverables checklist (M1–M6 portion only)**

Open `docs/roadmap/v2.md` and confirm these checkbox items are now demonstrably done (mark them `[x]`):

- [ ] `conductor/frappe_compat.py` extended with in-process `frappe.enqueue` patch + activation flag + unit tests
- [ ] `docs/roadmap/v2-certification/scheduled-jobs.md` — 105 rows, all triaged
- [ ] `docs/roadmap/v2-certification/cli.md` — every subcommand triaged
- [ ] `docs/roadmap/v2-certification/dashboard.md` — every control triaged

The remaining boxes (`Procfile.conductor`, `add_to_apps_screen`, `doctor` health-gate, KPI re-run, tag) belong to the M7+ plans.

- [ ] **Step 4: Commit the checkbox flips**

```bash
git add docs/roadmap/v2.md
git commit -m "cert: M1-M6 deliverables marked complete"
```

- [ ] **Step 5: Hand off**

Stop here. Plan 2 (`docs/superpowers/plans/<later-date>-conductor-v2-fix-backlog.md`) is written *now* — informed by the actual findings produced by Tasks 11, 13, 15, 16, and 17. Before starting it, re-invoke the `writing-plans` skill with the matrices in hand.

---

## Self-review

Spec coverage check:
- v2.md M1 → Tasks 1–8.
- v2.md M2 → Tasks 9–11.
- v2.md M3 → Tasks 12–13.
- v2.md M4 → Tasks 14–15.
- v2.md M5 → Task 16.
- v2.md M6 → Task 17.
- v2.md M7 → out of scope (separate plan, written after Task 17 produces findings).
- v2.md M8 → out of scope (separate plan).
- v2.md M9 → out of scope (separate plan).

Placeholder scan: every code step shows the exact code; every command step shows the exact argv; every matrix step shows the exact rendering script.

Type consistency: `_PATCH_MARKER` and `_ORIGINAL_ATTR` defined in Task 3, referenced unchanged in Tasks 4 (bootstrap test) and 7 (smoke test).

Risk re-check from v2.md:
- Shim-coverage risk → addressed by the design of `_site_has_conductor()` falling back gracefully (Task 3).
- Patch fragility → addressed by Task 2's idempotency + uninstall tests and Task 8's smoke before going wide.
- Bug-volume → built into M2 triage (Task 11 step 4) which buckets findings into M7 vs documented limitation.
- HRMS fixture dependence → handled in M2 triage as one of the bucket categories.
