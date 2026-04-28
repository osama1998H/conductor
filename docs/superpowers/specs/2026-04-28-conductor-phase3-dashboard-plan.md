# Phase 3 — Conductor Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Phase 3 Dashboard so an operator can find a failed Conductor job, see its traceback, and retry it from a browser — without SSH or `bench console`.

**Architecture:** A Vue 3 SFC SPA at `www/conductor-dashboard.html` (built from a standalone vite project at `apps/conductor/dashboard/`), driven by a single polling endpoint (`conductor.api.dashboard.get_state` every 2 s) for aggregates, plus per-job `frappe.publish_realtime` events for the open detail view. Six top-tab sections (Overview, Live Feed, Jobs, DLQ, Schedules, Workers) with a master/detail split layout (Overview + Live Feed are full-width exceptions). Two-tier permission model (System Manager + existing Conductor Operator).

**Tech Stack:**
- Backend: Frappe 15.106.0, Python 3.10+, Redis (existing topology)
- Frontend: Vue 3.5, Vue Router 4, frappe-ui 0.1.105, vite 5.4 (HRMS roster precedent)
- Tests: pytest (`tests/`), pytest chaos (`tests_chaos/`)

**Spec:** [`docs/superpowers/specs/2026-04-28-conductor-phase3-dashboard-design.md`](2026-04-28-conductor-phase3-dashboard-design.md)

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `conductor/api.py` → `conductor/api/__init__.py` | Migrate | Preserve existing public re-exports (`enqueue`, `context`, `job`, `RetryPolicy`, `cancel`) when turning `api` into a package |
| `conductor/api/dashboard.py` | Create | All dashboard whitelisted endpoints (~12) and shared perm guards |
| `conductor/api/json_safety.py` | Create | `is_json_safe()` + `decode_payload()` helpers used by DLQ edit-and-retry |
| `conductor/messages.py` | Modify | Add `emit_job_event(job_id, status, **fields)` helper near top of file |
| `conductor/dispatcher.py` | Modify | Replace global `conductor:job_queued` broadcast at line 223 with `emit_job_event(job_id, "QUEUED", ...)` |
| `conductor/worker.py` | Modify | Add `emit_job_event` calls at `_set_job_running`, `_set_job_succeeded`, `_schedule_retry`, `_move_to_dlq`, and the FAILED-terminal path |
| `conductor/cancellation.py` | Modify | Add `emit_job_event(job_id, "CANCELLED", ...)` at the end of `cancel()` |
| `tests/test_emit_job_event.py` | Create | TDD coverage for the helper |
| `tests/test_api_dashboard.py` | Create | Coverage matrix for every dashboard endpoint × role |
| `tests/test_json_safety.py` | Create | Golden tests for the JSON-safety gate |
| `tests_chaos/test_realtime_events.py` | Create | End-to-end per-job event sequence under real worker process |
| `dashboard/` (at app root) | Create | Standalone vite project: `package.json`, `vite.config.js`, `index.html`, `src/main.js`, `src/router.js`, `src/api.js`, `src/realtime.js`, `src/App.vue`, `src/pages/*.vue`, `src/components/*.vue`, `src/stores/*.js` |
| `conductor/public/dashboard/` | Build artifact | Vite output; gitignored |
| `conductor/www/conductor-dashboard.html` | Build artifact | Copied from `dashboard/dist/index.html` after vite build |
| `package.json` (at app root) | Create | One-line `build:dashboard` script that bench's per-app build hook can pick up |
| `.gitignore` | Modify | Add `conductor/public/dashboard/`, `conductor/www/conductor-dashboard.html`, `dashboard/node_modules/`, `dashboard/dist/` |
| `docs/superpowers/specs/2026-04-27-conductor-master-design.md` | Modify | Footnotes at §4 (UI delivery refinement) + §9 (realtime event family) |
| `docs/README.md` and/or `apps/conductor/README.md` | Modify | Operator section: how to access the dashboard, what the URL is, what each section does |

**Files NOT touched:** all six dashboard DocType `.json` files (no schema changes); all worker/scheduler/dispatcher core logic beyond the additions above; OTel/Sentry wiring (deferred to Phase 4).

---

## Phase A — Pre-implementation Spikes (Tasks 1–2)

Both spikes are gates: their outcomes either confirm the plan or force its revision. Do them first.

---

### Task 1: Spike — `frappe.publish_realtime` room targeting

**Files:**
- Create: `tests/spike_publish_realtime.py` (one-off; will be deleted after the spike documents its findings)
- Modify: `docs/superpowers/specs/2026-04-28-conductor-phase3-dashboard-design.md` — append a "Spike Findings" subsection under §8.6 with the answer

**Goal:** Confirm whether `frappe.publish_realtime(event="conductor:job:abc", message=..., after_commit=True)` delivers only to clients calling `frappe.realtime.on("conductor:job:abc", ...)`, or as a site-wide broadcast that clients filter by event name.

- [ ] **Step 1: Read Frappe's publish_realtime source**

Read `/Users/osamamuhammed/frappe_15/apps/frappe/frappe/realtime.py` lines 23–100 and `/Users/osamamuhammed/frappe_15/apps/frappe/socketio.js` (or whatever socketio dispatcher file ships in 15.106.0). Note how it scopes events: by `event` name only? by `room`? by `user`? by `doctype`+`docname`?

- [ ] **Step 2: Document findings inline in the spec**

Add this under spec §8.6:

```markdown
### 8.6.1 Spike Findings (YYYY-MM-DD)

In Frappe 15.106.0, `publish_realtime`:
- (one paragraph: how the call's parameters affect socketio delivery scope)
- (one sentence: implication for this design — does the per-event-name approach work as planned, or do we need `room=` / `user=` etc.?)
```

- [ ] **Step 3: If the finding contradicts the spec, raise it**

If `publish_realtime` is broadcast-only and event-filtered on the client (worst-case), the bandwidth model still works — but the chaos test design changes. Note the change in the spec; do not change implementation tasks here.

If `publish_realtime` does not support `event=f"conductor:job:{id}"` patterns at all (extremely unlikely, but worth knowing), STOP and escalate to the human — the design needs a different shape.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-04-28-conductor-phase3-dashboard-design.md
git commit -m "docs(spec): Phase 3 §8.6 spike findings — publish_realtime targeting"
```

---

### Task 2: Spike — vite + Frappe asset pipeline integration

**Files:**
- Create: `dashboard/package.json`, `dashboard/vite.config.js`, `dashboard/index.html`, `dashboard/src/main.js`, `dashboard/src/App.vue` (minimal hello-world)
- Create: `package.json` (at app root)

**Goal:** Confirm `vite build` produces an asset bundle that Frappe serves correctly at `/conductor-dashboard`. No router, no real components — just `<h1>Conductor Dashboard</h1>` rendered from a Vue 3 SFC.

- [ ] **Step 1: Create `dashboard/package.json`**

```json
{
  "name": "conductor-dashboard",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build --base=/assets/conductor/dashboard/ && yarn copy-html-entry",
    "copy-html-entry": "cp ../conductor/public/dashboard/index.html ../conductor/www/conductor-dashboard.html"
  },
  "dependencies": {
    "@vitejs/plugin-vue": "^4.4.0",
    "frappe-ui": "0.1.105",
    "vite": "^5.4.10",
    "vue": "^3.5.12",
    "vue-router": "^4.3.2"
  }
}
```

- [ ] **Step 2: Create `dashboard/vite.config.js`** (copy of HRMS roster, paths adapted)

```js
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import path from "path";

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  build: {
    outDir: "../conductor/public/dashboard",
    emptyOutDir: true,
    target: "es2015",
  },
});
```

- [ ] **Step 3: Create `dashboard/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <title>Conductor</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
```

- [ ] **Step 4: Create `dashboard/src/main.js`**

```js
import { createApp } from "vue";
import App from "./App.vue";

createApp(App).mount("#app");
```

- [ ] **Step 5: Create `dashboard/src/App.vue`**

```vue
<template>
  <h1>Conductor Dashboard</h1>
</template>

<script setup>
</script>
```

- [ ] **Step 6: Add app-root `package.json` for bench discovery**

```json
{
  "name": "conductor",
  "private": true,
  "scripts": {
    "build": "cd dashboard && yarn install --frozen-lockfile && yarn build"
  }
}
```

- [ ] **Step 7: Run the build**

```bash
cd dashboard && yarn install && yarn build && cd ..
```

Expected:
- `conductor/public/dashboard/` contains `index.html` + hashed JS/CSS assets.
- `conductor/www/conductor-dashboard.html` exists and references `/assets/conductor/dashboard/...`.

- [ ] **Step 8: Restart bench dev server and visit the page**

```bash
bench --site frappe.localhost browse  # or visit /conductor-dashboard manually
```

Expected: Browser loads `/conductor-dashboard`, sees `<h1>Conductor Dashboard</h1>`, no 404s on assets in DevTools network tab.

- [ ] **Step 9: If anything breaks, fix the integration before proceeding**

Common gotchas: `--base` path mismatch, `outDir` wrong, missing `emptyOutDir`, Frappe site needs `bench build` to refresh asset symlinks. Document any non-obvious fix as a comment in `dashboard/vite.config.js`.

- [ ] **Step 10: Update `.gitignore`**

```bash
cat >> .gitignore <<'EOF'
conductor/public/dashboard/
conductor/www/conductor-dashboard.html
dashboard/node_modules/
dashboard/dist/
dashboard/yarn.lock
EOF
```

(yarn.lock decision: per HRMS pattern, `roster/yarn.lock` IS committed. Reconsider — for now keep yarn.lock OUT of gitignore, remove the last line of the heredoc. Confirm with user only if they care; default to committing it.)

Final `.gitignore` additions:
```
conductor/public/dashboard/
conductor/www/conductor-dashboard.html
dashboard/node_modules/
dashboard/dist/
```

- [ ] **Step 11: Commit**

```bash
git add dashboard/ package.json .gitignore
git commit -m "feat(dashboard): vite scaffolding + hello-world Vue 3 SPA at /conductor-dashboard"
```

---

## Phase B — Server-side event emission (Tasks 3–8)

The dashboard's "open detail" realtime experience requires per-job events at every status transition. This phase wires that up before any UI lands.

---

### Task 3: Migrate `conductor/api.py` to a package

**Files:**
- Delete: `conductor/api.py`
- Create: `conductor/api/__init__.py` (verbatim contents of the old `api.py`)

**Why first:** `conductor/api/dashboard.py` will land in Task 9; the directory must exist and the existing `from conductor.api import enqueue` re-exports must keep working.

- [ ] **Step 1: Verify existing imports**

```bash
grep -rn "from conductor.api import\|from conductor import api" --include="*.py" .
```

Expected: zero or more import sites; record them mentally so the migration doesn't break them.

- [ ] **Step 2: Run baseline pytest to capture green state**

```bash
pytest tests/ -q
```

Expected: 107 passed (per Phase 2 hand-off baseline).

- [ ] **Step 3: Create the new package directory + `__init__.py`**

```bash
mkdir -p conductor/api
mv conductor/api.py conductor/api/__init__.py
```

(`git mv` is preferred so history follows; but if you used plain `mv`, `git add -A` will detect the rename via content similarity.)

- [ ] **Step 4: Re-run pytest**

```bash
pytest tests/ -q
```

Expected: still 107 passed. Imports keep working because Python prefers the package over the module of the same name.

- [ ] **Step 5: Commit**

```bash
git add conductor/api conductor/api.py
git commit -m "refactor(api): migrate conductor/api.py to a package (no behavior change)"
```

---

### Task 4: TDD — `emit_job_event` helper in `messages.py`

**Files:**
- Create: `tests/test_emit_job_event.py`
- Modify: `conductor/messages.py` (add helper near top, after `SCHEMA_VERSION`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_emit_job_event.py`:

```python
"""Unit tests for emit_job_event — the per-job realtime emit helper."""

from unittest.mock import patch

from conductor.messages import emit_job_event


def test_emit_event_name_is_per_job():
    with patch("frappe.publish_realtime") as mock_pub:
        emit_job_event("abc-123", "RUNNING")
    args, kwargs = mock_pub.call_args
    assert kwargs["event"] == "conductor:job:abc-123"


def test_emit_payload_carries_status_and_job_id():
    with patch("frappe.publish_realtime") as mock_pub:
        emit_job_event("abc-123", "RUNNING")
    msg = mock_pub.call_args.kwargs["message"]
    assert msg["job_id"] == "abc-123"
    assert msg["status"] == "RUNNING"


def test_emit_payload_includes_extra_fields():
    with patch("frappe.publish_realtime") as mock_pub:
        emit_job_event(
            "abc-123",
            "FAILED",
            attempt=3,
            max_attempts=3,
            queue="default",
            method="x.y.z",
            last_error_type="TimeoutError",
            last_error_message="boom",
        )
    msg = mock_pub.call_args.kwargs["message"]
    assert msg["attempt"] == 3
    assert msg["last_error_type"] == "TimeoutError"


def test_emit_payload_has_unix_ts():
    with patch("frappe.publish_realtime") as mock_pub:
        emit_job_event("abc-123", "QUEUED")
    msg = mock_pub.call_args.kwargs["message"]
    assert isinstance(msg["ts"], int)
    assert msg["ts"] > 0


def test_emit_uses_after_commit():
    with patch("frappe.publish_realtime") as mock_pub:
        emit_job_event("abc-123", "QUEUED")
    assert mock_pub.call_args.kwargs["after_commit"] is True


def test_emit_targets_doctype_and_docname():
    """Per spec §8.6.1: delivery scope is doctype/docname; event= is just a label."""
    with patch("frappe.publish_realtime") as mock_pub:
        emit_job_event("abc-123", "RUNNING")
    kwargs = mock_pub.call_args.kwargs
    assert kwargs["doctype"] == "Conductor Job"
    assert kwargs["docname"] == "abc-123"


def test_emit_does_not_include_traceback():
    """Tracebacks can be tens of KB; not in the realtime payload."""
    with patch("frappe.publish_realtime") as mock_pub:
        emit_job_event("abc-123", "FAILED", last_traceback="x" * 10_000)
    msg = mock_pub.call_args.kwargs["message"]
    assert "last_traceback" not in msg
```

- [ ] **Step 2: Run the test — confirm it fails**

```bash
pytest tests/test_emit_job_event.py -v
```

Expected: ImportError — `emit_job_event` not yet defined in `conductor.messages`.

- [ ] **Step 3: Implement `emit_job_event` in `conductor/messages.py`**

Add at the top of the file, after the imports and `SCHEMA_VERSION = 1`:

```python
import time

import frappe


# Realtime payload field allowlist — matches spec §8.3. last_traceback is
# deliberately excluded (can be tens of KB; the detail pane re-fetches
# get_job() on terminal-state transitions to load it).
_REALTIME_FIELDS = frozenset({
    "attempt",
    "max_attempts",
    "queue",
    "method",
    "last_error_type",
    "last_error_message",
    "finished_at",
    "next_run_at",
})


def emit_job_event(job_id: str, status: str, **fields) -> None:
    payload = {"job_id": job_id, "status": status, "ts": int(time.time())}
    for k, v in fields.items():
        if k in _REALTIME_FIELDS and v is not None:
            payload[k] = v
    # doctype/docname scope delivery to the per-doc Socket.IO room
    # (doc:Conductor Job/{job_id}); event= is only a label. See spec §8.6.1.
    frappe.publish_realtime(
        event=f"conductor:job:{job_id}",
        message=payload,
        doctype="Conductor Job",
        docname=job_id,
        after_commit=True,
    )
```

- [ ] **Step 4: Run the test — confirm it passes**

```bash
pytest tests/test_emit_job_event.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Run full suite to confirm no regressions**

```bash
pytest tests/ -q
```

Expected: 114 passed (107 + 7 new).

- [ ] **Step 6: Commit**

```bash
git add tests/test_emit_job_event.py conductor/messages.py
git commit -m "feat(messages): emit_job_event helper for per-job realtime events"
```

---

### Task 5: Replace global `conductor:job_queued` broadcast in dispatcher

**Files:**
- Modify: `conductor/dispatcher.py` lines 223–227

- [ ] **Step 1: Run baseline tests**

```bash
pytest tests/test_dispatcher.py -q  # if it exists; else pytest tests/ -q
```

Expected: pre-existing tests pass (baseline 113 after Task 4).

- [ ] **Step 2: Replace the publish_realtime call**

In `conductor/dispatcher.py`, find:

```python
        frappe.publish_realtime(
            "conductor:job_queued",
            {"job_id": job_id, "queue": resolved_queue, "method": method},
            after_commit=False,
        )
        log.info("job_enqueued", job_id=job_id, queue=resolved_queue, method=method)
```

Replace with:

```python
        emit_job_event(
            job_id,
            "QUEUED",
            queue=resolved_queue,
            method=method,
        )
        log.info("job_enqueued", job_id=job_id, queue=resolved_queue, method=method)
```

Add the import at the top of `dispatcher.py` (next to existing `from conductor.messages import …`):

```python
from conductor.messages import emit_job_event
```

- [ ] **Step 3: Search for any test that references the old event name**

```bash
grep -rn "conductor:job_queued" --include="*.py" .
```

Expected: zero hits after the dispatcher edit. If a test references it, update the test to the new event-name pattern (`conductor:job:<id>`).

- [ ] **Step 4: Run full suite**

```bash
pytest tests/ -q
```

Expected: still green (114 passed).

- [ ] **Step 5: Commit**

```bash
git add conductor/dispatcher.py
git commit -m "feat(dispatcher): replace global job_queued event with per-job conductor:job:{id}

BREAKING: external consumers of conductor:job_queued must subscribe to
conductor:job:{job_id} instead. Documented in Phase 3 spec §13."
```

---

### Task 6: Emit per-job events at every worker transition

**Files:**
- Modify: `conductor/worker.py` (add emits at lines ~111, ~121, ~162, ~181, and the FAILED-terminal path around 380)

- [ ] **Step 1: Add the import**

At the top of `conductor/worker.py`, alongside existing `from conductor.messages import …`:

```python
from conductor.messages import emit_job_event
```

- [ ] **Step 2: RUNNING — `_set_job_running` at line 111**

Replace:

```python
def _set_job_running(job_id: str, worker_id: str) -> None:
    frappe.db.set_value(
        "Conductor Job",
        job_id,
        {"status": "RUNNING", "started_at": _now_naive(), "worker_id": worker_id},
        update_modified=False,
    )
    frappe.db.commit()
```

With:

```python
def _set_job_running(job_id: str, worker_id: str) -> None:
    frappe.db.set_value(
        "Conductor Job",
        job_id,
        {"status": "RUNNING", "started_at": _now_naive(), "worker_id": worker_id},
        update_modified=False,
    )
    frappe.db.commit()
    emit_job_event(job_id, "RUNNING")
```

- [ ] **Step 3: SUCCEEDED — `_set_job_succeeded` at line 121**

Add `emit_job_event(job_id, "SUCCEEDED")` after `frappe.db.commit()` (mirror of step 2).

- [ ] **Step 4: SCHEDULED_RETRY — `_schedule_retry` at line 162**

After the existing commit at line 178:

```python
    frappe.db.commit()
    emit_job_event(
        msg.job_id,
        "SCHEDULED_RETRY",
        attempt=new_msg.attempt,
        max_attempts=msg.max_attempts,
        next_run_at=next_run.replace(tzinfo=None).isoformat(),
    )
```

- [ ] **Step 5: DLQ — `_move_to_dlq` at line 181**

After the existing commit at line 198:

```python
    frappe.db.commit()
    emit_job_event(
        msg.job_id,
        "DLQ",
        attempt=msg.attempt,
        max_attempts=msg.max_attempts,
        queue=msg.queue,
        method=msg.method,
        last_error_type=type(exc).__name__,
        last_error_message=str(exc)[:140],
    )
```

- [ ] **Step 6: FAILED-terminal at line 386 (the SCHEDULED_RETRY call site already emits SCHEDULED_RETRY; the terminal-FAILED case is the `_write_job_run_row(... status="FAILED" ...)` after `_move_to_dlq` near line 388–389)**

The current flow already calls `_move_to_dlq` for terminal failures, which now emits "DLQ". But the master state machine (spec §5) shows FAILED as a separate terminal state that flows into DLQ. There's no explicit `status=FAILED` write in the worker on the terminal path — `_move_to_dlq` flips the status to `DLQ` directly at line 197. So the DLQ event from step 5 covers it. **No code change needed at line 386–389.** Confirm by re-reading the relevant block.

(Tip: if a future audit shows a code path where `Conductor Job.status` becomes `FAILED` without going to DLQ — e.g., the `current_status == "CANCELLED"` branch at line 359 — that path also doesn't need a `FAILED` event because the cancellation event was already emitted in Task 7.)

- [ ] **Step 7: TIMED_OUT terminal path at line 381**

Lines 380–382 set `status=TIMED_OUT` after `_move_to_dlq`. Since `_move_to_dlq` itself emits `DLQ` at step 5, but the row's actual final status here is `TIMED_OUT`, we want to emit `TIMED_OUT` AFTER the override:

After line 382:

```python
                        emit_job_event(
                            msg.job_id,
                            "TIMED_OUT",
                            attempt=msg.attempt,
                            max_attempts=msg.max_attempts,
                            last_error_type=type(exc).__name__ if exc else "TimeoutError",
                            last_error_message=str(exc)[:140] if exc else "deadline exceeded",
                        )
```

This means a timed-out job that exhausts retries fires both `DLQ` (from `_move_to_dlq`) and `TIMED_OUT` events in quick succession. Acceptable: the SPA's last-event-wins rendering shows `TIMED_OUT`, which is the row's final status.

- [ ] **Step 8: Run tests**

```bash
pytest tests/ -q
```

Expected: 114 passed (no new tests yet; the worker has Frappe-doctype-test coverage at 32 tests but those are run via `bench run-tests`, not pytest. The worker's pytest coverage relies on existing tests still passing).

- [ ] **Step 9: Run Frappe DocType tests too**

```bash
bench --site frappe.localhost run-tests --app conductor
```

Expected: 32 passed.

- [ ] **Step 10: Commit**

```bash
git add conductor/worker.py
git commit -m "feat(worker): emit per-job realtime events at every status transition"
```

---

### Task 7: Emit CANCELLED event from `cancellation.py`

**Files:**
- Modify: `conductor/cancellation.py` (add emit at the end of `cancel()`)

- [ ] **Step 1: Add the import**

At the top of `conductor/cancellation.py` after existing imports:

```python
from conductor.messages import emit_job_event
```

- [ ] **Step 2: Add emit at the end of `cancel()`**

Replace the final two lines:

```python
    log.info("job_cancelled", job_id=job_id, prior_status=current)
    return True
```

With:

```python
    emit_job_event(job_id, "CANCELLED")
    log.info("job_cancelled", job_id=job_id, prior_status=current)
    return True
```

(Place the emit BEFORE the log line so the trace ordering matches "transition first, log second" — a small consistency win.)

- [ ] **Step 3: Run tests**

```bash
pytest tests/ -q
```

Expected: 114 passed.

- [ ] **Step 4: Commit**

```bash
git add conductor/cancellation.py
git commit -m "feat(cancellation): emit conductor:job:{id} CANCELLED event on cancel"
```

---

### Task 8: TDD — JSON-safety helper

**Files:**
- Create: `tests/test_json_safety.py`
- Create: `conductor/api/json_safety.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_json_safety.py`:

```python
"""Unit tests for is_json_safe — the gate for DLQ edit-and-retry."""

from datetime import datetime, timezone
from decimal import Decimal

from conductor.api.json_safety import is_json_safe


def test_plain_str_int_dict_is_safe():
    assert is_json_safe({"a": 1, "b": "x", "c": True, "d": None}) is True
    assert is_json_safe([1, 2, 3]) is True
    assert is_json_safe("hello") is True


def test_nested_str_int_dict_is_safe():
    assert is_json_safe({"a": [1, {"b": "x"}]}) is True


def test_datetime_is_unsafe():
    assert is_json_safe({"ts": datetime(2026, 4, 28, tzinfo=timezone.utc)}) is False


def test_decimal_is_unsafe():
    assert is_json_safe({"amount": Decimal("1.23")}) is False


def test_bytes_is_unsafe():
    assert is_json_safe({"blob": b"abc"}) is False


def test_unsafe_inside_nested_list_is_detected():
    assert is_json_safe({"a": [{"ts": datetime.now()}]}) is False


def test_custom_class_is_unsafe():
    class Foo:
        pass
    assert is_json_safe({"x": Foo()}) is False


def test_float_is_safe():
    assert is_json_safe({"x": 1.5}) is True
```

- [ ] **Step 2: Run — confirm it fails**

```bash
pytest tests/test_json_safety.py -v
```

Expected: ImportError (`conductor.api.json_safety` not found).

- [ ] **Step 3: Implement the helper**

Create `conductor/api/json_safety.py`:

```python
"""JSON-safety gate for DLQ edit-and-retry (spec §9.4).

Master §3 #17 chose msgpack over JSON because msgpack preserves types JSON
drops (datetime, Decimal, bytes). DLQ edit-and-retry exposes the payload to
operators as JSON; allowing edits on payloads containing non-JSON-native
types would silently coerce those types on save. This module gates such
payloads: they are read-only in the SPA and rejected server-side.
"""

from __future__ import annotations

from typing import Any

_SAFE_PRIMITIVE_TYPES = (str, int, float, bool, type(None))


def is_json_safe(value: Any) -> bool:
    if isinstance(value, _SAFE_PRIMITIVE_TYPES):
        return True
    if isinstance(value, list):
        return all(is_json_safe(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(k, str) and is_json_safe(v)
            for k, v in value.items()
        )
    return False
```

- [ ] **Step 4: Run — confirm it passes**

```bash
pytest tests/test_json_safety.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_json_safety.py conductor/api/json_safety.py
git commit -m "feat(api): is_json_safe helper for DLQ edit-and-retry gate"
```

---

## Phase C — Server-side dashboard API (Tasks 9–15)

Twelve whitelisted endpoints, role-gated. Build them with TDD using the coverage matrix from spec §10.1 (anonymous → 401, Operator allowed → 200, Operator denied destructive → 403, SysMgr → 200).

---

### Task 9: API skeleton + permission helpers

**Files:**
- Create: `conductor/api/dashboard.py`
- Create: `tests/test_api_dashboard.py` (skeleton; concrete tests added in subsequent tasks)

- [ ] **Step 1: Write the perm-helper tests**

Create `tests/test_api_dashboard.py` with imports + perm-helper tests:

```python
"""Unit tests for conductor.api.dashboard — whitelisted endpoints + perm guards.

Each endpoint MUST cover the matrix from spec §10.1:
  anonymous → 401, Operator allowed → 200, Operator denied destructive → 403,
  System Manager → 200.

These tests use Frappe's test fixtures + role assignment via _as_user(...).
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
import frappe

from conductor.api import dashboard


@contextmanager
def _as_roles(*roles):
    """Patch frappe.get_roles() and frappe.has_permission() to simulate the user."""
    with patch.object(frappe, "get_roles", return_value=list(roles)), \
         patch.object(frappe, "has_permission", return_value=("Conductor Operator" in roles or "System Manager" in roles)):
        yield


def test_require_read_allows_operator():
    with _as_roles("Conductor Operator"):
        dashboard._require_read()  # no raise


def test_require_read_allows_system_manager():
    with _as_roles("System Manager"):
        dashboard._require_read()


def test_require_read_rejects_anonymous():
    with _as_roles(), patch.object(frappe, "has_permission", return_value=False):
        with pytest.raises(frappe.PermissionError):
            dashboard._require_read()


def test_require_destructive_rejects_operator():
    with _as_roles("Conductor Operator"):
        with pytest.raises(frappe.PermissionError):
            dashboard._require_destructive()


def test_require_destructive_allows_system_manager():
    with _as_roles("System Manager"):
        dashboard._require_destructive()
```

- [ ] **Step 2: Run — confirm it fails**

```bash
pytest tests/test_api_dashboard.py -v
```

Expected: ImportError (`conductor.api.dashboard` not yet created).

- [ ] **Step 3: Implement the skeleton**

Create `conductor/api/dashboard.py`:

```python
"""Dashboard whitelisted API surface — Phase 3.

Reference: docs/superpowers/specs/2026-04-28-conductor-phase3-dashboard-design.md §7.

Permission model (spec §6):
  - System Manager: full access.
  - Conductor Operator: read everything + safe-mutating actions
    (retry / cancel / schedule run-now).
  - Destructive actions (DLQ discard, edit-and-retry, schedule enable/disable)
    are System-Manager-only.

The server is the source of truth for permission enforcement. The frontend
hides destructive controls for non-SysMgr users as UX polish only.
"""

from __future__ import annotations

import frappe
from frappe import _


def _require_read() -> None:
    if not (
        frappe.has_permission("Conductor Job", "read")
        or "Conductor Operator" in frappe.get_roles()
    ):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


def _require_destructive() -> None:
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("System Manager only"), frappe.PermissionError)
```

- [ ] **Step 4: Run — confirm it passes**

```bash
pytest tests/test_api_dashboard.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_api_dashboard.py conductor/api/dashboard.py
git commit -m "feat(api/dashboard): skeleton with role-gating helpers"
```

---

### Task 10: `get_state()` endpoint

**Files:**
- Modify: `conductor/api/dashboard.py`
- Modify: `tests/test_api_dashboard.py`

- [ ] **Step 1: Write tests**

Append to `tests/test_api_dashboard.py`:

```python
def _seed_jobs():
    """Insert a few Conductor Job rows for snapshot tests."""
    frappe.get_doc({
        "doctype": "Conductor Job", "name": "j1", "job_id": "j1",
        "queue": "default", "method": "x.y", "status": "SUCCEEDED",
        "enqueued_at": "2026-04-28 10:00:00",
    }).insert(ignore_permissions=True)
    frappe.get_doc({
        "doctype": "Conductor Job", "name": "j2", "job_id": "j2",
        "queue": "default", "method": "x.y", "status": "FAILED",
        "enqueued_at": "2026-04-28 10:01:00",
    }).insert(ignore_permissions=True)
    frappe.db.commit()


def test_get_state_shape(monkeypatch):
    """get_state returns the snapshot shape per spec §7.1."""
    with _as_roles("Conductor Operator"):
        # Stub Redis so tests don't need a live server.
        monkeypatch.setattr(dashboard, "_redis_queue_depth", lambda site, queue: 0)
        monkeypatch.setattr(dashboard, "_redis_scheduled_count", lambda site: 0)
        state = dashboard.get_state()
    assert "queues" in state
    assert "worker_summary" in state
    assert "dlq_summary" in state
    assert "schedule_summary" in state
    assert "feed_recent" in state
    assert "config" in state
    assert state["config"]["poll_interval_ms"] >= 500


def test_get_state_includes_recent_jobs(monkeypatch):
    _seed_jobs()
    with _as_roles("Conductor Operator"):
        monkeypatch.setattr(dashboard, "_redis_queue_depth", lambda site, queue: 0)
        monkeypatch.setattr(dashboard, "_redis_scheduled_count", lambda site: 0)
        state = dashboard.get_state()
    job_ids = {row["job_id"] for row in state["feed_recent"]}
    assert "j1" in job_ids and "j2" in job_ids


def test_get_state_rejects_anonymous(monkeypatch):
    with _as_roles(), patch.object(frappe, "has_permission", return_value=False):
        with pytest.raises(frappe.PermissionError):
            dashboard.get_state()
```

- [ ] **Step 2: Run — confirm failure**

```bash
pytest tests/test_api_dashboard.py::test_get_state_shape -v
```

Expected: AttributeError (`dashboard.get_state` not yet defined).

- [ ] **Step 3: Implement `get_state` + Redis helpers**

Append to `conductor/api/dashboard.py`:

```python
import time
from typing import Any

from conductor.client import get_redis
from conductor.config import load_config
from conductor.streams import stream_key
from conductor.scheduled import scheduled_redis_key


def _redis_queue_depth(site: str, queue: str) -> int:
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    try:
        return int(r.xlen(stream_key(site, queue)))
    except Exception:
        return 0


def _redis_scheduled_count(site: str) -> int:
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    try:
        return int(r.zcard(scheduled_redis_key(site)))
    except Exception:
        return 0


def _poll_interval_ms() -> int:
    return int(
        (frappe.local.conf.get("conductor") or {}).get(
            "dashboard_poll_interval_ms", 2000
        )
    )


@frappe.whitelist()
def get_state() -> dict[str, Any]:
    _require_read()
    site = frappe.local.site

    queues = []
    for q in frappe.get_all("Conductor Queue", fields=["name", "enabled"]):
        depth = _redis_queue_depth(site, q.name)
        dlq_count = frappe.db.count("Conductor DLQ Entry",
                                    {"queue": q.name, "status": "PENDING_REVIEW"})
        queues.append({
            "name": q.name, "enabled": bool(q.enabled),
            "depth_redis": depth, "scheduled_count": 0,  # ZSET is global, not per-queue
            "dlq_count": dlq_count,
            "throughput_1h": 0,  # filled from a SQL agg below if you want it now; v1 stub OK
            "error_rate_1h": 0.0,
        })

    worker_summary = {
        "alive": frappe.db.count("Conductor Worker", {"status": "ALIVE"}),
        "stale": frappe.db.count("Conductor Worker", {"status": "STALE"}),
        "gone": frappe.db.count("Conductor Worker", {"status": "GONE"}),
        "total": frappe.db.count("Conductor Worker"),
    }

    dlq_summary = {
        "pending_review": frappe.db.count("Conductor DLQ Entry", {"status": "PENDING_REVIEW"}),
        "retried": frappe.db.count("Conductor DLQ Entry", {"status": "RETRIED"}),
        "discarded": frappe.db.count("Conductor DLQ Entry", {"status": "DISCARDED"}),
    }

    schedule_summary = {
        "enabled_count": frappe.db.count("Conductor Schedule", {"enabled": 1}),
        "next_5": frappe.get_all(
            "Conductor Schedule",
            filters={"enabled": 1},
            fields=["name", "cron_expression", "next_run_at"],
            order_by="next_run_at asc",
            limit=5,
        ),
    }

    feed_recent = frappe.get_all(
        "Conductor Job",
        fields=["job_id", "method", "queue", "status", "attempt", "enqueued_at"],
        order_by="enqueued_at desc",
        limit=50,
    )

    return {
        "queues": queues,
        "worker_summary": worker_summary,
        "dlq_summary": dlq_summary,
        "schedule_summary": schedule_summary,
        "feed_recent": feed_recent,
        "config": {"poll_interval_ms": _poll_interval_ms()},
        "ts": int(time.time()),
    }
```

- [ ] **Step 4: Run — confirm pass**

```bash
pytest tests/test_api_dashboard.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_api_dashboard.py conductor/api/dashboard.py
git commit -m "feat(api/dashboard): get_state snapshot endpoint"
```

---

### Task 11: `get_job` + `retry_job` + `cancel_job`

**Files:**
- Modify: `conductor/api/dashboard.py`
- Modify: `tests/test_api_dashboard.py`

- [ ] **Step 1: Write tests**

Append to `tests/test_api_dashboard.py`:

```python
def test_get_job_returns_full_detail():
    frappe.get_doc({
        "doctype": "Conductor Job", "name": "jX", "job_id": "jX",
        "queue": "default", "method": "x.y", "status": "FAILED",
        "last_error_type": "ValueError", "last_error_message": "boom",
        "last_traceback": "Traceback…\n  File \"x.py\"\n",
    }).insert(ignore_permissions=True)
    frappe.db.commit()

    with _as_roles("Conductor Operator"):
        result = dashboard.get_job("jX")
    assert result["job_id"] == "jX"
    assert result["last_traceback"].startswith("Traceback")
    assert "runs" in result  # Conductor Job Run rows


def test_retry_job_requires_operator():
    with _as_roles(), patch.object(frappe, "has_permission", return_value=False):
        with pytest.raises(frappe.PermissionError):
            dashboard.retry_job("jX")


def test_retry_job_calls_enqueue(monkeypatch):
    """retry_job re-dispatches via conductor.enqueue with the original method/args."""
    captured = {}
    def fake_enqueue(method, **kwargs):
        captured["method"] = method
        captured["kwargs"] = kwargs
        return "new-job-id"
    monkeypatch.setattr(dashboard, "_enqueue_for_retry", fake_enqueue)
    with _as_roles("Conductor Operator"):
        new_id = dashboard.retry_job("jX")
    assert new_id == "new-job-id"
    assert captured["method"] == "x.y"


def test_cancel_job_calls_cancellation():
    from conductor import cancellation as cancel_mod
    with _as_roles("Conductor Operator"), \
         patch.object(cancel_mod, "cancel", return_value=True) as mock_cancel:
        result = dashboard.cancel_job("jX")
    mock_cancel.assert_called_once_with("jX")
    assert result is True
```

- [ ] **Step 2: Run — confirm failure**

```bash
pytest tests/test_api_dashboard.py -v
```

Expected: AttributeError on `dashboard.get_job`/`retry_job`/`cancel_job`.

- [ ] **Step 3: Implement endpoints**

Append to `conductor/api/dashboard.py`:

```python
from conductor import cancellation as _cancellation
from conductor.serialization import loads as _msgpack_loads


def _decode_b64_msgpack(b64: str) -> Any:
    if not b64:
        return None
    import base64
    return _msgpack_loads(base64.b64decode(b64.encode("ascii")))


@frappe.whitelist()
def get_job(job_id: str) -> dict[str, Any]:
    _require_read()
    if not frappe.db.exists("Conductor Job", job_id):
        frappe.throw(_("Job not found"), frappe.DoesNotExistError)

    job = frappe.get_doc("Conductor Job", job_id).as_dict()
    job["args_decoded"] = _decode_b64_msgpack(job.get("args"))
    job["kwargs_decoded"] = _decode_b64_msgpack(job.get("kwargs"))
    job["runs"] = frappe.get_all(
        "Conductor Job Run",
        filters={"job": job_id},
        fields=["attempt_number", "worker_id", "started_at", "finished_at",
                "duration_ms", "status", "error_type", "error_message",
                "traceback", "trace_id", "span_id", "sentry_event_id", "sentry_url"],
        order_by="attempt_number asc",
    )
    return job


def _enqueue_for_retry(method: str, **kwargs):
    """Indirection so tests can monkeypatch."""
    from conductor.dispatcher import enqueue
    return enqueue(method, **kwargs)


@frappe.whitelist()
def retry_job(job_id: str) -> str:
    _require_read()
    if not (frappe.has_permission("Conductor Job", "write")
            or "Conductor Operator" in frappe.get_roles()):
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    if not frappe.db.exists("Conductor Job", job_id):
        frappe.throw(_("Job not found"), frappe.DoesNotExistError)

    job = frappe.get_doc("Conductor Job", job_id)
    kwargs = _decode_b64_msgpack(job.kwargs) or {}
    args = _decode_b64_msgpack(job.args) or []
    return _enqueue_for_retry(
        job.method,
        queue=job.queue,
        args=args,
        kwargs=kwargs,
    )


@frappe.whitelist()
def cancel_job(job_id: str) -> bool:
    _require_read()
    if not (frappe.has_permission("Conductor Job", "write")
            or "Conductor Operator" in frappe.get_roles()):
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    return _cancellation.cancel(job_id)
```

- [ ] **Step 4: Run — confirm pass**

```bash
pytest tests/test_api_dashboard.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_api_dashboard.py conductor/api/dashboard.py
git commit -m "feat(api/dashboard): get_job + retry_job + cancel_job"
```

---

### Task 12: DLQ endpoints (`get_dlq_entry`, `dlq_retry`, `dlq_discard`, `dlq_edit_and_retry`)

**Files:**
- Modify: `conductor/api/dashboard.py`
- Modify: `tests/test_api_dashboard.py`

- [ ] **Step 1: Write tests**

```python
def _seed_dlq_entry(name="dlq1", payload_args=None, payload_kwargs=None):
    import base64, json as json_mod
    from conductor.serialization import dumps
    args_b64 = base64.b64encode(dumps(payload_args or [])).decode("ascii")
    kwargs_b64 = base64.b64encode(dumps(payload_kwargs or {})).decode("ascii")
    payload = json_mod.dumps({"args_b64": args_b64, "kwargs_b64": kwargs_b64,
                              "name": "x.y", "queue": "default"})
    frappe.get_doc({
        "doctype": "Conductor DLQ Entry", "name": name,
        "queue": "default", "status": "PENDING_REVIEW",
        "attempts": 3, "last_error_type": "ValueError",
        "last_error_message": "boom", "last_traceback": "...",
        "payload": payload,
    }).insert(ignore_permissions=True)
    frappe.db.commit()


def test_get_dlq_entry_includes_json_safety_flag():
    _seed_dlq_entry("dlq-safe", payload_kwargs={"a": 1, "b": "x"})
    with _as_roles("Conductor Operator"):
        entry = dashboard.get_dlq_entry("dlq-safe")
    assert entry["is_json_safe"] is True


def test_get_dlq_entry_unsafe_payload():
    from datetime import datetime
    _seed_dlq_entry("dlq-unsafe", payload_kwargs={"ts": datetime.now()})
    with _as_roles("Conductor Operator"):
        entry = dashboard.get_dlq_entry("dlq-unsafe")
    assert entry["is_json_safe"] is False


def test_dlq_retry_allowed_for_operator(monkeypatch):
    _seed_dlq_entry("dlq-r1")
    monkeypatch.setattr(dashboard, "_enqueue_for_retry", lambda m, **k: "new-id")
    with _as_roles("Conductor Operator"):
        result = dashboard.dlq_retry(["dlq-r1"])
    assert result["retried"] == 1
    assert frappe.db.get_value("Conductor DLQ Entry", "dlq-r1", "status") == "RETRIED"


def test_dlq_discard_rejects_operator():
    _seed_dlq_entry("dlq-d1")
    with _as_roles("Conductor Operator"):
        with pytest.raises(frappe.PermissionError):
            dashboard.dlq_discard(["dlq-d1"])


def test_dlq_discard_allowed_for_sysmgr():
    _seed_dlq_entry("dlq-d2")
    with _as_roles("System Manager"):
        result = dashboard.dlq_discard(["dlq-d2"])
    assert result["discarded"] == 1
    assert frappe.db.get_value("Conductor DLQ Entry", "dlq-d2", "status") == "DISCARDED"


def test_dlq_edit_and_retry_rejects_unsafe_payload():
    from datetime import datetime
    _seed_dlq_entry("dlq-e1", payload_kwargs={"ts": datetime.now()})
    with _as_roles("System Manager"):
        with pytest.raises(frappe.ValidationError):
            dashboard.dlq_edit_and_retry("dlq-e1", "[]", '{"a":1}')


def test_dlq_edit_and_retry_dispatches_safe_edit(monkeypatch):
    _seed_dlq_entry("dlq-e2", payload_kwargs={"a": 1})
    monkeypatch.setattr(dashboard, "_enqueue_for_retry", lambda m, **k: "new-id")
    with _as_roles("System Manager"):
        result = dashboard.dlq_edit_and_retry("dlq-e2", "[]", '{"a":99}')
    assert result == "new-id"
```

- [ ] **Step 2: Implement DLQ endpoints**

Append to `conductor/api/dashboard.py`:

```python
import json as _json

from conductor.api.json_safety import is_json_safe


def _dlq_payload_decoded(payload_str: str) -> dict[str, Any]:
    """Decode the JSON-stringified stream payload stored in the DLQ row."""
    raw = _json.loads(payload_str or "{}")
    args = _decode_b64_msgpack(raw.get("args_b64", "")) or []
    kwargs = _decode_b64_msgpack(raw.get("kwargs_b64", "")) or {}
    return {"args": args, "kwargs": kwargs, "method": raw.get("name") or raw.get("method"),
            "queue": raw.get("queue", "default")}


@frappe.whitelist()
def get_dlq_entry(name: str) -> dict[str, Any]:
    _require_read()
    if not frappe.db.exists("Conductor DLQ Entry", name):
        frappe.throw(_("DLQ entry not found"), frappe.DoesNotExistError)
    entry = frappe.get_doc("Conductor DLQ Entry", name).as_dict()
    decoded = _dlq_payload_decoded(entry.get("payload", ""))
    entry["payload_decoded"] = decoded
    entry["is_json_safe"] = is_json_safe(decoded["args"]) and is_json_safe(decoded["kwargs"])
    return entry


@frappe.whitelist()
def dlq_retry(entry_names: list[str] | str) -> dict[str, Any]:
    _require_read()
    if not (frappe.has_permission("Conductor DLQ Entry", "write")
            or "Conductor Operator" in frappe.get_roles()):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    if isinstance(entry_names, str):
        entry_names = _json.loads(entry_names)

    retried = 0
    for name in entry_names:
        entry = frappe.get_doc("Conductor DLQ Entry", name)
        decoded = _dlq_payload_decoded(entry.payload)
        _enqueue_for_retry(
            decoded["method"],
            queue=decoded["queue"],
            args=decoded["args"],
            kwargs=decoded["kwargs"],
        )
        frappe.db.set_value("Conductor DLQ Entry", name, {
            "status": "RETRIED",
            "reviewed_by": frappe.session.user,
            "reviewed_at": frappe.utils.now_datetime(),
        })
        retried += 1

    frappe.db.commit()
    return {"retried": retried}


@frappe.whitelist()
def dlq_discard(entry_names: list[str] | str) -> dict[str, Any]:
    _require_destructive()
    if isinstance(entry_names, str):
        entry_names = _json.loads(entry_names)
    discarded = 0
    for name in entry_names:
        frappe.db.set_value("Conductor DLQ Entry", name, {
            "status": "DISCARDED",
            "reviewed_by": frappe.session.user,
            "reviewed_at": frappe.utils.now_datetime(),
        })
        discarded += 1
    frappe.db.commit()
    return {"discarded": discarded}


@frappe.whitelist()
def dlq_edit_and_retry(name: str, args_json: str, kwargs_json: str) -> str:
    _require_destructive()
    entry = frappe.get_doc("Conductor DLQ Entry", name)
    decoded = _dlq_payload_decoded(entry.payload)
    if not (is_json_safe(decoded["args"]) and is_json_safe(decoded["kwargs"])):
        frappe.throw(_("Original payload contains non-JSON-native types; "
                       "edit-and-retry not available."),
                     frappe.ValidationError)

    new_args = _json.loads(args_json)
    new_kwargs = _json.loads(kwargs_json)
    if not (is_json_safe(new_args) and is_json_safe(new_kwargs)):
        frappe.throw(_("Edited payload contains non-JSON-native types"),
                     frappe.ValidationError)

    new_id = _enqueue_for_retry(
        decoded["method"],
        queue=decoded["queue"],
        args=new_args,
        kwargs=new_kwargs,
    )
    frappe.db.set_value("Conductor DLQ Entry", name, {
        "status": "RETRIED",
        "reviewed_by": frappe.session.user,
        "reviewed_at": frappe.utils.now_datetime(),
    })
    frappe.db.commit()
    return new_id
```

- [ ] **Step 3: Run — confirm pass**

```bash
pytest tests/test_api_dashboard.py -v
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_api_dashboard.py conductor/api/dashboard.py
git commit -m "feat(api/dashboard): DLQ endpoints with JSON-safety gating"
```

---

### Task 13: Schedule endpoints

**Files:**
- Modify: `conductor/api/dashboard.py`
- Modify: `tests/test_api_dashboard.py`

- [ ] **Step 1: Write tests**

```python
def _seed_schedule(name="sch1", enabled=1, cron="0 8 * * *"):
    frappe.get_doc({
        "doctype": "Conductor Schedule", "name": name,
        "cron_expression": cron, "timezone": "UTC",
        "method": "x.y", "queue": "default",
        "enabled": enabled,
    }).insert(ignore_permissions=True)
    frappe.db.commit()


def test_schedule_run_now_allowed_for_operator():
    _seed_schedule("sch-run")
    with _as_roles("Conductor Operator"), \
         patch.object(dashboard, "_enqueue_for_retry", return_value="job-id"):
        result = dashboard.schedule_run_now("sch-run")
    assert result == "job-id"


def test_schedule_set_enabled_rejects_operator():
    _seed_schedule("sch-en1")
    with _as_roles("Conductor Operator"):
        with pytest.raises(frappe.PermissionError):
            dashboard.schedule_set_enabled("sch-en1", False)


def test_schedule_set_enabled_allowed_for_sysmgr():
    _seed_schedule("sch-en2", enabled=1)
    with _as_roles("System Manager"):
        dashboard.schedule_set_enabled("sch-en2", False)
    assert frappe.db.get_value("Conductor Schedule", "sch-en2", "enabled") == 0


def test_get_schedule_next_fires():
    _seed_schedule("sch-next", cron="*/5 * * * *")
    with _as_roles("Conductor Operator"):
        fires = dashboard.get_schedule_next_fires("sch-next", count=3)
    assert len(fires) == 3
```

- [ ] **Step 2: Implement endpoints**

Append:

```python
from croniter import croniter
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore


@frappe.whitelist()
def schedule_run_now(name: str) -> str:
    _require_read()
    if not (frappe.has_permission("Conductor Schedule", "write")
            or "Conductor Operator" in frappe.get_roles()):
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    sch = frappe.get_doc("Conductor Schedule", name)
    args = _decode_b64_msgpack(sch.args) or []
    kwargs = _decode_b64_msgpack(sch.kwargs) or {}
    return _enqueue_for_retry(sch.method, queue=sch.queue, args=args, kwargs=kwargs)


@frappe.whitelist()
def schedule_set_enabled(name: str, enabled: bool) -> None:
    _require_destructive()
    enabled_int = 1 if (enabled is True or str(enabled).lower() in {"1", "true"}) else 0
    frappe.db.set_value("Conductor Schedule", name, "enabled", enabled_int)
    frappe.db.commit()


@frappe.whitelist()
def get_schedule_next_fires(name: str, count: int = 10) -> list[str]:
    _require_read()
    sch = frappe.db.get_value(
        "Conductor Schedule", name,
        ["cron_expression", "timezone"], as_dict=True,
    )
    if not sch:
        frappe.throw(_("Schedule not found"), frappe.DoesNotExistError)

    tz_name = sch.timezone or "UTC"
    if ZoneInfo:
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")
    else:
        tz = timezone.utc

    base = datetime.now(tz)
    it = croniter(sch.cron_expression, base)
    return [it.get_next(datetime).isoformat() for _ in range(int(count))]
```

- [ ] **Step 3: Run — confirm pass**

```bash
pytest tests/test_api_dashboard.py -v
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_api_dashboard.py conductor/api/dashboard.py
git commit -m "feat(api/dashboard): schedule run-now / set-enabled / next-fires"
```

---

### Task 14: `get_worker` endpoint

**Files:**
- Modify: `conductor/api/dashboard.py`
- Modify: `tests/test_api_dashboard.py`

- [ ] **Step 1: Write test**

```python
def _seed_worker(worker_id="w1", status="ALIVE"):
    frappe.get_doc({
        "doctype": "Conductor Worker", "name": worker_id,
        "host": "localhost", "pid": 12345, "queues": '["default"]',
        "status": status, "last_heartbeat": frappe.utils.now_datetime(),
        "started_at": frappe.utils.now_datetime(),
    }).insert(ignore_permissions=True)
    frappe.db.commit()


def test_get_worker_returns_detail_and_recent_jobs():
    _seed_worker("w1")
    frappe.get_doc({
        "doctype": "Conductor Job", "name": "wjob1", "job_id": "wjob1",
        "queue": "default", "method": "x.y", "status": "SUCCEEDED",
        "worker_id": "w1", "finished_at": "2026-04-28 10:00:00",
    }).insert(ignore_permissions=True)
    frappe.db.commit()

    with _as_roles("Conductor Operator"):
        result = dashboard.get_worker("w1")
    assert result["name"] == "w1"
    assert any(j["job_id"] == "wjob1" for j in result["recent_jobs"])
    assert "heartbeat_age_seconds" in result
```

- [ ] **Step 2: Implement**

```python
@frappe.whitelist()
def get_worker(worker_id: str) -> dict[str, Any]:
    _require_read()
    if not frappe.db.exists("Conductor Worker", worker_id):
        frappe.throw(_("Worker not found"), frappe.DoesNotExistError)

    worker = frappe.get_doc("Conductor Worker", worker_id).as_dict()
    last_hb = worker.get("last_heartbeat")
    if last_hb:
        delta = (frappe.utils.now_datetime() - last_hb).total_seconds()
        worker["heartbeat_age_seconds"] = max(0, int(delta))
    else:
        worker["heartbeat_age_seconds"] = None

    worker["recent_jobs"] = frappe.get_all(
        "Conductor Job",
        filters={"worker_id": worker_id},
        fields=["job_id", "method", "queue", "status", "finished_at"],
        order_by="finished_at desc",
        limit=20,
    )
    return worker
```

- [ ] **Step 3: Run — pass**
- [ ] **Step 4: Commit**

```bash
git add tests/test_api_dashboard.py conductor/api/dashboard.py
git commit -m "feat(api/dashboard): get_worker with heartbeat-age + recent jobs"
```

---

### Task 15: Verify polling-interval config wiring

**Files:**
- Modify: `tests/test_api_dashboard.py` (one extra test confirming `site_config.json` override)

- [ ] **Step 1: Write test**

```python
def test_get_state_respects_site_config_poll_interval(monkeypatch):
    monkeypatch.setattr(dashboard, "_redis_queue_depth", lambda *a, **k: 0)
    monkeypatch.setattr(dashboard, "_redis_scheduled_count", lambda *a, **k: 0)
    monkeypatch.setattr(frappe.local, "conf",
                        {"conductor": {"dashboard_poll_interval_ms": 5000}})
    with _as_roles("Conductor Operator"):
        state = dashboard.get_state()
    assert state["config"]["poll_interval_ms"] == 5000
```

- [ ] **Step 2: Run + commit**

```bash
pytest tests/test_api_dashboard.py -v
git add tests/test_api_dashboard.py
git commit -m "test(api/dashboard): site_config.json override of poll interval"
```

---

## Phase D — Frontend scaffold (Tasks 16–19)

Builds on the Task 2 spike scaffolding. Adds router + state composables + tab shell.

---

### Task 16: SPA shell with router + top tabs

**Files:**
- Modify: `dashboard/src/main.js`, `dashboard/src/App.vue`
- Create: `dashboard/src/router.js`, `dashboard/src/pages/OverviewPage.vue`, `dashboard/src/pages/FeedPage.vue`, `dashboard/src/pages/JobsPage.vue`, `dashboard/src/pages/DlqPage.vue`, `dashboard/src/pages/SchedulesPage.vue`, `dashboard/src/pages/WorkersPage.vue`

- [ ] **Step 1: Create router**

`dashboard/src/router.js`:

```js
import { createRouter, createWebHashHistory } from "vue-router";

const routes = [
  { path: "/", redirect: "/overview" },
  { path: "/overview", component: () => import("./pages/OverviewPage.vue") },
  { path: "/feed",     component: () => import("./pages/FeedPage.vue") },
  { path: "/jobs/:job_id?",       component: () => import("./pages/JobsPage.vue"),      props: true },
  { path: "/dlq/:entry_name?",    component: () => import("./pages/DlqPage.vue"),       props: true },
  { path: "/schedules/:name?",    component: () => import("./pages/SchedulesPage.vue"), props: true },
  { path: "/workers/:worker_id?", component: () => import("./pages/WorkersPage.vue"),   props: true },
];

export default createRouter({ history: createWebHashHistory(), routes });
```

- [ ] **Step 2: Wire router into `main.js`**

```js
import { createApp } from "vue";
import App from "./App.vue";
import router from "./router";

createApp(App).use(router).mount("#app");
```

- [ ] **Step 3: Replace `App.vue` with the tab shell**

```vue
<template>
  <div class="conductor-shell">
    <nav class="tabs">
      <router-link to="/overview">Overview</router-link>
      <router-link to="/feed">Live Feed</router-link>
      <router-link to="/jobs">Jobs</router-link>
      <router-link to="/dlq">DLQ</router-link>
      <router-link to="/schedules">Schedules</router-link>
      <router-link to="/workers">Workers</router-link>
    </nav>
    <main><router-view /></main>
  </div>
</template>

<script setup>
</script>

<style scoped>
.conductor-shell { font-family: system-ui, sans-serif; }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid #ddd; padding: 0 16px; }
.tabs a { padding: 8px 12px; text-decoration: none; color: #555; border-bottom: 2px solid transparent; }
.tabs a.router-link-active { color: #2563eb; border-bottom-color: #2563eb; font-weight: 500; }
main { padding: 16px; }
</style>
```

- [ ] **Step 4: Create stub page components**

For each of the six pages (OverviewPage / FeedPage / JobsPage / DlqPage / SchedulesPage / WorkersPage), create a minimal stub:

```vue
<template>
  <div>
    <h2>Overview</h2>
    <p>Coming next.</p>
  </div>
</template>

<script setup>
</script>
```

(Replace heading text per page.)

- [ ] **Step 5: Build + verify**

```bash
cd dashboard && yarn build && cd ..
bench --site frappe.localhost browse  # navigate to /conductor-dashboard
```

Expected: tabs render; clicking each updates the URL hash and shows the corresponding "Coming next." stub.

- [ ] **Step 6: Commit**

```bash
git add dashboard/
git commit -m "feat(dashboard): SPA shell with hash router + 6 tab stubs"
```

---

### Task 17: API + realtime client wrappers

**Files:**
- Create: `dashboard/src/api.js`, `dashboard/src/realtime.js`

- [ ] **Step 1: Create `api.js`**

```js
const BASE = "/api/method/conductor.api.dashboard";

async function call(endpoint, params = {}, method = "GET") {
  const url = `${BASE}.${endpoint}`;
  const opts = {
    method,
    credentials: "include",
    headers: {
      "X-Frappe-CSRF-Token": window.frappe?.csrf_token || "token",
    },
  };
  let finalUrl = url;
  if (method === "GET") {
    const qs = new URLSearchParams(params).toString();
    if (qs) finalUrl = `${url}?${qs}`;
  } else {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(params);
  }
  const res = await fetch(finalUrl, opts);
  if (!res.ok) throw new Error(`${endpoint}: ${res.status}`);
  const data = await res.json();
  return data.message;  // Frappe wraps responses in {message: ...}
}

export const api = {
  getState:        () => call("get_state"),
  getJob:          (job_id) => call("get_job", { job_id }),
  retryJob:        (job_id) => call("retry_job", { job_id }, "POST"),
  cancelJob:       (job_id) => call("cancel_job", { job_id }, "POST"),
  getDlqEntry:     (name) => call("get_dlq_entry", { name }),
  dlqRetry:        (entry_names) => call("dlq_retry", { entry_names }, "POST"),
  dlqDiscard:      (entry_names) => call("dlq_discard", { entry_names }, "POST"),
  dlqEditAndRetry: (name, args_json, kwargs_json) =>
    call("dlq_edit_and_retry", { name, args_json, kwargs_json }, "POST"),
  scheduleRunNow:     (name) => call("schedule_run_now", { name }, "POST"),
  scheduleSetEnabled: (name, enabled) => call("schedule_set_enabled", { name, enabled }, "POST"),
  getScheduleNextFires: (name, count = 10) =>
    call("get_schedule_next_fires", { name, count }),
  getWorker: (worker_id) => call("get_worker", { worker_id }),
};

export function getList(doctype, opts = {}) {
  const params = {
    doctype,
    fields: JSON.stringify(opts.fields || ["name"]),
    filters: JSON.stringify(opts.filters || {}),
    order_by: opts.order_by || "modified desc",
    limit_page_length: opts.limit || 50,
    limit_start: opts.start || 0,
  };
  return call("../frappe.client.get_list", params);
}

export function userRoles() {
  return window.frappe?.boot?.user?.roles || [];
}
```

- [ ] **Step 2: Create `realtime.js`**

```js
// Spec §8.6.1: per-doc events ride the doc:{Doctype}/{name} room. The
// page must call doc_subscribe to join the room AND on(event_name) to
// match the Socket.IO event-name label. Both are required.

function _rt() {
  if (!window.frappe?.realtime) {
    console.warn("frappe.realtime not available; running outside Desk?");
    return null;
  }
  return window.frappe.realtime;
}

export function subscribeDoc(doctype, docname, eventName, callback) {
  const rt = _rt();
  if (!rt) return () => {};
  rt.doc_subscribe(doctype, docname);
  rt.on(eventName, callback);
  return () => {
    rt.off(eventName, callback);
    rt.doc_unsubscribe(doctype, docname);
  };
}

// Generic event-only subscription (no doc room) — for site-wide events
// like "list_update". Use sparingly; prefer subscribeDoc for per-entity.
export function subscribe(eventName, callback) {
  const rt = _rt();
  if (!rt) return () => {};
  rt.on(eventName, callback);
  return () => rt.off(eventName, callback);
}
```

- [ ] **Step 3: Build + commit**

```bash
cd dashboard && yarn build && cd ..
git add dashboard/src/api.js dashboard/src/realtime.js
git commit -m "feat(dashboard): api.js + realtime.js client wrappers"
```

---

### Task 18: `useDashboardState` polling composable

**Files:**
- Create: `dashboard/src/stores/useDashboardState.js`

- [ ] **Step 1: Implement**

```js
import { ref, onMounted, onBeforeUnmount } from "vue";
import { api } from "../api";

let _instance = null;

export function useDashboardState() {
  if (_instance) return _instance;

  const state = ref(null);
  const error = ref(null);
  let timer = null;
  let refCount = 0;

  async function tick() {
    try {
      const snapshot = await api.getState();
      state.value = snapshot;
      error.value = null;
      const nextMs = snapshot.config?.poll_interval_ms || 2000;
      timer = setTimeout(tick, nextMs);
    } catch (e) {
      error.value = e;
      timer = setTimeout(tick, 5000); // backoff on error
    }
  }

  function start() {
    refCount += 1;
    if (refCount === 1) tick();
  }

  function stop() {
    refCount = Math.max(0, refCount - 1);
    if (refCount === 0 && timer) {
      clearTimeout(timer);
      timer = null;
    }
  }

  _instance = { state, error, start, stop };
  return _instance;
}

export function useAutoPolling() {
  const store = useDashboardState();
  onMounted(store.start);
  onBeforeUnmount(store.stop);
  return store;
}
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/src/stores/useDashboardState.js
git commit -m "feat(dashboard): useDashboardState polling composable with refcount"
```

---

### Task 19: `useDetailSubscription` realtime composable

**Files:**
- Create: `dashboard/src/stores/useDetailSubscription.js`

- [ ] **Step 1: Implement**

```js
import { ref, onBeforeUnmount, watch } from "vue";
import { subscribeDoc } from "../realtime";

/**
 * Subscribe to per-entity realtime events for the open detail view.
 *
 *   const { data, refetch, unsubscribe } = useDetailSubscription(
 *     "Conductor Job",          // doctype — joins room doc:Conductor Job/{id}
 *     "conductor:job",          // event-name prefix; full event = `${prefix}:${id}`
 *     jobIdRef,
 *     () => api.getJob(jobIdRef.value),
 *   );
 *
 * `data` is reactive and reflects the most recent realtime delta merged
 * over the most recent full fetch. See spec §8.6.1 for why doctype is
 * required (event= alone broadcasts site-wide).
 */
export function useDetailSubscription(doctype, eventPrefix, idRef, fetcher) {
  const data = ref(null);
  let unsub = () => {};

  async function refetch() {
    if (!idRef.value) return;
    data.value = await fetcher();
  }

  function attach() {
    unsub();
    if (!idRef.value) {
      unsub = () => {};
      return;
    }
    const eventName = `${eventPrefix}:${idRef.value}`;
    unsub = subscribeDoc(doctype, idRef.value, eventName, (delta) => {
      if (data.value) data.value = { ...data.value, ...delta };
      // Re-fetch full record on terminal-state transitions to load traceback.
      if (["FAILED", "DLQ", "SUCCEEDED", "TIMED_OUT", "CANCELLED"].includes(delta?.status)) {
        refetch();
      }
    });
  }

  watch(idRef, async (newId, oldId) => {
    if (newId !== oldId) {
      data.value = null;
      attach();
      await refetch();
    }
  }, { immediate: true });

  onBeforeUnmount(() => unsub());

  return { data, refetch, unsubscribe: () => unsub() };
}
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/src/stores/useDetailSubscription.js
git commit -m "feat(dashboard): useDetailSubscription per-entity realtime composable"
```

---

## Phase E — Frontend sections (Tasks 20–26)

Each section is one Vue page under `dashboard/src/pages/`. Build them in this order so the critical-path exit criterion (Jobs detail + retry) lands earliest.

---

### Task 20: Jobs page (master + detail) — exit-criterion path

**Files:**
- Modify: `dashboard/src/pages/JobsPage.vue`
- Create: `dashboard/src/components/StatusBadge.vue`, `dashboard/src/components/JsonViewer.vue`

(Detailed implementation in spec §9.3. Use `getList("Conductor Job", { filters, fields: ["job_id","method","queue","status","attempt","enqueued_at","last_error_message"], order_by: "enqueued_at desc" })` for the master pane, `useDetailSubscription("Conductor Job", "conductor:job", jobIdRef, () => api.getJob(jobIdRef.value))` for the detail pane (note the leading `doctype` arg per spec §8.6.1). Filter bar = queue/status/method/time-range. Detail sub-tabs = Overview/Runs/Args/Trace. Retry button calls `api.retryJob(job_id)`; Cancel button calls `api.cancelJob(job_id)`; both are hidden if user lacks write perm.)

- [ ] **Step 1: Implement `StatusBadge.vue`** with the color matrix from spec §9.3 (green=SUCCEEDED, blue=RUNNING, yellow=QUEUED/SCHEDULED_RETRY, red=FAILED/DLQ/TIMED_OUT, grey=CANCELLED).

- [ ] **Step 2: Implement `JsonViewer.vue`** — pretty-print JSON in a `<pre>` block; nothing fancy. ~10 lines.

- [ ] **Step 3: Implement `JobsPage.vue`** with master/detail split, filter bar, list (paginated 50/page), detail pane with sub-tabs and action buttons (Retry/Cancel gated on roles via `userRoles()`).

- [ ] **Step 4: Build + manual test**

```bash
cd dashboard && yarn build && cd ..
```

Open `/conductor-dashboard#/jobs`, verify list renders against `Conductor Job` rows. Click a row, verify detail shows. Click Retry on a FAILED job, verify a new job is enqueued via `api.retryJob`. **This is the exit-criterion path** — confirm it works end-to-end before continuing.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src
git commit -m "feat(dashboard): Jobs page master+detail with retry/cancel actions"
```

---

### Task 21: DLQ page

**Files:**
- Modify: `dashboard/src/pages/DlqPage.vue`
- Create: `dashboard/src/components/EditAndRetryModal.vue`

(Detailed shape in spec §9.4. Master pane: filterable list with checkbox column + bulk-action bar. Detail pane: header + sections (Last error, Original payload with JSON-safety badge, Linked job, Review notes). Edit-and-Retry modal: textareas for args + kwargs JSON; submit calls `api.dlqEditAndRetry`.)

- [ ] **Step 1: Implement `EditAndRetryModal.vue`** — two `<textarea>`s (args/kwargs), validation by `JSON.parse` on submit, server returns the new job_id.
- [ ] **Step 2: Implement `DlqPage.vue`** with multi-select, bulk actions, JSON-safety badge, role-gated buttons.
- [ ] **Step 3: Build + verify** — seed a DLQ entry via `bench console` (`frappe.get_doc(...).insert()`), verify it appears, verify retry-as-is works, verify discard is hidden for Operator role.
- [ ] **Step 4: Commit** `feat(dashboard): DLQ page with bulk actions + JSON-safety-gated edit-and-retry`

---

### Task 22: Schedules page

**Files:**
- Modify: `dashboard/src/pages/SchedulesPage.vue`
- Create: `dashboard/src/components/MiniCalendar.vue`

(Spec §9.5. Master pane: list with enable toggle (disabled control for Operator). Detail pane: Last dispatch + Last job (separate rows, not conflated), Next 10 fires (`api.getScheduleNextFires`), Recent 20 runs (heuristic via `getList("Conductor Job", { method: schedule.method })`), MiniCalendar with dot-per-day for next 28 days.)

- [ ] **Step 1: Implement `MiniCalendar.vue`** — CSS grid 7×4, fill from a list of date strings.
- [ ] **Step 2: Implement `SchedulesPage.vue`** — master + detail with role-gated enable toggle, run-now button (Operator+).
- [ ] **Step 3: Build + verify**.
- [ ] **Step 4: Commit** `feat(dashboard): Schedules page with mini-calendar + run-now/enable`

---

### Task 23: Workers page

**Files:**
- Modify: `dashboard/src/pages/WorkersPage.vue`

(Spec §9.6. Master: list of workers with status badge + heartbeat-age; sort ALIVE first. Detail: header + currently executing + recent jobs + heartbeat age. No mutating actions.)

- [ ] **Step 1: Implement** `WorkersPage.vue` — master/detail split, no buttons.
- [ ] **Step 2: Build + verify**.
- [ ] **Step 3: Commit** `feat(dashboard): Workers page with heartbeat observability`

---

### Task 24: Live Feed page

**Files:**
- Modify: `dashboard/src/pages/FeedPage.vue`

(Spec §9.2. Single column, newest at top, ~80 visible rows from `state.feed_recent`, "Pause on hover" toggle.)

- [ ] **Step 1: Implement** `FeedPage.vue`.
- [ ] **Step 2: Build + verify** (dispatch a few jobs from `bench console`; watch the feed update).
- [ ] **Step 3: Commit** `feat(dashboard): Live Feed page`

---

### Task 25: Overview page

**Files:**
- Modify: `dashboard/src/pages/OverviewPage.vue`
- Create: `dashboard/src/components/NumberCard.vue`, `dashboard/src/components/QueueChart.vue`

(Spec §9.1. 4-up number cards + 2-up charts. Use frappe-ui's chart wrapper or `frappe.Chart` (loaded from Frappe globals as `window.frappe.Chart`).)

- [ ] **Step 1: Implement `NumberCard.vue`** — title, big number, click → router-push.
- [ ] **Step 2: Implement `QueueChart.vue`** — wrapper around `frappe.Chart` with `type=bar`.
- [ ] **Step 3: Implement `OverviewPage.vue`** — full-width grid with cards + charts, click-through to filtered routes.
- [ ] **Step 4: Build + verify**.
- [ ] **Step 5: Commit** `feat(dashboard): Overview page with cards + charts`

---

### Task 26: Permission-aware UI hiding pass

**Files:**
- Modify: All page components that render destructive buttons (DlqPage, SchedulesPage)

- [ ] **Step 1: Audit each page** with `grep -rn "v-if.*role\|userRoles" dashboard/src/`. Confirm:
  - DLQ: Discard button hidden for non-SysMgr.
  - DLQ: Edit-and-retry button hidden for non-SysMgr.
  - Schedules: Enable toggle disabled for non-SysMgr.
- [ ] **Step 2: Add a `useUserRoles()` composable** if not already present:

```js
// dashboard/src/stores/useUserRoles.js
import { computed } from "vue";
import { userRoles } from "../api";
export function useUserRoles() {
  const roles = userRoles();
  return {
    isSysMgr: computed(() => roles.includes("System Manager")),
    isOperator: computed(() =>
      roles.includes("Conductor Operator") || roles.includes("System Manager")
    ),
  };
}
```

- [ ] **Step 3: Use it in DlqPage and SchedulesPage** — wrap destructive buttons in `v-if="isSysMgr"`.
- [ ] **Step 4: Build + verify** — log in as a Conductor Operator user (created via `bench --site frappe.localhost add-user-role`), confirm Discard button is gone.
- [ ] **Step 5: Commit** `feat(dashboard): role-aware UI hiding for destructive actions`

---

## Phase F — Verification & docs (Tasks 27–30)

---

### Task 27: Chaos test for per-job realtime events

**Files:**
- Create: `tests_chaos/test_realtime_events.py`

The exact subscription mechanism depends on Task 1 spike findings. Below is the monkeypatch-based pattern (most robust if Frappe doesn't expose a socketio test client).

- [ ] **Step 1: Write the test**

```python
"""Chaos test: dispatch a job that goes QUEUED -> RUNNING -> FAILED -> DLQ;
assert the per-job realtime event sequence is emitted in order."""

from unittest.mock import patch
import frappe

from conductor.dispatcher import enqueue


def test_job_emits_status_events_in_order(spawn_scheduler, fakemethod_failing):
    captured = []

    def capture_emit(*args, **kwargs):
        if kwargs.get("event", "").startswith("conductor:job:"):
            captured.append({
                "event": kwargs["event"],
                "status": kwargs["message"]["status"],
                "after_commit": kwargs.get("after_commit"),
                "doctype": kwargs.get("doctype"),
                "docname": kwargs.get("docname"),
            })

    with patch("frappe.publish_realtime", side_effect=capture_emit):
        job_id = enqueue(fakemethod_failing, queue="default", max_attempts=1)
        # Wait for worker to consume + transition through to DLQ.
        _wait_for_status(job_id, "DLQ", timeout=20)

    mine = [e for e in captured if e["event"].endswith(job_id)]
    statuses = [e["status"] for e in mine]
    assert statuses[0] == "QUEUED"
    assert "RUNNING" in statuses
    assert statuses[-1] == "DLQ"
    assert all(e["after_commit"] is True for e in mine)
    # Spec §8.6.1: delivery scope is doctype/docname, not event=. The bug we
    # are guarding against is event-only emits that broadcast site-wide.
    assert all(e["doctype"] == "Conductor Job" for e in mine)
    assert all(e["docname"] == job_id for e in mine)


def _wait_for_status(job_id, target, timeout):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        frappe.db.rollback()
        s = frappe.db.get_value("Conductor Job", job_id, "status")
        if s == target:
            return
        time.sleep(0.2)
    raise AssertionError(f"timeout waiting for {target}; last={s}")
```

- [ ] **Step 2: Add fixture for `fakemethod_failing`**

In `tests_chaos/conftest.py`, append:

```python
@pytest.fixture
def fakemethod_failing():
    """Returns a method dotted-path that always raises."""
    return "conductor.demo.always_raises"  # add this in conductor/demo.py if missing
```

If `conductor.demo.always_raises` doesn't exist, add it to `conductor/demo.py`:

```python
def always_raises():
    raise ValueError("intentional failure for chaos test")
```

- [ ] **Step 3: Run the chaos suite**

```bash
pytest tests_chaos/test_realtime_events.py -v
```

Expected: green. If flaky (per Phase 2 hand-off §3.1, chaos has ~10% under-load flake), verify it's green on a single run; rerun if needed.

- [ ] **Step 4: Commit**

```bash
git add tests_chaos/test_realtime_events.py tests_chaos/conftest.py conductor/demo.py
git commit -m "test(chaos): per-job realtime events fire in order across transitions"
```

---

### Task 28: Master design footnotes

**Files:**
- Modify: `docs/superpowers/specs/2026-04-27-conductor-master-design.md`

- [ ] **Step 1: §4 — Phase 3 footnote**

Find the "Phase 3 — Dashboard" subsection. After the "Ships:" bullet about "single-file Vue 3 SFC, embedded as a Frappe Page DocType", add a footnote:

```markdown
> **Phase 3 refinement (2026-04-28):** Implemented as a `www/conductor-dashboard.html`
> route built from a standalone vite project (HRMS roster pattern), not as a Frappe
> Page DocType. The `www/` route is the proven Vue 3 SFC pattern in this Frappe 15.106.0
> bench. See Phase 3 spec §2 #3 for full reasoning.
```

- [ ] **Step 2: §9 — Real-time events row**

Find the "Real-time dashboard events (`conductor:*`)" row. Append to the right column:

> "Phase 3 settled the event family as `conductor:job:{job_id}` only; aggregates use polling. Existing global `conductor:job_queued` is replaced (breaking change documented in Phase 3 spec §13)."

- [ ] **Step 3: Add change-log entry at the bottom of the master**

```markdown
| 2026-04-28 | Phase 3 footnotes: UI delivery refined to www/ route; realtime event family settled. | osama.m@aau.iq |
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-04-27-conductor-master-design.md
git commit -m "docs(master): Phase 3 footnotes — www/ route delivery + per-job realtime"
```

---

### Task 29: Operator README updates

**Files:**
- Modify: `apps/conductor/README.md`

- [ ] **Step 1: Add a "Dashboard" section**

Find the "Phase 2 operations" section (per recent git log) and add after it:

```markdown
## Dashboard (Phase 3)

The Conductor dashboard is at `https://<your-site>/conductor-dashboard`. Six tabs:

- **Overview** — queue depths, throughput, error rate, DLQ counts.
- **Live Feed** — chronological stream of recent jobs.
- **Jobs** — filterable list; click → detail with traceback, retry, cancel.
- **DLQ** — failed-after-retries jobs; bulk retry / discard / edit-and-retry.
- **Schedules** — list + run-now + enable/disable.
- **Workers** — observability of running workers.

### Permissions

- **System Manager**: full access.
- **Conductor Operator**: read everything + retry / cancel / run-now.
- Destructive actions (DLQ discard, payload edit, schedule enable/disable) are System Manager only.

### Configuration

In `site_config.json`:

```json
{
  "conductor": {
    "dashboard_poll_interval_ms": 2000
  }
}
```

Default 2000 ms. Range: 500–60000.

### Build

The dashboard is a Vue 3 SPA under `apps/conductor/dashboard/`. Build with:

```bash
cd apps/conductor/dashboard && yarn install && yarn build
```

`bench build` invokes the same pipeline via the app-root `package.json`'s `build` script.
```

- [ ] **Step 2: Commit**

```bash
git add apps/conductor/README.md
git commit -m "docs(README): Phase 3 dashboard operations section"
```

---

### Task 30: Exit-criterion sign-off demo

**Files:**
- Create: `docs/superpowers/specs/2026-04-28-conductor-phase3-exit-demo.md` (the demo runbook + verification checklist)

The Phase 3 exit criterion (master §4 verbatim):
> "Operator can fully diagnose a failed job (find it, see its traceback, retry it) without SSH or `bench console`."

- [ ] **Step 1: Write the demo runbook**

```markdown
# Phase 3 Exit-Criterion Demo Runbook

**Date:** 2026-04-28 (or actual run date)
**Phase:** 3 — Dashboard
**Exit criterion:** Operator can fully diagnose a failed job (find it, see its traceback, retry it) without SSH or `bench console`.

## Setup (one-time, allowed to use bench console)

1. Ensure a Conductor Operator user exists:
   ```bash
   bench --site frappe.localhost add-user-role osama.m@aau.iq "Conductor Operator"
   ```
2. Build the dashboard: `cd apps/conductor/dashboard && yarn build`
3. Start a worker: `bench conductor worker --queue default --concurrency 2`
4. Dispatch a job that will fail:
   ```python
   from conductor.dispatcher import enqueue
   enqueue("conductor.demo.always_raises", queue="default", max_attempts=2)
   ```

## Demo (NO bench console / SSH allowed past this point)

1. **Find:** Open `/conductor-dashboard#/jobs?status=FAILED` as the Operator user. The failed job appears within ~2 s.
2. **See traceback:** Click the row. The detail pane opens with `last_error_message` and `last_traceback` visible. The traceback contains the original `ValueError: intentional failure for chaos test`.
3. **Retry:** Click the "Retry" button. Confirm in the toast that a new job_id was created. Watch the Live Feed: the new job appears as QUEUED → RUNNING → FAILED (because `always_raises` still fails, but the retry mechanism is what's verified).

If steps 1–3 work without leaving the browser, the exit criterion is met.

## Sign-off

Verified by: __________________  Date: __________________
```

- [ ] **Step 2: Run the demo and capture screenshots / video** (optional but encouraged for the project archive).

- [ ] **Step 3: Write the hand-off note for Phase 4** in spec §15 of the design doc:

```markdown
## 15. Phase 3 hand-off notes (carry-forward to Phase 4)

(Filled in 2026-04-28-Phase 3 ship date)

### What shipped
- `www/conductor-dashboard.html` Vue 3 SPA with 6 tabs.
- 12 whitelisted endpoints in `conductor.api.dashboard`.
- Per-job realtime event family (`conductor:job:{job_id}`).
- Two-tier permission model.

### Real bugs / surprises during execution
(Capture any non-trivial issues encountered during plan execution.)

### Residual limitations (accepted, deferred)
1. ...

### Phase 4 first-day backlog
1. Wire OTel exporter — the dashboard's Trace tab already shows `trace_id`; Phase 4 makes the link clickable.
2. Add `Conductor Job.schedule` link field — fixes the Schedules-recent-runs heuristic noted in spec §11 risk #5.
3. Add Prometheus / OTLP metrics endpoint — populates the Overview throughput/error-rate properly (currently stubbed at 0 in `get_state`).
```

- [ ] **Step 4: Commit + tag**

```bash
git add docs/superpowers/specs/2026-04-28-conductor-phase3-exit-demo.md docs/superpowers/specs/2026-04-28-conductor-phase3-dashboard-design.md
git commit -m "release: Conductor Phase 3 — Dashboard complete

Exit criterion verified: operator diagnoses + retries failed jobs from
browser without SSH or bench console. See exit-demo runbook."
git tag v0.3.0
```

---

## Self-Review (executed by plan author)

**1. Spec coverage:**
- §1 Exit criterion → verified by Task 30 demo
- §2 Decisions table → all 11 settled in spec; no plan tasks needed
- §3 Architecture → Tasks 4–7 (events) + 9–15 (API) + 16–25 (frontend)
- §4 Routing → Task 16
- §5 Project layout → Task 2 (scaffold) + 16 (full structure) + 3 (api package migration)
- §6 Permissions → Task 9 (helpers) + per-endpoint enforcement in 10–14 + 26 (UI)
- §7 API surface → Tasks 9–14 (all 12 endpoints)
- §7.2 Polling configurability → Task 15
- §8 Realtime taxonomy → Tasks 4–7 (server emits) + 17, 19 (client subscribe)
- §8.6 Spike → Task 1
- §9 Section content → Tasks 20–25 (six pages)
- §10 Testing → Tasks 4, 8, 9–14 (unit) + 27 (chaos)
- §11 Risks → addressed in Tasks 1, 2, 8, 26 (corresponding mitigations)
- §13 Master design changes → Task 28
- §14 Implementation task ordering hint → roughly followed; refined into 30 tasks

**2. Placeholder scan:**
- Tasks 21–25 use shorter step descriptions ("implement DLQ master+detail") because their layouts are exhaustively documented in spec §9; the engineer is told where to find the detail. This is intentional — duplicating spec §9 verbatim into the plan is anti-DRY and rots when the spec is updated. Each of these tasks still has concrete file paths, build steps, and commit messages, so they pass the bite-sized-step bar.
- One known gap: Tasks 21–25 don't have explicit failing-tests-first steps. Reason: the frontend lacks a unit-test harness in this repo (no Jest/Vitest setup); adding one is out of scope for Phase 3. Frontend behaviors are verified by manual smoke-test ("Build + verify" step in each task) and end-to-end by Task 27 (chaos test for the realtime event flow that drives the UI) and Task 30 (manual exit-criterion demo). Document this trade-off if the user pushes back.

**3. Type / signature consistency:**
- `emit_job_event(job_id, status, **fields)` — used identically in Task 4 (definition), 5–7 (call sites). ✓
- `is_json_safe(value) -> bool` — Task 8 definition, Tasks 12 + 26 call sites. ✓
- `dashboard.api.*` endpoint names — Task 17 wraps them; Tasks 20–25 use the same names. ✓
- `useDetailSubscription(doctype, eventPrefix, idRef, fetcher)` signature — Task 19 definition; Task 20 call site (`useDetailSubscription("Conductor Job", "conductor:job", jobIdRef, () => api.getJob(...))`). ✓

**4. Rough effort estimate:** 30 tasks × ~20 min/task = ~10 hours of focused execution time, plus spike + chaos + demo overhead. Realistic ship window: 1.5–2 days for one engineer.
