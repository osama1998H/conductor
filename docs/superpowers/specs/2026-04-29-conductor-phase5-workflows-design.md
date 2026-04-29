# Conductor Phase 5 — Workflows (Design)

**Status:** Draft for approval
**Date:** 2026-04-29
**Author:** osama.m@aau.iq
**Phase:** 5 of master roadmap (Workflows). Phase 4 was Observability and was removed; Phase 6 (Multi-tenant polish) follows.
**Master:** `docs/superpowers/specs/2026-04-27-conductor-master-design.md`

This spec refines, but does not relitigate, the master design. DocType schemas (master §6.7–6.9), the advancer pattern (master §4 Phase 5), the compensation rule, the "pin definition snapshot at run start" rule (master §3 #20), and the exit criterion are all frozen there.

---

## 1. Scope

Phase 5 adds DAG workflows with compensations on top of the reliability core (Phases 0–2) and the dashboard (Phase 3). Workflows are declared as Python classes; their steps are dispatched through the existing `Conductor Job` pipeline, so each step inherits Phase-1 retry/idempotency/DLQ semantics and Phase-3 realtime visibility for free.

**v1 scope (this phase):**

- Class-decorator workflow definition with declarative `Step` attributes.
- `conductor.run_workflow(...)` Python API + CLI.
- Three new DocTypes: `Conductor Workflow`, `Conductor Workflow Run`, `Conductor Workflow Step Run`.
- Forward execution via an advancer job using a single-key Lua script for atomic fan-in.
- Compensation in reverse topological order, executed as separate Conductor jobs.
- Auto-detected topology versioning with deterministic hash.
- Read-only dashboard tab with Mermaid DAG visualization plus a `Cancel run` action.
- Best-effort cancellation; no automatic compensation on cancel.

**Explicitly out of scope (Q&A locked):**

- Step-to-step data passing — steps coordinate via Frappe state.
- Workflow editing or triggering from the dashboard.
- `bench conductor workflow show` (DAG dump) and `enable`/`disable` CLI.
- Sub-workflows.
- Manual single-step compensation trigger.
- Retry-from-failed-step (operator re-runs whole workflow with the same idempotency key).

---

## 2. Cross-Phase Reference Map

| Frozen contract | Where | Used here |
|---|---|---|
| `Conductor Job.workflow_run_id` and `step_id` columns | Master §6.2 | Populated by `run_workflow` and the advancer; read by worker hooks |
| Stream message `workflow_run_id` and `step_id` keys | Master §7 | Same |
| Per-job realtime room scoping | Master §9 / Phase 3 §8 | New events follow the same `doctype`/`docname` pattern, scoped to `Conductor Workflow Run` |
| `conductor.enqueue` and `RetryPolicy` | Phase 1 | Steps and compensations are enqueued via this API; nothing bypasses the pipeline |
| Single-key Lua scripts only | Master §3 #15 | Fanin-decrement script operates on a single `wfdeps:{run_id}` key |
| Site-bound workers | Master §3 #14 | Workflow runs are per-site; Redis keys carry `{site}` already |

---

## 3. Architecture

A workflow is a class decorated with `@conductor.workflow(name=..., queue=...)`. Class-level attributes are `Step(...)` declarations carrying `depends_on` and an optional `compensation` method name; step bodies are normal methods on the class. Triggering a run goes through `conductor.run_workflow(...)`, which:

1. Imports the class and computes a deterministic topology hash.
2. Compares the hash to the latest `Conductor Workflow.definition_snapshot`. If different, increments `version` and writes the new snapshot before continuing.
3. Acquires an idempotency lock (24h TTL by default) keyed on a caller-supplied `idempotency_key`.
4. Inserts a `Conductor Workflow Run` row pinned to the new `definition_version`, with `input_args` / `input_kwargs` frozen.
5. Inserts one `Conductor Workflow Step Run` row per step in the snapshot, status `PENDING` (so the dashboard always shows the full topology, and cancellation has rows to flip to `SKIPPED`).
6. Seeds a Redis hash `conductor:{site}:wfdeps:{run_id}` of `step_id -> remaining_deps_count` from the pinned snapshot.
7. Enqueues an advancer job on the `workflow` queue.

The advancer atomically decrements the deps counter via a single-key Lua script, gets back the set of steps whose remaining count reached zero, inserts a `Conductor Workflow Step Run` row per ready step, and `conductor.enqueue`s each as a regular Conductor Job (with `workflow_run_id` and `step_id` populated).

When a step's job reaches a terminal state, `conductor/worker.py` checks `job.workflow_run_id` and either (a) on success: enqueues another advancer, or (b) on terminal failure (job landed in DLQ): enqueues a compensator.

The compensator walks completed steps in reverse topological order, enqueues one compensation job at a time, and waits for each to terminate before continuing. If a compensation itself fails terminally, the run halts in `FAILED` and earlier completed steps are not unrolled — operator triages from the dashboard.

Cancellation is best-effort: dashboard or API marks the run `CANCELLED`, the advancer stops dispatching, in-flight step jobs receive the existing Phase-1 cancellation signal. Completed work is left in place — no automatic compensation on cancel.

---

## 4. Components

| Path | Purpose |
|---|---|
| `conductor/workflow/__init__.py` | Public API surface: `workflow`, `Step`, `run_workflow`, `WorkflowDefinitionError` |
| `conductor/workflow/decorator.py` | `@workflow` class decorator; `Step` dataclass; in-process registry of decorated classes |
| `conductor/workflow/snapshot.py` | Topology hashing (canonical JSON, sorted) and snapshot serialization |
| `conductor/workflow/dispatcher.py` | `run_workflow(...)`: version-bump check, idempotency, run row insert, deps-hash seed, advancer enqueue |
| `conductor/workflow/advancer.py` | Unified advancer job entry-point (branches on `run.status`; serves both forward and compensation paths). Decorated with `@conductor.job(queue="workflow")`. |
| `conductor/workflow/lua.py` | Single-key Lua scripts: `fanin_decrement` |
| `conductor/workflow/topo.py` | Cycle detection at decoration time; reverse-topological order computation |
| `conductor/worker.py` *(edit)* | After step terminal state, hook into advancer / compensator enqueue |
| `conductor/conductor/doctype/conductor_workflow/...` | DocType + controller (read-only validation: `definition_snapshot` is system-managed) |
| `conductor/conductor/doctype/conductor_workflow_run/...` | DocType + controller; `cancel` whitelisted method |
| `conductor/conductor/doctype/conductor_workflow_step_run/...` | DocType + controller (read-only) |
| `conductor/api/workflows.py` | Dashboard whitelisted endpoints |
| `conductor/commands/workflow.py` | `bench conductor workflow {list,run,status,cancel}` |
| `dashboard/src/pages/WorkflowsPage.vue` + `WorkflowRunDetailPage.vue` | UI tab #7 with Mermaid renderer |
| `tests/test_workflow_*.py` | Unit + Frappe-integration tests |
| `tests_chaos/test_phase5_chaos.py` | Phase 5 chaos suite |

The `conductor/workflow/` subpackage mirrors `conductor/api/`'s split-out style — a feature with 4+ files becomes its own subpackage rather than top-level files.

---

## 5. Public API

### 5.1 Definition

```python
from conductor.workflow import workflow, Step

@workflow(name="OrderFulfillment", queue="default")
class OrderFulfillment:
    a = Step("reserve", depends_on=[], compensation="release")
    b = Step("charge",  depends_on=["a"], compensation="refund")
    c = Step("notify",  depends_on=["a"])
    d = Step("receipt", depends_on=["b", "c"])

    def reserve(self, *, order_id): ...
    def release(self, *, order_id): ...   # compensation for reserve
    def charge(self,  *, order_id): ...
    def refund(self,  *, order_id): ...   # compensation for charge
    def notify(self,  *, order_id): ...   # no compensation
    def receipt(self, *, order_id): ...   # no compensation
```

`Step` is a frozen dataclass:

```python
@dataclass(frozen=True)
class Step:
    name: str                       # unique step id within the workflow
    depends_on: tuple[str, ...] = ()
    compensation: str | None = None # method name on the same class
```

**Decorator-time validation** raises `WorkflowDefinitionError` when:

- A step's `name` is not a method on the class.
- A step's `compensation` is set but the named method does not exist.
- `depends_on` references a step that doesn't exist.
- The DAG contains a cycle.
- Two `Step` attributes share the same `name`.

The decorator registers the class in an in-process registry keyed by the workflow name. `frappe.get_attr(definition_path)` resolves the class at dispatch time.

### 5.2 Step inputs

Step methods receive the run's frozen `input_args` and `input_kwargs` only — no return values from upstream steps are auto-injected (locked decision: no automatic data flow). If a step needs data produced by an upstream step, the upstream writes it to Frappe (a doc, a temp record, a custom field) and the downstream reads it.

The worker exposes the run id during step execution via `frappe.local.conductor_workflow_run_id` (set before invocation, cleared after) so steps that need run-context can find it without changing their signature.

### 5.3 Triggering

```python
import conductor

run_id = conductor.run_workflow(
    "OrderFulfillment",
    order_id=42,
    idempotency_key="ord-42-fulfill",   # optional; if omitted, no idempotency
)
```

Behavior:

- Synchronous; returns the new (or idempotency-deduplicated) `run_id`.
- Validates that the named workflow is registered.
- Triggers the version-bump check before inserting the run row.
- The run starts in status `PENDING`; the advancer flips it to `RUNNING` on first dispatch.

### 5.4 Cancellation

```python
conductor.cancel_workflow_run(run_id)         # Python API
# or via dashboard / `bench conductor workflow cancel <run_id>`
```

- Marks `Conductor Workflow Run.status = CANCELLED`.
- Marks any step runs in `PENDING` or `READY` as `SKIPPED`.
- Calls the existing Phase-1 `cancel_job(job_id)` for any step run currently in `RUNNING`.
- Does **not** trigger compensation. Completed steps stay completed.

### 5.5 CLI

```
bench --site SITE conductor workflow list
bench --site SITE conductor workflow run <name> [--args=JSON] [--kwargs=JSON] [--idempotency-key=KEY]
bench --site SITE conductor workflow status <run_id>
bench --site SITE conductor workflow cancel <run_id>
```

Mirrors the existing `bench conductor schedule` command shape (Phase 2). No `show`, `enable`, or `disable` subcommands in v1 (locked).

### 5.6 Whitelisted dashboard endpoints

- `conductor.api.workflows.list_workflows` — list registered workflows + active/recent run counts.
- `conductor.api.workflows.list_runs(workflow=None, status=None, limit, offset)` — paginated runs.
- `conductor.api.workflows.get_run(run_id)` — run + all step runs + pinned snapshot.
- `conductor.api.workflows.cancel_run(run_id)` — operator-gated mutation.

All endpoints require an authenticated user with `Conductor Operator` role; `cancel_run` is the only mutating endpoint.

---

## 6. Data Flow

### 6.1 Forward execution

```
run_workflow(name, *args, **kwargs)
 ├─ resolve class via in-process decorator registry (not via DocType row)
 ├─ hash topology; INSERT-or-version-bump Conductor Workflow row
 ├─ acquire wfidem lock if idempotency_key supplied
 ├─ INSERT Conductor Workflow Run (status=PENDING, definition_version=N)
 ├─ INSERT one Conductor Workflow Step Run per step (status=PENDING)
 ├─ HSET conductor:{site}:wfdeps:{run_id} for every step → len(depends_on)
 └─ enqueue advancer(run_id, completed_step=None) on "workflow" queue
       │
       ▼
advancer worker
 ├─ load run + pinned snapshot
 ├─ if run.status not in {PENDING, RUNNING}: return  (cancellation guard)
 ├─ EVAL fanin_decrement KEYS={wfdeps:{run_id}}
 │        ARGV={completed_step or "", json(downstreams_of_completed)}
 │        → returns list of step_ids whose count is now 0
 │   (on first call, returns all roots — steps with in_degree 0)
 ├─ for each ready step_id:
 │    UPDATE Step Run.status: PENDING → READY  (skip if not PENDING; idempotent)
 │    conductor.enqueue(method=Class.<step_method>,
 │                      queue=workflow.queue,
 │                      kwargs=run.input_kwargs,
 │                      idempotency_key=f"wf:{run_id}:{step_id}:dispatch",
 │                      __workflow_run_id=run_id,
 │                      __step_id=step_id)
 │    (worker.py flips READY → RUNNING when it picks the job up)
 ├─ if first dispatch: UPDATE run.status: PENDING → RUNNING
 └─ if no ready steps remain AND no Step Run in {READY, RUNNING}:
      UPDATE run.status = SUCCEEDED, finished_at = now
       │
       ▼
step's Conductor Job runs (worker.py)
 ├─ on SUCCEEDED:
 │    UPDATE Workflow Step Run.status=SUCCEEDED, finished_at=now
 │    if job.workflow_run_id:
 │        enqueue advancer(run_id, completed_step=step_id)
 ├─ on terminal failure (DLQ):
 │    UPDATE Workflow Step Run.status=FAILED, error fields populated
 │    if job.workflow_run_id:
 │        UPDATE Workflow Run.status=COMPENSATING
 │        enqueue compensator(run_id, failed_step=step_id)
```

### 6.2 Compensation

**Compensation row model:** the forward Step Run row stays in its terminal state (`SUCCEEDED` for completed steps, `FAILED` for the failing one). Each compensation creates a **new** Step Run row with `is_compensation=1` so the row's state machine is just `PENDING → READY → RUNNING → COMPENSATED|FAILED` — no overloaded "succeeded but compensating" intermediate. The dashboard pairs forward+compensation rows by `(workflow_run, step_id)` for display.

**In-flight-sibling rule:** when the run transitions to `COMPENSATING`, in-flight forward steps (status `READY` or `RUNNING`) are **allowed to finish naturally** — they are not cancelled. The compensator refuses to enqueue the next compensation until **all** forward step runs (is_compensation=0) are in a terminal state (`SUCCEEDED`, `FAILED`, or `SKIPPED`). The worker hook re-fires the compensator each time a forward step terminates, so the compensator advances on its own as the in-flight set drains. Forward steps that succeed during the COMPENSATING window still land their `SUCCEEDED` row and are included in the reverse-topo list; their compensation runs as part of the same compensation pass. Forward steps that fail during the window are recorded but do not re-trigger compensation (we are already compensating).

```
advancer worker, COMPENSATING branch (run_id, just_completed_step | None)
 ├─ load run + pinned snapshot
 ├─ if run.status not in {COMPENSATING}: return  (cancellation / halt guard)
 ├─ if any forward Step Run (is_compensation=0) is in {PENDING, READY, RUNNING}:
 │     return  (the worker hook will re-fire us when each one terminates)
 ├─ completed_forward_steps =
 │     forward Step Runs (is_compensation=0) with status=SUCCEEDED,
 │     for which no compensation row yet exists
 ├─ if completed_forward_steps is empty:
 │     UPDATE Workflow Run.status = FAILED, finished_at = now
 │     return
 ├─ next_step = first in reverse-topological order from the pinned snapshot
 ├─ if next_step has no compensation method:
 │     no row inserted; recurse: enqueue compensator(run_id, just_compensated_step=next_step)
 │     return
 ├─ INSERT Conductor Workflow Step Run (step_id=next_step, is_compensation=1, status=READY)
 ├─ conductor.enqueue(method=Class.<compensation_method>,
 │                   queue=workflow.queue,
 │                   kwargs=run.input_kwargs,
 │                   idempotency_key=f"wf:{run_id}:{next_step}:compensate",
 │                   __workflow_run_id=run_id,
 │                   __step_id=next_step,
 │                   __is_compensation=True,
 │                   __step_run_id=<just-inserted row name>)
 └─ (worker.py marks the row RUNNING on pickup; on terminal state, hooks below fire)

compensation job → SUCCEEDED:
 ├─ UPDATE Step Run (compensation row) status=COMPENSATED
 └─ enqueue advancer(run_id, completed_step=step_id) to continue (re-enters COMPENSATING branch)

compensation job → DLQ (terminal failure):
 ├─ UPDATE Step Run (compensation row) status=FAILED
 ├─ UPDATE Workflow Run.status = FAILED, last_error = <compensation traceback>, finished_at = now
 └─ HALT — earlier completed steps are NOT unrolled (locked decision)
```

The advancer (in either branch) is itself a Conductor job and inherits retry/timeout semantics; if it dies mid-execution, Phase-1 reclamation re-runs it. The COMPENSATING branch is idempotent because it always re-derives the next-uncompensated-step from current row state — re-running it never inserts a duplicate compensation row (the `step_id + is_compensation=1` row's existence is the lock).

### 6.3 Cancellation flow

```
cancel_workflow_run(run_id)
 ├─ UPDATE Workflow Run.status=CANCELLED
 ├─ UPDATE every Step Run with status in {PENDING,READY} → SKIPPED
 ├─ for every Step Run with status=RUNNING: cancel_job(step_run.job)
 └─ DELETE conductor:{site}:wfdeps:{run_id}
```

The advancer checks `run.status` on entry and exits cleanly if the status is anything other than `PENDING`, `RUNNING`, or `COMPENSATING` — so any in-flight advancer/compensator that fires after cancellation is a no-op.

---

## 7. State Machines

### 7.1 Workflow Run

```
PENDING ──► RUNNING ──► SUCCEEDED
              │
              ├──► COMPENSATING ──► FAILED      (terminal step failure path)
              ├──► FAILED                       (compensation-of-compensation halt; or compensator exhaust)
              └──► CANCELLED                    (operator action)
```

Compatible with the master §6.8 `Conductor Workflow Run.status` enum.

### 7.2 Workflow Step Run

```
PENDING ──► READY ──► RUNNING ──► SUCCEEDED ──► (COMPENSATED?)
                          │
                          ├──► FAILED      (job exhausted retries)
                          └──► SKIPPED     (run cancelled before dispatch)
```

Master §6.9 enum already lists `PENDING / READY / RUNNING / SUCCEEDED / FAILED / COMPENSATED / SKIPPED`.

---

## 8. DocType Adjustments to Master §6.7–6.9

The master schemas are largely sufficient. The following additions are needed for Phase 5 functionality:

### 8.1 `Conductor Workflow` — additions

| Field | Type | Notes |
|---|---|---|
| `last_version_bumped_at` | Datetime | Sanity field — the last time auto-detection bumped `version` |

### 8.2 `Conductor Workflow Run` — additions

| Field | Type | Notes |
|---|---|---|
| `idempotency_key` | Data (indexed) | Hashed key value, mirrors `Conductor Job` |
| `cancelled_at` | Datetime | Set when `cancel_workflow_run` is called |
| `cancelled_by` | Link → User | Set when cancellation is operator-driven |

### 8.3 `Conductor Workflow Step Run` — additions

| Field | Type | Notes |
|---|---|---|
| `is_compensation` | Check | Set to 1 when the step run represents a compensation job rather than the forward-path step |
| `error_type` | Data | Mirrored from the underlying job's last failed run for quick filtering |
| `error_message` | Small Text | Mirrored from the underlying job |

These additions are list-views-friendly so the dashboard table doesn't need to chase the `Conductor Job` row to render a row.

---

## 9. Redis Topology Additions

```
conductor:{site}:wfdeps:{run_id}        # HASH step_id → remaining_deps_count
conductor:{site}:wfidem:{hash}          # SET NX EX, value=run_id, TTL 24h (mirrors job idem)
```

`wfdeps:{run_id}` is the only key touched by the Lua script — single-key per master §3 #15.

The `wfsnap:{name}:v{N}` cache mentioned in earlier brainstorming is removed; we will read snapshots from MariaDB directly. The DB row is small, the read is once per advancer invocation, and avoiding a Redis cache eliminates a coherence concern.

---

## 10. Lua Script: `fanin_decrement`

**Inputs:**
- `KEYS[1]` = `conductor:{site}:wfdeps:{run_id}`
- `ARGV[1]` = `completed_step_id` (empty string on the first call)
- `ARGV[2]` = JSON-encoded list of step ids that depend on the completed step

**Behavior:**
- If `ARGV[1]` is empty: scan the hash, collect all fields whose value is `0`, return them.
- Otherwise: for each downstream id in `ARGV[2]`, `HINCRBY ... -1`. Collect those whose new value is `≤ 0`. Return them.

**Properties:**
- Single-key (cluster-compatible).
- Idempotent on duplicate completion notifications: a downstream count can go negative on a re-fired advancer, but the dispatch side is also guarded — the `READY → enqueue` step is a conditional `UPDATE WHERE status='PENDING'`, so a duplicate-ready step is a no-op rather than a double-dispatch.
- Atomic: two siblings finishing at the same time can't both miss the fan-in — the script linearizes their decrements.

---

## 11. Realtime Events

Following Phase 3 §8.6.1 per-entity room scoping:

| Event name | When | Doctype/docname for room |
|---|---|---|
| `conductor:workflow_run:{run_id}` | Every Workflow Run status transition | `Conductor Workflow Run` / `run_id` |
| `conductor:workflow_step:{step_run_id}` | Every Step Run status transition | `Conductor Workflow Step Run` / `step_run_id` |
| (no event) | List views | Polling per Phase 3 §8.6.1 |

Aggregate views (Workflows list, Runs list) **must** use polling — the `useDashboardState` composable already handles this and is what the existing Jobs/DLQ tabs use.

The Workflow Run detail page subscribes to its own `workflow_run` room and to each of its step runs' rooms; the existing `useDetailSubscription` composable from Phase 3 takes the doctype + docname pair, so a small extension to subscribe to multiple step rooms simultaneously is needed.

---

## 12. Worker Integration

Three surgical hooks in `conductor/worker.py`, after the existing Phase-1 status writes:

```python
# When the worker picks up a workflow job:
if job.workflow_run_id:
    workflow.advancer.mark_step_running(job)
    # UPDATE Workflow Step Run SET status='RUNNING', started_at=now WHERE step_run_id=...

# After SUCCEEDED:
if job.workflow_run_id:
    workflow.advancer.mark_step_terminal(job, success=True)
    # forward row: SUCCEEDED ; compensation row: COMPENSATED
    workflow.advancer.enqueue_advance(job.workflow_run_id, completed_step=job.step_id)

# After terminal failure (DLQ):
if job.workflow_run_id:
    workflow.advancer.mark_step_terminal(job, success=False, error=...)
    # forward row: FAILED  → run flips to COMPENSATING (if not is_compensation)
    # compensation row: FAILED → run halts at FAILED
    workflow.advancer.enqueue_advance(job.workflow_run_id, completed_step=job.step_id)
```

`enqueue_advance` is a single entry point. The advancer job branches on `run.status`:

- `PENDING | RUNNING` → forward path: fan-in decrement, dispatch newly ready, transition run to `SUCCEEDED` if everything's done.
- `COMPENSATING` → compensation path: in-flight check, then enqueue the next reverse-topo compensation; transition run to `FAILED` when no compensations remain.
- Any other status → no-op (cancelled / already terminal).

`mark_step_terminal` is also responsible for transitioning the run to `COMPENSATING` when a forward step lands `FAILED` (and to `FAILED` when a compensation lands `FAILED`).

`enqueue_advance` / `enqueue_compensate` use `conductor.enqueue` themselves — there is no special path. They live in `conductor/workflow/advancer.py`.

A `workflow` queue is added to the Phase 0 fixtures so advancer / compensator traffic doesn't compete with user steps. Concurrency = 4 by default (matches `default`).

---

## 13. Definition Versioning

**Topology hash inputs** (sorted, canonical JSON):

- Workflow `name` and `queue`.
- Per step: `name`, `depends_on` (sorted), `compensation` method name, queue override (if any), `max_attempts` override (if any).

**Excluded** from the hash:

- Function bodies / bytecode.
- Method docstrings or comments.
- Order of `Step` attribute declaration on the class (we sort by step name).

This keeps version bumps to genuine topology changes. Body changes within an existing step do not bump the version, so in-flight runs don't see logic drift while running — they execute the *current* method body, but the structure is locked.

**Resolving `name → class`:** The decorator registers `name → class` in an in-process registry (`conductor.workflow.decorator._REGISTRY`) at import time. `run_workflow(name)` looks up the class **in the registry**, not via the DocType row. The `Conductor Workflow.definition_path` field is an audit projection populated by the dispatcher on first run; it is never used to load the class on the dispatch hot path. This avoids a chicken-and-egg between the registry (the source of truth for "what does this name mean?") and the DocType row (which records "we have seen this workflow"). It also means workflow registration is purely a Python import event — adding a workflow does not require a `bench migrate`.

**Algorithm on dispatch:**

1. Look up the class in the in-process registry; if missing, raise `WorkflowNotFoundError`.
2. Compute hash from class topology.
3. `frappe.db.get_value("Conductor Workflow", name, ["version", "definition_snapshot"])`.
4. If row missing: `frappe.get_doc(...).insert()` with `version=1`, hash, snapshot, `definition_path = f"{cls.__module__}.{cls.__qualname__}"`.
5. Else: hash the stored snapshot; if mismatch, `version += 1`, write new snapshot, set `last_version_bumped_at`.
6. Run is created with `definition_version = current version`.

**Note** (master §10 #5): if a run completes against a version that has since been bumped, log a structured warning. The dashboard shows a small badge on stale-version runs.

---

## 14. Dashboard (Tab #7)

A new tab is appended to the existing six. Routes:

- `/conductor-dashboard#/workflows` — list view.
- `/conductor-dashboard#/workflows/runs/:run_id` — run detail.

### 14.1 Workflows list

Per workflow:
- Name, current `version`, # active runs, # runs in last 24h, last-run status.
- Click → drills into recent-runs list filtered by that workflow.

### 14.2 Runs list (filterable)

Columns: run id, workflow, status, started_at, finished_at, duration, # steps total / done / failed, idempotency key.
Filters: workflow, status (multi-select), date range.

### 14.3 Run detail

- **Header:** workflow name, version (with stale badge if applicable), status pill, started/finished timestamps, idempotency key, **Cancel** button (operator role + status in `RUNNING`).
- **DAG panel:** Mermaid diagram colored by step status — gray (pending), blue (running), green (succeeded), red (failed), orange (compensated), dim (skipped). Hover a node → tooltip with timing + last error message.
- **Step runs table:** step id, status, attempts, duration, link to underlying `Conductor Job`. Click a row → expands traceback inline.
- **Input panel:** pretty-printed `input_args` / `input_kwargs`.
- Live updates via `useDetailSubscription` for the run + each step run. List views use `useDashboardState` polling.

The Mermaid renderer is a small Vue component wrapping the existing `mermaid` package; if `mermaid` is not already in the dashboard's `package.json`, it must be added during this phase.

---

## 15. Permissions

- All three Phase-5 DocTypes are **read-only** to the `Conductor Operator` role at the Frappe-permission level (no Create / Write / Delete from the Desk).
- Run cancellation goes through the `cancel_workflow_run` whitelisted method (which checks role, validates state, and writes via `frappe.flags.in_install`-style internal flag to bypass the read-only constraint for that one update path).
- System Manager retains full access for emergency intervention.

---

## 16. Testing Strategy

### 16.1 Unit tests

- `test_workflow_decorator.py` — decoration validation: missing method, missing compensation method, cycle detection, duplicate step name, undeclared dep.
- `test_workflow_snapshot.py` — hash determinism across restarts and Python `dict` ordering; equivalence of two structurally-identical workflows; non-equivalence when a `depends_on` entry changes.
- `test_workflow_topo.py` — reverse-topological order computation, including diamond and parallel-branch shapes.
- `test_workflow_lua.py` — `fanin_decrement` against a fake Redis: empty-completed first call returns roots; sibling decrements both succeed; double decrement on the same edge is harmless.
- `test_workflow_dispatcher.py` — `run_workflow` idempotency, version-bump trigger on hash change, run-row contents pinned.
- `test_workflow_advancer.py` — advancer flips PENDING→RUNNING, ready-set computation, terminal SUCCEEDED transition, terminal FAILED cascade to compensator enqueue.

### 16.2 Frappe integration tests (real DB + fake_redis)

- 4-step diamond happy path: A → {B, C} → D succeeds end-to-end. All four Step Run rows in `SUCCEEDED`; Workflow Run is `SUCCEEDED`.
- Force C terminal-fail: B and D never run (D never queued because C never finishes), A's compensation fires, run lands `FAILED`.
- Cancel mid-run: cancellation marks `RUNNING` step's job cancelled, leaves completed steps alone, run is `CANCELLED`.
- Idempotency: two `run_workflow(...)` calls with the same key return the same `run_id`.
- Definition versioning: change a `depends_on`, dispatch — run pinned to v2; old run rows unchanged.

### 16.3 Chaos tests

- `kill -9` an advancer mid-fan-out → Phase-1 reclaim re-runs it; deps state is consistent; run still finishes.
- `kill -9` a compensator mid-sequence → re-run continues from the next un-compensated step.
- Two workers racing on the advancer queue → exactly-once dispatch per step (because the dispatcher uses idempotency on `(run_id, step_id, "dispatch")`).

### 16.4 Exit criterion (master §4 Phase 5)

A 4-step workflow with one parallel branch (B and C both depending on A; D depending on B and C) runs to success. Forcing C to fail terminally rolls back A's compensation. Both scenarios run as a single test in `tests_chaos/test_phase5_chaos.py`.

---

## 17. Security and Multi-Tenancy

- Workflow class loading goes through `frappe.get_attr` and is therefore subject to Frappe's import boundaries — no path-traversal risk.
- All Redis keys are `{site}`-scoped per master §3 #7; runs cannot cross sites.
- Only `Conductor Operator` and `System Manager` can list / view / cancel workflow runs.
- The Mermaid client renders strings that come from the topology (step ids, names) which are always source-code symbols, never user input — XSS surface is the same as the existing dashboard.

---

## 18. Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | Topology hash sensitivity to dict ordering breaks reproducibility | Canonical JSON: sorted keys, sorted lists, no whitespace. Tested in `test_workflow_snapshot.py`. |
| 2 | Step name = method name collision on inheritance / mixins | Decorator validates against the class's own `__dict__` and walks `mro()` once for method lookup but raises if both produce a method. |
| 3 | Definition drift mid-run | Master §10 #5: stale-version warning logged + dashboard badge. |
| 4 | Advancer self-reentrancy / double-dispatch on the same step | `run_workflow` and the advancer use `conductor.enqueue(idempotency_key=f"wf:{run_id}:{step_id}:dispatch")` so duplicate enqueues collapse. |
| 5 | Compensation that itself fails terminally | By design (locked Q3 = A.1): halt at `FAILED`, do not unroll earlier steps. |
| 6 | Mermaid bundle size on dashboard | Lazy-import the Mermaid component on the run-detail route only. |
| 7 | Cross-phase contract violation: stream message schema field meanings | We only **populate** the existing `workflow_run_id` / `step_id` keys and add `is_compensation` to kwargs (not the stream schema). No schema change. |

---

## 19. Master Design Updates Required

This phase requires a single change-log entry in the master design (no schema-level edits — master §6.7–6.9 are sufficient as-is, augmented by §8 above). The change-log entry should note:

- Phase 5 spec written and locked.
- The Phase-5 fields added to Workflow / Workflow Run / Workflow Step Run schemas (per §8 here).
- The `wfdeps:{run_id}` and `wfidem:{hash}` keys added to master §8 Redis Topology.
- The `workflow` queue added to Phase 0 fixtures.

---

## 20. Implementation Order (preview for the plan)

This is a hint for the writing-plans handoff, not a binding sequence:

1. DocType schemas (the three new tables).
2. `Step`, `@workflow` decorator, registry, validation, topology hash — pure Python, no Frappe runtime.
3. `run_workflow` dispatcher (DB row + Redis seed + advancer enqueue).
4. Lua script + advancer happy path.
5. Worker hooks for success.
6. Compensator + worker hooks for terminal failure.
7. Cancellation API and propagation.
8. CLI commands.
9. Whitelisted dashboard endpoints.
10. Dashboard tab + Mermaid renderer.
11. Chaos tests + exit-criterion test.
12. Master-design change-log entry + README update ("Phase 4 of 5").

---

## Change Log

| Date | Change | Author |
|---|---|---|
| 2026-04-29 | Initial Phase 5 design. | osama.m@aau.iq |
