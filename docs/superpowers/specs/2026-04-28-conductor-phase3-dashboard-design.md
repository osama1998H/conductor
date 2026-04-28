# Conductor — Phase 3: Dashboard (Spec)

**Status:** Draft for approval
**Date:** 2026-04-28
**Author:** osama.m@aau.iq
**Derives from:** [Master Design](2026-04-27-conductor-master-design.md) §4 "Phase 3 — Dashboard", §9 inter-phase contracts.
**Hand-off input:** [Phase 3 hand-off notes](2026-04-28-conductor-phase3-handoff.md).

This spec refines the master's Phase 3 section. Per master §3, only the cross-cutting decisions (app name, msgpack, Redis topology, stream schema, etc.) are frozen across phases. The UI stack and section-level UX are open for Phase 3 to settle. This spec settles them.

---

## 1. Exit criterion (verbatim from master §4)

> "Operator can fully diagnose a failed job (find it, see its traceback, retry it) without SSH or `bench console`."

Every design choice in this document supports that flow:
- **Find** → Jobs tab, filter status=FAILED.
- **See traceback** → row click → detail pane → `last_traceback`.
- **Retry** → Retry button (Conductor Operator role allowed).

The other five sections (Overview, Live Feed, DLQ, Schedules, Workers) are bonus value above the gating bar; they do not gate the phase.

---

## 2. Decisions ratified by this brainstorm

| # | Decision | Value | Notes |
|---|---|---|---|
| 1 | Phase 3 scope | Full master scope: 6 sections (Overview, Live Feed, Jobs, DLQ, Schedules, Workers) | Workflows section remains Phase 5 |
| 2 | UI stack | Vue 3 SFC + Vue Router 4 + `frappe-ui` + `vite` | Matches master §4 wording for "Vue 3 SFC" |
| 3 | UI delivery | **`www/conductor-dashboard.html` route** built from a standalone vite project at `apps/conductor/dashboard/` | **Refines** master §4's "Frappe Page DocType" wording. Reason: the working Vue 3 SFC pattern in this Frappe 15.106.0 bench is `www/` + vite (per HRMS roster + frontend); Frappe Desk Page bundle compilation for `.vue` is unproven. Logged in §13 change-log |
| 4 | Routing | One Vue SPA, Vue Router 4 hash mode | Deep-linkable URLs without server history fallback |
| 5 | Layout | Top tab strip + master/detail split column inside Jobs / DLQ / Schedules / Workers | Overview is full-width grid (exception); Live Feed is single-column scroll (exception) |
| 6 | Update strategy | **Hybrid**: SPA polls `get_state()` every 2 s for aggregates; subscribes to per-job realtime events only when a Job detail pane is open | Avoids socketio firehose under load |
| 7 | Realtime events added | One event family: `conductor:job:{job_id}` | Schedules / workers / DLQ rely on polling — they change slowly enough |
| 8 | Permission model | Two-tier (System Manager + Conductor Operator) | Operator can retry / run-now / cancel; SysMgr only for DLQ-discard, edit-and-retry, schedule enable/disable |
| 9 | DLQ edit-and-retry | **JSON-safety-gated** | Payloads containing `datetime` / `Decimal` / `bytes` cannot be edited (preserves master §3 #17 msgpack invariant); plain "Retry as-is" is always available |
| 10 | Polling interval | 2 s default; configurable via `site_config.json` `conductor.dashboard_poll_interval_ms` | High-volume sites can dial down |
| 11 | Existing global `conductor:job_queued` event | **Replaced** by per-job `conductor:job:{job_id}` | Breaking change for external consumers; documented in §13 change-log; master §9 stable-contract row for "Real-time dashboard events" becomes stable from Phase 3 (already so per master) |

---

## 3. Architecture overview

```
┌──────────────────────────────────────────────────────────────────┐
│  Browser  ─  /conductor-dashboard  (Vue 3 SPA, hash routes)      │
│                                                                   │
│  poll every 2s ──►  conductor.api.dashboard.get_state             │
│                                                                   │
│  realtime.on("conductor:job:<id>")  ◄──  publish_realtime         │
│      (only when detail pane open)                                 │
└─────────────────────┬────────────────────────────────────────────┘
                      │  HTTP / WS
┌─────────────────────┴────────────────────────────────────────────┐
│  Frappe site                                                      │
│   conductor/api/dashboard.py        — whitelisted endpoints       │
│   conductor/messages.py             — emit_job_event() helper     │
│   conductor/dispatcher.py           — emits at QUEUED             │
│   conductor/worker.py               — emits at RUNNING / SUCCEEDED│
│                                       FAILED / SCHEDULED_RETRY /  │
│                                       DLQ                         │
│   conductor/cancellation.py         — emits at CANCELLED          │
│   conductor/conductor/doctype/...   — unchanged (no schema work)  │
└───────────────────────────────────────────────────────────────────┘
```

**No DocType schema changes.** All six dashboard doctypes already exist and have `Conductor Operator` granted `read:1` (verified). No fields added or modified in Phase 3.

---

## 4. Routing and URL scheme

```
#/                    → redirect to #/overview
#/overview            → OverviewPage          (full-width grid; no detail)
#/feed                → FeedPage              (single-column live stream; no detail)
#/jobs                → JobsPage              (master only)
#/jobs/:job_id        → JobsPage              (master + detail)
#/dlq                 → DlqPage               (master only)
#/dlq/:entry_name     → DlqPage               (master + detail)
#/schedules           → SchedulesPage         (master only)
#/schedules/:name     → SchedulesPage         (master + detail)
#/workers             → WorkersPage           (master only)
#/workers/:worker_id  → WorkersPage           (master + detail)
```

Hash mode chosen because `www/` does not get a Frappe history-fallback handler and hash never round-trips to the server.

---

## 5. Project layout

```
apps/conductor/
  dashboard/                         # NEW — standalone vite project (HRMS-roster pattern)
    package.json                     # vue@3.5, vue-router@4, frappe-ui, vite, @vitejs/plugin-vue
    vite.config.js                   # base=/assets/conductor/dashboard/
    index.html
    src/
      main.js                        # createApp + router + frappe-ui plugin
      router.js                      # hash routes per §4
      api.js                         # wraps frappe.call; JSON-safety helpers
      realtime.js                    # wraps frappe.realtime.on with auto-cleanup
      App.vue                        # top-tabs + <router-view>
      pages/
        OverviewPage.vue
        FeedPage.vue
        JobsPage.vue
        DlqPage.vue
        SchedulesPage.vue
        WorkersPage.vue
      components/
        StatusBadge.vue
        JsonViewer.vue
        QueueChart.vue
        RetryButton.vue
        ConfirmDialog.vue            # only if frappe-ui's doesn't fit
      stores/
        useDashboardState.js         # composable for the 2 s polling snapshot
        useDetailSubscription.js     # composable for per-entity realtime subscription

  conductor/
    api/                             # MIGRATED — `conductor/api.py` becomes a package
      __init__.py                    # MIGRATED — verbatim contents of the old `conductor/api.py` (re-exports `enqueue`, `context`, `job`, `RetryPolicy`, `cancel`); preserves the existing public surface
      dashboard.py                   # NEW — whitelisted endpoints (§7)
    messages.py                      # MODIFIED — add emit_job_event() helper (§8.4)
    dispatcher.py                    # MODIFIED — replace global event with per-job (§8)
    worker.py                        # MODIFIED — emit per-job events at transitions (§8)
    cancellation.py                  # MODIFIED — emit per-job CANCELLED event
    public/dashboard/                # NEW (build output; gitignored; bench-build runs vite)
    www/
      conductor-dashboard.html       # NEW (post-build copy of dashboard/dist/index.html)
```

`bench build` already shells to each app's build script. We add a build script entry to `apps/conductor/package.json` (or to its own `apps/conductor/dashboard/package.json` invoked by bench's per-app build hook — to be confirmed in Task 1 spike).

---

## 6. Permissions enforcement

**Source of truth: server.** Every whitelisted endpoint guards itself.

```python
# conductor/api/dashboard.py
def _require_read():
    if not (frappe.has_permission("Conductor Job", "read")
            or "Conductor Operator" in frappe.get_roles()):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

def _require_destructive():
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("System Manager only"), frappe.PermissionError)
```

**Frontend hides destructive buttons** for non-SysMgr users by reading `frappe.boot.user.roles`. UX polish only — server enforces the rule.

**Page-level access:** `www/conductor-dashboard.html` is served to any authenticated user. The SPA's first call is `get_state`; on 403 it shows a "no access" page with a link back to `/app`. Anonymous users hit Frappe's stock login redirect.

**No DocType perm changes.** All six dashboard doctypes already grant `Conductor Operator` `read:1` and (mostly) `report:1, export:1`:
| DocType | Operator perms |
|---|---|
| `Conductor Job` | read, report, export |
| `Conductor Job Run` | read, report, export |
| `Conductor DLQ Entry` | read, report, export |
| `Conductor Queue` | read, report, export |
| `Conductor Schedule` | read, report, export |
| `Conductor Worker` | read, report |

---

## 7. Server API surface

All endpoints in `conductor/api/dashboard.py`, all `@frappe.whitelist()`, all guard via `_require_read()` or `_require_destructive()`.

| Endpoint | Purpose | Perm | Notes |
|---|---|---|---|
| `get_state()` | Single snapshot for the 2 s polling loop | read | See §7.1 |
| `get_job(job_id)` | Full job detail incl. `Conductor Job Run` history, decoded args/kwargs, traceback, trace_id, sentry_url | read | |
| `retry_job(job_id)` | Re-enqueue (uses existing `conductor.enqueue` path) | Operator+ | Resets attempt to 1 |
| `cancel_job(job_id)` | Wraps existing `conductor.cancellation.cancel(job_id)` | Operator+ | |
| `get_dlq_entry(name)` | Detail incl. decoded payload + `is_json_safe` flag | read | |
| `dlq_retry(entry_names: list[str])` | Bulk retry-as-is | Operator+ | Marks entries `RETRIED` |
| `dlq_discard(entry_names: list[str])` | Mark entries `DISCARDED` | **System Manager** | |
| `dlq_edit_and_retry(name, args_json, kwargs_json)` | Re-encode JSON to msgpack, dispatch | **System Manager** | Server-side decode-edit-encode round-trip rejection if msgpack bytes drift |
| `schedule_run_now(name)` | Existing `bench conductor schedule run-now` logic | Operator+ | Does not bump `last_run_at` (per Phase 2 hand-off §3.5) |
| `schedule_set_enabled(name, enabled: bool)` | Toggle `Conductor Schedule.enabled` | **System Manager** | |
| `get_worker(worker_id)` | Detail + recent N jobs handled | read | |
| `get_schedule_next_fires(name, count=10)` | Compute next N fires via `croniter` | read | |

**List reads (jobs, dlq, schedules, workers, queues) use `frappe.client.get_list` directly from the SPA**, not custom endpoints. Reason: pure pass-through reads that already respect DocType perms; no joins or computed fields needed. Custom endpoints are reserved for `get_state` (Redis + SQL composition), `get_worker` (heartbeat-age computation in UTC), and mutations.

### 7.1 `get_state()` payload

```json
{
  "queues": [
    {"name": "default", "enabled": true,
     "depth_redis": 12, "scheduled_count": 3, "dlq_count": 1,
     "throughput_1h": 248, "error_rate_1h": 0.012}
  ],
  "worker_summary": {"alive": 4, "stale": 0, "gone": 1, "total": 5},
  "dlq_summary": {"pending_review": 2, "retried": 14, "discarded": 5},
  "schedule_summary": {
    "enabled_count": 7,
    "next_5": [{"name": "report-daily", "cron": "0 8 * * *", "next_run_at": "2026-04-29T08:00:00Z"}]
  },
  "feed_recent": [
    {"job_id": "abc-...", "method": "...", "queue": "default",
     "status": "FAILED", "attempt": 3, "ts": "2026-04-28T10:23:00Z"}
  ],
  "config": {"poll_interval_ms": 2000}
}
```

`feed_recent` is the last 50 jobs by `enqueued_at desc`. The Feed tab consumes it directly — no separate poll. Single endpoint, single query budget per tick.

### 7.2 Polling configurability

Default 2000 ms. Configurable via `site_config.json`:

```json
{ "conductor": { "dashboard_poll_interval_ms": 2000 } }
```

Returned in `get_state().config.poll_interval_ms`; SPA reads on first response and adjusts the polling timer.

---

## 8. Realtime event taxonomy

### 8.1 What needs realtime, and what doesn't

The polling layer is adequate for everything that changes slowly: schedules (cron-cadence), workers (5 s heartbeats), DLQ entries (operator-mediated). Jobs are the only fast-transitioning entity (QUEUED→RUNNING→SUCCEEDED can happen in milliseconds), and that is where sub-2 s latency actually matters.

**v1 ships one event family**: `conductor:job:{job_id}`. Schedules / workers / DLQ rely on polling.

This is a deliberate trim from the hand-off §5.1 wishlist (which named `schedule_fired`, etc.). Once polling owns aggregates, those events lose their primary consumer.

### 8.2 Event firing sites

| File + function | Status emitted |
|---|---|
| `conductor/dispatcher.py:223` (replaces existing global `conductor:job_queued`) | `QUEUED` |
| `conductor/worker.py:_set_job_running` (line 111) | `RUNNING` |
| `conductor/worker.py:_set_job_succeeded` (line 121) | `SUCCEEDED` |
| `conductor/worker.py` FAILED-terminal path (around line 380) | `FAILED` |
| `conductor/worker.py:_schedule_retry` (line 162) | `SCHEDULED_RETRY` |
| `conductor/worker.py:_move_to_dlq` (line 181) | `DLQ` |
| `conductor/cancellation.py:cancel` (line 28) | `CANCELLED` |

### 8.3 Payload shape (delta, not full record)

```json
{
  "job_id": "abc-123-uuid",
  "status": "FAILED",
  "attempt": 3,
  "max_attempts": 3,
  "queue": "default",
  "method": "ledger.sync_invoice",
  "last_error_type": "TimeoutError",
  "last_error_message": "Connection refused",
  "finished_at": "2026-04-28T10:23:45Z",
  "next_run_at": null,
  "ts": 1714299825
}
```

`last_traceback` is **not** in the realtime payload (can be tens of KB). The detail pane re-fetches `get_job(job_id)` on receipt of a terminal-state transition (FAILED / DLQ / SUCCEEDED) to load the traceback / result_preview.

### 8.4 Server emit helper

Added to existing `conductor/messages.py`:

```python
def emit_job_event(job_id: str, status: str, **fields) -> None:
    payload = {"job_id": job_id, "status": status, "ts": int(time.time()), **fields}
    frappe.publish_realtime(
        event=f"conductor:job:{job_id}",
        message=payload,
        doctype="Conductor Job",       # delivery scope: doc:Conductor Job/{job_id}
        docname=job_id,                # see §8.6.1 — event= alone is just a label
        after_commit=True,             # avoids stale-read races on detail re-fetch
    )
```

`doctype` + `docname` are the **delivery-scope** parameters; without them events broadcast to the site-wide `"all"` room (see §8.6.1 for the spike that uncovered this). `after_commit=True` is critical: without it, the SPA can receive a "RUNNING" event and immediately re-fetch `get_job`, only to read the still-uncommitted QUEUED row.

### 8.5 Frontend subscription pattern

```js
// pages/JobsPage.vue, on entering #/jobs/:job_id
import { useDetailSubscription } from '../stores/useDetailSubscription'

const { data, unsubscribe } = useDetailSubscription(
    'Conductor Job',                  // doctype — joins room doc:Conductor Job/{id}
    'conductor:job',                  // event-name prefix
    job_id,
)
onBeforeUnmount(unsubscribe)
```

`useDetailSubscription` (a) calls `frappe.realtime.doc_subscribe(doctype, docname)` to join the per-doc room, (b) calls `frappe.realtime.on(eventName, cb)` to listen for the event-name label, (c) on unmount calls `doc_unsubscribe` + `off`, and (d) auto-refetches the full record on terminal-state transitions to load the traceback.

### 8.6 Pre-implementation spike (Task 1 of plan)

**Confirm `frappe.publish_realtime(event="conductor:job:abc", message={...}, after_commit=True)` actually delivers only to clients with `frappe.realtime.on("conductor:job:abc", ...)` and not as a site-wide broadcast in Frappe 15.106.0.** If broadcast-only, the bandwidth model still works (clients filter by event name) but it informs the test design. ~30 minutes of investigation.

### 8.6.1 Spike Findings (2026-04-28)

**How `publish_realtime` scopes delivery.** When called with only `event=` and `message=` (no `room=`, `user=`, `doctype=`, or `docname=`), Frappe's Python layer falls through to the final else-branch at `realtime.py:69–71` and sets `room = get_site_room()`, which returns the string `"all"` (`realtime.py:158–159`). That room string, together with the event name and the site namespace, is then published to Redis as a JSON payload (`realtime.py:100–115`). On the Node side (`realtime/index.js:51–52`), the subscriber reads this payload and calls `io.of(namespace).to(message.room).emit(message.event, message.message)` — a standard Socket.IO room-targeted emit. The event name (`message.event`) is therefore the Socket.IO *event name* used in the emit, while `message.room` is the Socket.IO *room* that scopes which connected sockets receive it. Every System User socket is auto-joined to the `"all"` room at connection time (`realtime/handlers/frappe_handlers.js:11–13`), so a call with no explicit room delivers to **all Desk users on the site**. There is no per-event-name room; the event name is only a label carried inside the Socket.IO payload and matched by the client's `frappe.realtime.on("conductor:job:abc", cb)` listener.

**Implication for this design.** The plan to use `event=f"conductor:job:{job_id}"` alone as the scoping mechanism does **not** limit delivery to operators viewing that specific job — it broadcasts to every connected Desk user and relies on each client's listener registration to filter. This is the "broadcast-only, client-filtered" worst case described in §8.6. The bandwidth model remains valid (messages are small, volume is bounded by the scheduler's tick rate), but three adjustments are required:

1. **Per-job events:** Pass `doctype="Conductor Job", docname=job_id` to `publish_realtime` (the public API form; `realtime.py:67–68` computes `get_doc_room(doctype, docname)` = `"doc:Conductor Job/{job_id}"` internally). Do **not** pass the raw room string directly — that couples Conductor to an internal naming convention. The dashboard page must emit `frappe.realtime.trigger("doc_subscribe", {doctype, docname})` on mount and `doc_unsubscribe` on unmount to join/leave that room.

2. **List-view events:** The overview and list pages that need live row updates should use `event="list_update"` with `doctype="Conductor Job"`. Frappe's special-case handler at `realtime.py:52–54` routes these to `doctype:Conductor Job` automatically, and all users subscribed to that doctype receive them. Do **not** invent a custom `event="conductor:job:list"` name without an explicit room — it would broadcast to all Desk users exactly as the per-job case would have.

3. **Chaos-test assertions:** The monkeypatch approach (capture `frappe.publish_realtime` call args) remains the right technique, but the tests **must** assert that `doctype` and `docname` (or an explicit `room=`) are present on each captured call. An assertion that only checks `event=` would miss the precise bug this spike exposed.

---

## 9. Section-by-section content

### 9.1 Overview (full-width grid; exception to master/detail)

**Layout:** 4-up number cards (top row) + 2-up charts (bottom row).

**Number cards:**
- Total queue depth (sum of Redis `XLEN` across all queues)
- Jobs/min last 1 h (SQL count)
- Error rate last 1 h (FAILED + DLQ ÷ all-terminal)
- DLQ pending review

**Charts (frappe-ui chart wrapper or `frappe.Chart`):**
- Queue depth by queue (horizontal bar; current snapshot)
- Throughput last 24 h (line; per-hour SUCCEEDED count)

**Drill-through:** clicking a card / chart navigates to the relevant filtered view (DLQ card → `#/dlq`, error-rate card → `#/jobs?status=FAILED`).

**Actions:** none.
**Perm gate:** read.

### 9.2 Live Feed (single-column scroll; exception to master/detail)

**Layout:** vertical timeline, newest at top, ~80 visible rows. "Pause on hover" enabled by default (Sentry-style — a row the operator is reading is not pushed off-screen).

**Each row:** timestamp · status badge · queue · method · job_id (clickable → `#/jobs/<job_id>`).

**Data source:** `feed_recent` from polling snapshot (last 50 jobs).

**Actions:** click row → drill to Jobs detail.
**Perm gate:** read.

### 9.3 Jobs (master/detail split)

**Master pane:**
- Filters bar: queue (multi-select), status (multi-select), method (text search), time range, idempotency_key.
- Sortable columns: enqueued_at (default desc), method, queue, status, attempt.
- Paginated, 50 per page.
- Status badge colors: green = SUCCEEDED; blue = RUNNING; yellow = QUEUED / SCHEDULED_RETRY; red = FAILED / DLQ / TIMED_OUT; grey = CANCELLED.
- Reads via `frappe.client.get_list("Conductor Job", filters=..., fields=...)`.

**Detail pane (`#/jobs/:job_id`):**
- Header: status · method · attempt N/M · queue · enqueued_at · started_at · finished_at.
- Sub-tabs: **Overview / Runs / Args / Trace**.
  - **Overview:** `last_error_message`, `last_error_type`, `last_traceback` (collapsible, monospace), action buttons.
  - **Runs:** timeline of `Conductor Job Run` rows — attempt #, started/finished, duration, status, error_type, traceback.
  - **Args:** decoded `args` + `kwargs` from msgpack → JSON pretty-print. Read-only.
  - **Trace:** `trace_id` with copy + external link if `conductor.trace_url_template` is configured. `sentry_url` if present (Phase 4 fields; show empty placeholder otherwise).
- Subscribes to `conductor:job:{job_id}` for live updates while open.

**Actions in detail:**
- **Retry** (Operator+) — calls `retry_job(job_id)`. Available for FAILED / TIMED_OUT / DLQ / CANCELLED.
- **Cancel** (Operator+) — calls `cancel_job(job_id)`. Available for QUEUED / RUNNING / SCHEDULED_RETRY.

**Perm gate:** read for view; Operator+ for actions.

### 9.4 DLQ (master/detail with multi-select)

**Master pane:**
- Filters: queue, method, status (PENDING_REVIEW / RETRIED / DISCARDED), date range.
- Checkbox column for multi-select.
- Bulk-action bar (appears when 1+ selected): **[Retry selected] [Discard selected] [Edit & retry…]** (last is enabled only when exactly 1 selected AND payload is JSON-safe; tooltip explains otherwise).
- Reads via `frappe.client.get_list("Conductor DLQ Entry", ...)`.

**Detail pane (`#/dlq/:entry_name`):**
- Header: queue · method · attempts · last_error_type · moved_at · status.
- Sections:
  - **Last error:** `last_error_message` + `last_traceback`.
  - **Original payload:** decoded args + kwargs. JSON-safety badge ("JSON-safe ✓" or "Contains datetime / Decimal / bytes — edit-and-retry not available").
  - **Linked job:** `Conductor Job` link (`#/jobs/<job_id>`).
  - **Review notes:** `reviewed_by`, `reviewed_at`, `review_notes` (free-text; editable by SysMgr only).

**Actions:**
- **Retry as-is** (Operator+) — `dlq_retry([entry_names])` re-enqueues original payload via `conductor.enqueue`; marks entry RETRIED.
- **Discard** (SysMgr) — `dlq_discard([entry_names])` marks DISCARDED; no Redis side effects.
- **Edit & retry** (SysMgr; JSON-safe payloads only) — modal with `<textarea>` containing JSON of args + kwargs. On Save: `dlq_edit_and_retry(name, args_json, kwargs_json)` validates JSON-safety server-side, re-encodes to msgpack, dispatches.

Confirmation dialogs on bulk actions: "Retry 4 entries?" / "Discard 4 entries? This cannot be undone."

**Perm gate:** read for view; Operator+ for retry; SysMgr for discard / edit-and-retry.

### 9.5 Schedules (master/detail)

**Master pane:**
- Columns: name, cron_expression, timezone, next_run_at, last_status (dispatch outcome), last_run_at, enabled toggle.
- Enabled toggle: disabled control for Operator (read-only); functional for SysMgr (calls `schedule_set_enabled`).
- Per-row "Run now" button (Operator+).
- Reads via `frappe.client.get_list("Conductor Schedule", ...)`.

**Detail pane (`#/schedules/:name`):**
- Header: name · cron · timezone · enabled (with same role-gated toggle).
- Sections:
  - **Last dispatch:** `last_status` badge (DISPATCHED / DISPATCH_FAILED) + `last_run_at`. *Dispatch outcome*, not job outcome.
  - **Last job:** `last_job` link + the linked job's terminal status. Both rows are visible — not conflated.
  - **Next 10 fires:** computed via `get_schedule_next_fires(name, 10)`.
  - **Recent 20 runs:** `frappe.client.get_list("Conductor Job", filters={"method": <schedule.method>, ...}, order_by="enqueued_at desc", limit=20)`. Heuristic — same method called by multiple schedules will be conflated; v1 limitation noted in §11 risk #5.
  - **Mini calendar:** 4-week CSS-grid showing days with scheduled fires as dots. No calendar lib.

**Actions:**
- **Run now** (Operator+) — `schedule_run_now(name)`. Tooltip: "Dispatches now; cron cadence is unaffected."
- **Enable / Disable** (SysMgr) — `schedule_set_enabled(name, bool)`.
- **Create / edit / delete** schedules: out of scope; operators use Frappe's stock List View on `Conductor Schedule`.

**Perm gate:** read for view; Operator+ for run-now; SysMgr for enable/disable.

### 9.6 Workers (master/detail; observability only)

**Master pane:**
- Columns: status (ALIVE/STALE/GONE colored badge), worker_id, host, pid, queues, last_heartbeat, heartbeat-age.
- Sort: status (ALIVE first), then heartbeat-age asc.
- Reads via `frappe.client.get_list("Conductor Worker", ...)`.

**Detail pane (`#/workers/:worker_id`):**
- Header: status · worker_id · host:pid · queues (JSON list pretty) · started_at · conductor_version.
- Sections:
  - **Currently executing:** `current_job` link if set + that job's status.
  - **Recent N jobs handled:** `frappe.client.get_list("Conductor Job", filters={"worker_id": ...}, order_by="finished_at desc", limit=20)`.
  - **Heartbeat age:** computed live (refreshed on poll tick).

**Actions:** none. No force-kill, no "evict from queue".
**Perm gate:** read.

---

## 10. Testing strategy

Three layers, matching hand-off §6.

### 10.1 Unit tests (`tests/`)

New file: `tests/test_api_dashboard.py`. Coverage matrix per endpoint:
- Anonymous → 401
- Conductor Operator allowed action → 200
- Conductor Operator denied destructive action → 403
- System Manager → 200

JSON-safety helper: golden tests with msgpack-encoded `datetime`, `Decimal`, `bytes`, plain `dict[str, str|int|float|bool|None]` — confirm `is_json_safe(payload)` returns False for the first three, True for the fourth.

Realtime emit helper: monkeypatch `frappe.publish_realtime`, call `emit_job_event(...)`, assert captured call has `event="conductor:job:{id}"`, `after_commit=True`, expected payload shape.

### 10.2 DocType tests (`conductor/conductor/doctype/<x>/test_*.py`)

No additions or changes — Phase 3 ships no DocType schema changes.

### 10.3 Chaos tests (`tests_chaos/`)

New file: `tests_chaos/test_realtime_events.py` — dispatch a job that goes QUEUED → RUNNING → FAILED → DLQ; assert exactly the expected sequence of `conductor:job:{id}` events arrives, in order, with `after_commit=True` semantics (no events fire before DB commit).

The exact subscription mechanism (real socketio client vs monkeypatched `frappe.publish_realtime` capture vs Redis pub/sub channel sniff — Frappe forwards realtime through Redis) is determined by §8.6 spike. Frappe does not ship a dedicated socketio test client, so the most likely shape is monkeypatch + ordering assertions.

### 10.4 Manual UI verification (exit criterion sign-off)

Operator user, dashboard URL bookmark → kill a job mid-execution from `bench console` → find it via `#/jobs?status=FAILED` → click into detail → see traceback → click Retry → watch it succeed. **All without SSH or `bench console` after the kill.**

---

## 11. Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | Frappe 15.106.0 socketio room targeting may not scope as intended | §8.6 spike as Task 1 of implementation; bandwidth model still works either way |
| 2 | `frappe-ui` version compatibility with Frappe 15.106.0 | Pin to HRMS roster's version (`0.1.105` per its package.json); same bench, same Frappe version |
| 3 | `vite build` integration with `bench build` | HRMS roster does this exact pattern; copy verbatim |
| 4 | JSON-safety gate could be bypassed if the gate logic is wrong | Two layers: (a) the SPA only enables "Edit & retry" when the server returned `is_json_safe: true` for the entry; (b) `dlq_edit_and_retry` re-decodes the **original** payload server-side and rejects the request if the original contained any non-JSON-native type — even if the SPA mistakenly enabled the button. The submitted JSON is then parsed and dispatched via `conductor.enqueue` like any normal dispatch (no special msgpack handling needed because all values are JSON-native by gate construction) |
| 5 | Schedules "recent runs" approximation (job lookup by method name) is wrong if same method is called by multiple schedules | Acceptable v1 limitation; right fix is a `Conductor Job.schedule` link field — defer to Phase 3.5 / 4 |
| 6 | Hand-rolled mini calendar gets gnarly if operators want month/year view | Defer; operators with that need have Frappe's stock Calendar View on `Conductor Schedule.next_run_at` already |
| 7 | Polling load: 2 s × N concurrent tabs on `get_state` against Redis + SQL | `get_state` should be sub-100 ms; 10 tabs × 0.5 req/s = 5 req/s — trivial. Configurable in `site_config.json` if needed |
| 8 | Replacing global `conductor:job_queued` is a breaking change for any external consumer | Documented in §13 change-log |
| 9 | Master §3 cross-cutting frozen decisions | None violated. No new DocTypes, no schema changes, no Redis topology changes, no stream message format changes |

---

## 12. Out of scope (Phase 3)

- Workflows section — Phase 5
- Charts/metrics from a real time-series source — Phase 4 (OTel / Prometheus)
- Pool workers / per-tenant rate limits — Phase 6
- Force-kill workers — needs Redis signal mechanism
- Schedule create / edit / delete via dashboard — operators use Frappe stock List View
- Job-level edit-and-retry (only DLQ has it)
- Custom roles beyond System Manager + Conductor Operator (three-tier rejected in brainstorm Q3)
- Mobile-responsive layout
- i18n

---

## 13. Master design changes

This Phase 3 spec triggers two updates to the master:

1. **§3 #11 (UI delivery wording)** — master §4 says "single-file Vue 3 SFC, embedded as a Frappe Page DocType". Add a footnote to master §4 that Phase 3 settled the UI delivery as `www/` route + standalone vite project (HRMS roster pattern), not Page DocType. The "Vue 3 SFC" wording stays accurate.

2. **§9 stable-contract row "Real-time dashboard events"** — the master already lists this as becoming stable from Phase 3. Append: "Event family: `conductor:job:{job_id}` only; aggregates use polling. Existing global `conductor:job_queued` is replaced (breaking change)."

Both edits are minor and can be made when the Phase 3 plan starts execution.

---

## 14. Implementation task ordering hint

Roughly the order the writing-plans skill should structure the plan in. Detailed plan to be written by writing-plans next.

1. **Spike** — verify `publish_realtime` room targeting in Frappe 15.106.0 (§8.6).
2. **Spike** — verify `vite build` + `bench build` integration; produce a hello-world `www/conductor-dashboard.html` that renders a Vue 3 component (no router yet).
3. **Server: messages helper** — add `emit_job_event` to `conductor/messages.py` + unit tests.
4. **Server: emit at every transition** — modify `dispatcher.py`, `worker.py`, `cancellation.py` to call the helper. Replace the global `conductor:job_queued` broadcast.
5. **Server: api package + dashboard.py** — convert `conductor/api.py` to `conductor/api/__init__.py` (verbatim contents; existing imports `from conductor.api import enqueue` keep working). Add `conductor/api/dashboard.py` with `get_state`, `get_job`, `retry_job`, `cancel_job`, `get_dlq_entry`, `dlq_retry`, `dlq_discard`, `dlq_edit_and_retry`, `schedule_run_now`, `schedule_set_enabled`, `get_worker`, `get_schedule_next_fires`. Each with permission test cases.
6. **Frontend: project scaffold** — `dashboard/` vite project, top-tab nav, hash-mode router, Overview placeholder.
7. **Frontend: Live Feed** + polling skeleton (uses `feed_recent`).
8. **Frontend: Jobs** master + detail (with realtime subscription).
9. **Frontend: DLQ** master + detail + bulk actions + edit-and-retry modal.
10. **Frontend: Schedules** master + detail.
11. **Frontend: Workers** master + detail.
12. **Frontend: Overview** number cards + charts.
13. **Permissions polish** — frontend role-based button hiding.
14. **Chaos test** — `test_realtime_events.py`.
15. **Exit-criterion manual demo** — sign-off.

---

## 15. Phase 3 hand-off notes (carry-forward to Phase 4)

To be filled in at the end of Phase 3 implementation, not now.

---

## Change Log

| Date | Change | Author |
|---|---|---|
| 2026-04-28 | Initial Phase 3 dashboard spec. Refines master §4 in three ways: UI delivery is `www/` route (not Page DocType — see §2 #3); realtime events trimmed to per-job only (§8.1); DLQ edit-and-retry gated on JSON-safety (§9.4). | osama.m@aau.iq |
