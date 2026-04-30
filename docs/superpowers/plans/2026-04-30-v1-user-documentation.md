# Conductor v1 User Documentation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a flat, Diátaxis-organized user documentation set under `docs/`, shrink the README to a quickstart that links into `docs/`, and remove the stale `docs/audit.md`.

**Architecture:** 14 Markdown files under `docs/` (1 `index.md` + 1 tutorial + 6 how-tos + 3 reference pages + 3 explanation pages) plus a README rewrite. Each page has a single Diátaxis purpose; conventions (active voice, lead with the answer, runnable code samples, "If something went wrong" sections in how-tos) are uniform. README keeps the KPI bullets and quickstart only and links into `docs/`. App polish is deferred.

**Tech Stack:** Plain GitHub-rendered Markdown (no static site generator for v1). Mermaid for diagrams. Source of truth is the Conductor codebase under `apps/conductor/conductor/`.

**Spec:** [`docs/superpowers/specs/2026-04-30-v1-user-documentation-design.md`](../specs/2026-04-30-v1-user-documentation-design.md)

---

## Reference material the engineer needs

Read these once at the start of the session and keep them open:

- **The spec** — `docs/superpowers/specs/2026-04-30-v1-user-documentation-design.md` (per-page contracts, conventions).
- **The current README** — `README.md` (existing copy that pages extract from; the README itself is rewritten in Task 16).
- **CLAUDE.md** — `CLAUDE.md` at the repo root (clean-code rules apply to docs prose too: short paragraphs, intention-revealing names, no jargon without definition).
- **The KPI plan spec** — `docs/superpowers/specs/2026-04-30-conductor-vs-rq-kpi-plan.md` (cited from `explanation-why-conductor.md`).

### Codebase landmarks

| Topic | File(s) |
|---|---|
| Public Python API re-exports | `conductor/__init__.py` |
| `enqueue`, `cancel`, `RetryPolicy`, `context`, `job` | `conductor/api/__init__.py` and submodules |
| Workflow public surface | `conductor/workflow/__init__.py`, `conductor/workflow/decorator.py`, `conductor/workflow/dispatcher.py`, `conductor/workflow/cancellation.py` |
| `frappe.enqueue` shim | `conductor/frappe_compat.py` |
| CLI subcommands | `conductor/commands/{worker,scheduler,doctor,schedule,dlq,depth,migrate_rq,workflow,cancel}.py` |
| Site-config keys / hooks | `conductor/hooks.py`, `conductor/install.py` |
| DocTypes | `conductor/conductor/doctype/{conductor_queue,conductor_job,conductor_job_run,conductor_worker,conductor_schedule,conductor_workflow,conductor_workflow_run,conductor_workflow_step_run,conductor_dlq_entry}/*.json` |
| Architecture (dispatcher → stream → worker) | `conductor/dispatcher.py`, `conductor/streams.py`, `conductor/worker.py` |
| Scheduler singleton + lock | `conductor/scheduler.py`, `conductor/scheduler_lock.py`, `conductor/scheduler_loops.py` |
| Reliability primitives | `conductor/idempotency.py`, `conductor/retry.py`, `conductor/scheduled.py`, `conductor/inflight.py`, `conductor/rate_limit.py`, `conductor/sweeper.py` |
| Multi-tenant pool / site discovery | `conductor/site_discovery.py`, `conductor/worker.py` (pool branches) |
| RQ migration | `conductor/migrate_rq.py` |
| KPI suite | `tests/comparative/run_kpis.py`, `tests/comparative/*.py` |

### Verification environment

- Bench root: `/Users/osamamuhammed/frappe_15`
- Site: `frappe.localhost`
- Python: `/Users/osamamuhammed/frappe_15/env/bin/python`
- Pytest: `/Users/osamamuhammed/frappe_15/env/bin/pytest`
- Bench wrapper: `bench --site frappe.localhost ...` (run from bench root, not from inside `apps/conductor`)

### Spec correction (apply during the plan)

The spec lists 5 DocTypes for `reference-configuration.md`. The codebase actually has **9** DocTypes — the page must cover all of them:

`Conductor Queue`, `Conductor Job`, `Conductor Job Run`, `Conductor Worker`, `Conductor Schedule`, `Conductor Workflow`, `Conductor Workflow Run`, `Conductor Workflow Step Run`, `Conductor DLQ Entry`.

The spec also lists 6 Python API symbols. The actual public surface is **wider** (per `conductor/__init__.py`): add `cancel`, `cancel_workflow_run`, `RetryPolicy`, and `job` (the decorator). `reference-python-api.md` covers all of them.

### Deprecated terms (forbidden in `docs/`)

- "dead letter" → use **DLQ**
- "task" (when meaning a Conductor execution) → use **job**
- "cron daemon" → use **scheduler**
- "topic" (when meaning a queue) → use **queue**
- "consumer" (when meaning a worker) → use **worker**

---

## Phase order

1. **Reference** (Tasks 1–3) — factual, easy to verify against code; everything else links here.
2. **Explanation** (Tasks 4–6) — defines the jargon how-tos rely on.
3. **How-to** (Tasks 7–12) — task-oriented; uses references and explanations.
4. **Tutorial + Index** (Tasks 13–14) — written last; pulls from everything.
5. **README rewrite + cleanup** (Tasks 15–16) — depends on `docs/` being complete.

Each task ends with a commit. Commits are scoped to one file (or one logical change for the README/cleanup tasks).

---

## Task 1: `reference-cli.md`

**Files:**
- Create: `docs/reference-cli.md`
- Read: `conductor/commands/{worker,scheduler,doctor,schedule,dlq,depth,migrate_rq,workflow,cancel}.py`

- [ ] **Step 1: Read each command module** to capture exact subcommand names, options, defaults, and exit codes.

  ```bash
  ls /Users/osamamuhammed/frappe_15/apps/conductor/conductor/commands/
  ```

  For each `*.py` other than `__init__.py`, read the file to extract: subcommand name, click options (with help text), exit codes (look for `sys.exit(...)`), and whether it requires `--site` or works pool-wide.

- [ ] **Step 2: Draft `docs/reference-cli.md`** with this structure:

  - First paragraph (≤ 3 lines): "Reference for every `bench conductor *` subcommand. Synopsis, options, examples, exit codes." Note that all examples assume `bench --site SITE` from the bench root unless stated.
  - One `##` section per subcommand group, in this order: **worker**, **scheduler**, **doctor**, **schedule** (with `list` / `enable` / `disable` / `run-now` subsections), **dlq** (`list` / `retry` / `discard`), **depth**, **migrate-from-rq**, **workflow** (`list` / `run` / `status` / `cancel`), **cancel**.
  - Each section: synopsis line in a fenced block, an options table (Option · Default · Meaning), 1–2 `bash` examples, and exit codes when non-trivial (e.g., `doctor` exits 1 on failure).
  - End with a "See also" linking to `reference-configuration.md` and `how-to-triage-failures.md`.

- [ ] **Step 3: Verify a representative command from each group**

  ```bash
  bench --site frappe.localhost conductor doctor
  bench --site frappe.localhost conductor depth
  bench --site frappe.localhost conductor schedule list
  bench --site frappe.localhost conductor dlq list --queue default
  bench --site frappe.localhost conductor workflow list
  ```

  Expected: each runs without error (or returns an empty list). Adjust the doc if the help text doesn't match what `--help` prints.

- [ ] **Step 4: Run `--help` on each subcommand** and confirm the options table matches:

  ```bash
  bench --site frappe.localhost conductor worker --help
  bench --site frappe.localhost conductor scheduler --help
  bench --site frappe.localhost conductor schedule list --help
  bench --site frappe.localhost conductor dlq retry --help
  bench --site frappe.localhost conductor migrate-from-rq --help
  bench --site frappe.localhost conductor workflow run --help
  ```

  Expected: each `--help` output matches the options table for that section.

- [ ] **Step 5: Grep for forbidden terms**

  ```bash
  grep -niE 'dead letter|cron daemon|\btopic\b|\bconsumer\b' docs/reference-cli.md
  ```

  Expected: no matches. (`task` is grep-checked at the end of Task 16 because some legitimate prose like "completes the task" can occur — for now, just check the deprecated phrases.)

- [ ] **Step 6: Commit**

  ```bash
  git add docs/reference-cli.md
  git commit -m "docs(v1): CLI reference page"
  ```

---

## Task 2: `reference-python-api.md`

**Files:**
- Create: `docs/reference-python-api.md`
- Read: `conductor/__init__.py`, `conductor/api/__init__.py`, `conductor/decorator.py`, `conductor/context.py`, `conductor/retry.py`, `conductor/workflow/__init__.py`, `conductor/workflow/decorator.py`, `conductor/workflow/dispatcher.py`, `conductor/workflow/cancellation.py`, `conductor/frappe_compat.py`

- [ ] **Step 1: Confirm the public surface** by reading `conductor/__init__.py` and `conductor/workflow/__init__.py`. The full list is:

  - `conductor.enqueue(method, *, queue=..., idempotency_key=..., **kwargs) -> str`
  - `conductor.cancel(job_id) -> bool` — soft cancel; the worker checks the cancel flag at lease boundaries.
  - `conductor.context() -> Context` — current job context inside a job body.
  - `conductor.job` — decorator for registering a method as a job.
  - `conductor.RetryPolicy(...)` — per-job retry override.
  - `conductor.run_workflow(name, *, idempotency_key=None, **kwargs) -> str`
  - `conductor.cancel_workflow_run(run_id) -> bool`
  - `conductor.workflow.workflow(*, name, queue, ...)` — class decorator.
  - `conductor.workflow.Step(method_name, *, depends_on=(), compensation=None)`
  - `conductor.workflow.WorkflowDefinitionError`, `WorkflowNotFoundError`
  - `conductor.frappe_compat.enqueue(...)` — `frappe.enqueue` override target.

- [ ] **Step 2: Draft `docs/reference-python-api.md`** with this structure:

  - First paragraph (≤ 3 lines): "Reference for the Conductor public Python API. Import from `conductor` (top-level re-exports) or `conductor.workflow`. Internal modules (`conductor.dispatcher`, `conductor.streams`, etc.) are not part of the public API."
  - Group headings: **Enqueue and cancel** · **Job decoration and context** · **Workflows** · **Frappe compatibility shim**.
  - One `###` per symbol with: signature (Python, type-annotated), parameters table (Param · Type · Default · Meaning), Returns, Raises, Example (3–8 lines).
  - "See also" footer linking to `reference-cli.md` (for the `--idempotency-key` mirror), `explanation-reliability.md` (for what idempotency keys actually protect), `how-to-define-workflows.md`.

- [ ] **Step 3: Verify each example imports and runs** in `bench console`:

  ```bash
  bench --site frappe.localhost console <<'EOF'
  import conductor
  from conductor.workflow import workflow, Step
  print(conductor.enqueue, conductor.run_workflow, conductor.cancel)
  print(workflow, Step)
  EOF
  ```

  Expected: prints function/decorator objects. No `ImportError`.

- [ ] **Step 4: For `enqueue`, run a real end-to-end sanity check**

  ```bash
  bench --site frappe.localhost console <<'EOF'
  import conductor
  jid = conductor.enqueue("frappe.utils.now")
  print("enqueued:", jid)
  EOF
  ```

  Expected: prints a UUID-shaped job id. (Worker need not be running for this check; we only verify the call signature.)

- [ ] **Step 5: Commit**

  ```bash
  git add docs/reference-python-api.md
  git commit -m "docs(v1): Python API reference page"
  ```

---

## Task 3: `reference-configuration.md`

**Files:**
- Create: `docs/reference-configuration.md`
- Read: `conductor/hooks.py`, `conductor/install.py`, `conductor/conductor/doctype/*/conductor_*.json` (9 DocTypes)

- [ ] **Step 1: Extract `site_config.json` keys** by grepping `frappe.conf` and `frappe.local.conf` references in the codebase:

  ```bash
  grep -rn 'frappe\.conf' /Users/osamamuhammed/frappe_15/apps/conductor/conductor/ | grep -v __pycache__
  grep -rn 'conductor.*redis_url\|stream_max_len\|default_queue\|dashboard_poll_interval_ms' /Users/osamamuhammed/frappe_15/apps/conductor/conductor/ | grep -v __pycache__
  ```

  Capture: key path, type, default value, the file:line where it is read.

- [ ] **Step 2: Extract DocType field tables** — for each of the 9 DocTypes, read its `*.json` and build a table of (Fieldname · Type · Required · Meaning). Skip Frappe-default fields (`name`, `creation`, `modified`, `owner`, etc.).

  ```bash
  ls /Users/osamamuhammed/frappe_15/apps/conductor/conductor/conductor/doctype/
  ```

  DocTypes to cover, in this order: `Conductor Queue`, `Conductor Job`, `Conductor Job Run`, `Conductor Worker`, `Conductor Schedule`, `Conductor Workflow`, `Conductor Workflow Run`, `Conductor Workflow Step Run`, `Conductor DLQ Entry`.

- [ ] **Step 3: Extract roles and permission rules** — read each DocType's `permissions` array, plus any `hooks.py` permission overrides. Build a matrix: action × (System Manager · Conductor Operator · other), where action ∈ {read, retry, cancel, run-now, enable/disable schedule, edit-and-retry, discard DLQ}.

- [ ] **Step 4: Draft `docs/reference-configuration.md`** with four sections:

  - **`site_config.json` keys** — table (Key · Type · Default · Meaning · Read by). Cover at minimum: `conductor.redis_url`, `conductor.default_queue`, `conductor.stream_max_len`, `conductor.dashboard_poll_interval_ms`, plus any others Step 1 surfaces.
  - **DocType fields** — one `###` heading per DocType, each with the field table from Step 2.
  - **Roles and permissions** — the matrix from Step 3, plus a one-paragraph explanation of the destructive/read-only split.
  - **Job state machine** — a Mermaid `stateDiagram-v2` block showing PENDING → RUNNING → SUCCEEDED / FAILED / SCHEDULED_RETRY → DLQ with allowed transitions, followed by a one-line description of each terminal state.

- [ ] **Step 5: Verify state machine matches the code** by reading `conductor/worker.py` (status writes), `conductor/scheduled.py`, and `conductor/sweeper.py` for terminal transitions.

  ```bash
  grep -nE 'status\s*=\s*["\x27](PENDING|RUNNING|SUCCEEDED|FAILED|SCHEDULED_RETRY|DLQ|CANCELED)' /Users/osamamuhammed/frappe_15/apps/conductor/conductor/worker.py /Users/osamamuhammed/frappe_15/apps/conductor/conductor/scheduled.py /Users/osamamuhammed/frappe_15/apps/conductor/conductor/sweeper.py
  ```

  Expected: every status string in the diagram appears in the code; every status string in the code is in the diagram (or is private/transient and the diagram says so).

- [ ] **Step 6: Render check** — paste the Mermaid block into <https://mermaid.live> (or use a local renderer) and confirm it renders without syntax errors. (GitHub renders Mermaid in `mermaid` fenced blocks natively.)

- [ ] **Step 7: Commit**

  ```bash
  git add docs/reference-configuration.md
  git commit -m "docs(v1): configuration reference page"
  ```

---

## Task 4: `explanation-why-conductor.md`

**Files:**
- Create: `docs/explanation-why-conductor.md`
- Read: `README.md` (the "Why Conductor (vs Frappe RQ)" section, lines 1–60), `docs/superpowers/specs/2026-04-30-conductor-vs-rq-kpi-plan.md`

- [ ] **Step 1: Lift the KPI table verbatim from the README.** Same caveats, same wording for "What we do *not* claim". Do not editorialize.

- [ ] **Step 2: Add a "Methodology" subsection** describing how the suite is run (`tests/comparative/run_kpis.py`, same site, same workload, KPI-by-KPI). Cite the file path. Cite the spec for the threat model.

- [ ] **Step 3: Add a "What this measurement cannot tell you" subsection** — Linux vs macOS fork cost caveat, single-worker throughput is not a fleet number, the dropped KPI 6.

- [ ] **Step 4: Draft `docs/explanation-why-conductor.md`** with:

  - First paragraph (≤ 3 lines): "Conductor positions itself as reliability-first relative to Frappe RQ. This page is the receipts: the measurements, the methodology, and the limits of what those measurements prove."
  - Sections: **At a glance** (the bullets) · **The KPI table** · **Methodology** · **What this measurement cannot tell you** · **Reproducing the suite** (the `run_kpis.py` invocation block).
  - Footer: link to `tests/comparative/run_kpis.py` and the KPI plan spec.

- [ ] **Step 5: Verify the suite still runs** (a single KPI is enough)

  ```bash
  cd /Users/osamamuhammed/frappe_15/apps/conductor
  /Users/osamamuhammed/frappe_15/env/bin/python -m tests.comparative.run_kpis --kpi 1 --engine conductor
  ```

  Expected: completes and prints a result for KPI 1. (No need to compare to RQ; this only verifies the documented invocation works.)

- [ ] **Step 6: Commit**

  ```bash
  git add docs/explanation-why-conductor.md
  git commit -m "docs(v1): why-Conductor explanation page"
  ```

---

## Task 5: `explanation-architecture.md`

**Files:**
- Create: `docs/explanation-architecture.md`
- Read: `conductor/dispatcher.py`, `conductor/streams.py`, `conductor/worker.py`, `conductor/scheduler.py`, `conductor/scheduler_lock.py`, `conductor/scheduler_loops.py`, `conductor/site_discovery.py`, `conductor/sweeper.py`, `conductor/inflight.py`, `conductor/rate_limit.py`

- [ ] **Step 1: Extract the Redis keyspace.** Grep for key prefixes:

  ```bash
  grep -rnE 'conductor:\{?site\}?:\{?[a-z_]+\}?:' /Users/osamamuhammed/frappe_15/apps/conductor/conductor/ | grep -v __pycache__ | sort -u
  ```

  Capture: stream key, idempotency key, inflight key, rate-limit key, scheduler-lock key, retry-delay key. Note the multi-tenant `{site}` segment.

- [ ] **Step 2: Sketch the data flow** by reading `dispatcher.py` (enqueue side) → `streams.py` (XADD / XREADGROUP) → `worker.py` (claim and execute). Note where idempotency, inflight, and rate-limit checks happen relative to XADD.

- [ ] **Step 3: Draft `docs/explanation-architecture.md`** with:

  - First paragraph (≤ 3 lines): "Conductor is a Redis-streams job queue with a single scheduler per site and N workers. This page explains the moving parts and how a job moves through them."
  - Sections (in this order): **Components** (one bullet per: dispatcher, stream, worker, scheduler, sweeper, dashboard) · **Redis keyspace** (table from Step 1) · **A job's life** (numbered steps from `enqueue(...)` → status `SUCCEEDED`/`FAILED`/`DLQ`) · **The scheduler singleton** (lock, takeover within ~20 s) · **Pool worker model** (how `--sites=auto` maps one process to many sites).
  - **One Mermaid `flowchart LR` diagram** showing: caller → `enqueue` → idempotency check → stream → worker → status. Put it under the **A job's life** heading.
  - Footer: link to `explanation-reliability.md`, `how-to-run-multi-tenant.md`, `reference-configuration.md`.

- [ ] **Step 4: Verify the keyspace table** by running

  ```bash
  bench --site frappe.localhost conductor depth
  redis-cli -p 11000 -n 2 keys 'conductor:*' | head
  ```

  Expected: real keys match the documented patterns. (If Redis is on a non-default port, adjust per `site_config.json`.)

- [ ] **Step 5: Commit**

  ```bash
  git add docs/explanation-architecture.md
  git commit -m "docs(v1): architecture explanation page"
  ```

---

## Task 6: `explanation-reliability.md`

**Files:**
- Create: `docs/explanation-reliability.md`
- Read: `conductor/idempotency.py`, `conductor/inflight.py`, `conductor/rate_limit.py`, `conductor/retry.py`, `conductor/scheduled.py`, `conductor/sweeper.py`, `conductor/workflow/advancer.py`, `conductor/workflow/dispatcher.py`

- [ ] **Step 1: Capture the contract.** From the code, write down:

  - At-least-once delivery boundary: where can duplicates occur? (worker death between status flip and ACK)
  - Idempotency key behavior: what protects against (concurrent producers), what does not (a job that internally calls a non-idempotent external API).
  - Retry backoff schedule (read `retry.py`).
  - DLQ entry conditions: terminal failure after N retries; non-retryable error class; explicit `discard`.
  - Workflow compensation order: reverse-topological from the failed step. Partial-rollback rule when a compensation itself fails.

- [ ] **Step 2: Draft `docs/explanation-reliability.md`** with:

  - First paragraph (≤ 3 lines): "Conductor's reliability story has four pieces: at-least-once delivery, idempotency keys, retries, and the DLQ. This page explains each, including what it does **not** protect against."
  - Sections: **At-least-once delivery** · **Idempotency keys** · **Retries and `SCHEDULED_RETRY`** · **The DLQ** · **Workflow compensations** · **Failure modes Conductor does not handle** (e.g., a job whose body itself calls a non-idempotent external API).
  - Cross-link to `reference-configuration.md` (state machine) for the status transitions.

- [ ] **Step 3: Sanity-check the retry schedule** by reading `conductor/retry.py` — confirm the documented backoff matches the code.

  ```bash
  grep -nE 'def\s+(next_retry_at|backoff)|RETRY_DELAYS' /Users/osamamuhammed/frappe_15/apps/conductor/conductor/retry.py
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add docs/explanation-reliability.md
  git commit -m "docs(v1): reliability explanation page"
  ```

---

## Task 7: `how-to-enqueue-jobs.md`

**Files:**
- Create: `docs/how-to-enqueue-jobs.md`
- Read: `conductor/api/__init__.py`, `conductor/idempotency.py`, `conductor/frappe_compat.py`, `README.md` ("Use it" section)

- [ ] **Step 1: Draft three procedures.** Use this skeleton:

  - First paragraph (≤ 3 lines): who the page is for (Frappe app developers), what success looks like (a job lands on a queue with a known id and runs).
  - **Procedure 1 — Enqueue a job from a Frappe app.** 4–5 numbered steps. Code block:

    ```python
    import conductor

    job_id = conductor.enqueue(
        "myapp.tasks.send_email",
        queue="default",
        invoice="INV-001",
    )
    ```

  - **Procedure 2 — Make an enqueue idempotent.** 4–5 steps. Code block:

    ```python
    job_id = conductor.enqueue(
        "myapp.tasks.send_email",
        queue="default",
        idempotency_key="invoice:INV-001:reminder:1",
        invoice="INV-001",
    )
    ```

    Explain in 2–3 lines what the key protects against (concurrent producers racing the same business key) and what it does not (a job body that calls a non-idempotent external API). Link to `explanation-reliability.md#idempotency-keys`.

  - **Procedure 3 — Override `frappe.enqueue` app-wide.** Code block from the README's `hooks.py` snippet. Explain that the override is per-client-app (set in *that* app's `hooks.py`, not Conductor's).

  - **If something went wrong** — 3 entries: (1) `ImportError: conductor` → install the app on the site; (2) job id returned but never runs → no worker for that queue, run `bench conductor worker --queue X`; (3) duplicate executions despite key → the key must be the same string across producers, and only protects within the dedup window (link to `explanation-reliability.md`).

- [ ] **Step 2: Run each code sample** in `bench console`:

  ```bash
  bench --site frappe.localhost console <<'EOF'
  import conductor
  print(conductor.enqueue("frappe.utils.now"))
  print(conductor.enqueue("frappe.utils.now", idempotency_key="docs-test-1"))
  print(conductor.enqueue("frappe.utils.now", idempotency_key="docs-test-1"))  # second call returns same id
  EOF
  ```

  Expected: first call prints a job id; the two `idempotency_key="docs-test-1"` calls print the **same** id. If they print different ids, the page's claim is wrong — fix the page (or fix the code, but that's out of scope for this branch — file an issue).

- [ ] **Step 3: Commit**

  ```bash
  git add docs/how-to-enqueue-jobs.md
  git commit -m "docs(v1): how-to enqueue jobs"
  ```

---

## Task 8: `how-to-schedule-jobs.md`

**Files:**
- Create: `docs/how-to-schedule-jobs.md`
- Read: `conductor/scheduler.py`, `conductor/scheduler_loops.py`, `conductor/cron.py`, `conductor/commands/schedule.py`, `conductor/conductor/doctype/conductor_schedule/conductor_schedule.json`

- [ ] **Step 1: Draft three procedures.**

  - First paragraph (≤ 3 lines): operator audience; success = a cron expression fires the documented method on time.
  - **Procedure 1 — Create a `Conductor Schedule` in the Desk.** Numbered steps: Desk → Conductor module → New Schedule → required fields (`cron_expression`, `timezone`, `method`, `queue`) → save. Note that bad cron expressions are rejected at save time.
  - **Procedure 2 — Manage schedules from the CLI.** Show all four subcommands:

    ```bash
    bench --site frappe.localhost conductor schedule list
    bench --site frappe.localhost conductor schedule enable <name>
    bench --site frappe.localhost conductor schedule disable <name>
    bench --site frappe.localhost conductor schedule run-now <name>
    ```

    Note the `run-now` semantics: it fires immediately and updates `last_status` / `last_job` but **does not** advance `last_run_at`.

  - **Procedure 3 — Make a scheduled method idempotent.** Explain the at-least-once contract (a scheduler crash between `enqueue(...)` and the `next_run_at` write causes the next holder to refire). Show a 5-line example with an idempotency check at the top of the method.
  - **If something went wrong** — 3 entries: (1) cron save fails → expression is invalid; (2) schedule never fires → no `bench conductor scheduler` running; (3) duplicate fires → expected under at-least-once; make method idempotent.

- [ ] **Step 2: Verify the CLI commands run**

  ```bash
  bench --site frappe.localhost conductor schedule list
  ```

  Expected: prints a table (possibly empty) without error.

- [ ] **Step 3: Commit**

  ```bash
  git add docs/how-to-schedule-jobs.md
  git commit -m "docs(v1): how-to schedule jobs"
  ```

---

## Task 9: `how-to-define-workflows.md`

**Files:**
- Create: `docs/how-to-define-workflows.md`
- Read: `conductor/workflow/decorator.py`, `conductor/workflow/dispatcher.py`, `conductor/workflow/topo.py`, `conductor/workflow/cancellation.py`, `conductor/commands/workflow.py`, `README.md` ("Workflows (Phase 5)" section)

- [ ] **Step 1: Draft four procedures.**

  - First paragraph (≤ 3 lines): app-developer audience; success = a DAG runs end-to-end and partial failure triggers the right compensations.
  - **Procedure 1 — Define a DAG.** Use the `OrderFulfillment` example from the README verbatim. Walk through `Step("name", depends_on=(...), compensation=...)`.
  - **Procedure 2 — Add a compensation.** Show one step with and one step without a compensation; explain the difference.
  - **Procedure 3 — Trigger, status, cancel.** Three code blocks: `conductor.run_workflow(...)`, `bench conductor workflow status <run_id>`, `conductor.cancel_workflow_run(run_id)`.
  - **Procedure 4 — Read partial-rollback semantics.** When a compensation itself terminally fails, earlier completed steps are **not** compensated; the run lands `FAILED` and the operator triages from the dashboard. Link to `explanation-reliability.md#workflow-compensations`.
  - **If something went wrong** — 3 entries: (1) `WorkflowNotFoundError` → the workflow class isn't imported anywhere your worker loads; (2) cycle detected → the DAG has a cycle (link to topo); (3) a step's compensation never ran → the prior step had not yet completed when the failure happened (which is correct).

- [ ] **Step 2: Verify the example imports**

  ```bash
  bench --site frappe.localhost console <<'EOF'
  from conductor.workflow import workflow, Step
  print(workflow, Step)
  EOF
  ```

  Expected: prints decorator and class.

- [ ] **Step 3: Verify CLI commands**

  ```bash
  bench --site frappe.localhost conductor workflow list
  ```

  Expected: prints a list (possibly empty) without error.

- [ ] **Step 4: Commit**

  ```bash
  git add docs/how-to-define-workflows.md
  git commit -m "docs(v1): how-to define workflows"
  ```

---

## Task 10: `how-to-triage-failures.md`

**Files:**
- Create: `docs/how-to-triage-failures.md`
- Read: `conductor/commands/dlq.py`, `conductor/conductor/doctype/conductor_dlq_entry/conductor_dlq_entry.json`, `dashboard/src/pages/DlqPage.vue` (or whatever the dashboard DLQ page is)

- [ ] **Step 1: Find the dashboard DLQ page** to confirm which actions it exposes:

  ```bash
  ls /Users/osamamuhammed/frappe_15/apps/conductor/dashboard/src/pages/
  grep -rn 'DLQ\|dlq' /Users/osamamuhammed/frappe_15/apps/conductor/dashboard/src/pages/ | head
  ```

- [ ] **Step 2: Draft three procedures.**

  - First paragraph (≤ 3 lines): operator audience; success = a failed job is found, decided on, and resolved (retry / edit-and-retry / discard).
  - **Procedure 1 — Find a failed job.** Two paths: (a) dashboard DLQ tab (filter by queue, click row for traceback); (b) CLI:

    ```bash
    bench --site frappe.localhost conductor dlq list --queue default
    ```

  - **Procedure 2 — Retry one or many.** Dashboard multi-select + Retry button; CLI:

    ```bash
    bench --site frappe.localhost conductor dlq retry --queue default --limit 50
    ```

    Edit-and-retry — dashboard only (System Manager).

  - **Procedure 3 — Discard.** Dashboard discard action and CLI:

    ```bash
    bench --site frappe.localhost conductor dlq discard --job <job_id>
    ```

    Note that discard is destructive and System Manager only.

  - **Permissions** subsection — link to `reference-configuration.md#roles-and-permissions` and summarize: read = both roles; retry = both; discard / edit-and-retry = System Manager only.
  - **If something went wrong** — 3 entries: (1) DLQ list is empty but you expect entries → wrong queue filter; (2) retry succeeds but the job fails again immediately → underlying bug, not a transient failure (link to `explanation-reliability.md`); (3) discard returns "not found" → another operator already handled it.

- [ ] **Step 3: Verify CLI commands**

  ```bash
  bench --site frappe.localhost conductor dlq list --queue default
  ```

  Expected: prints a list (possibly empty) without error.

- [ ] **Step 4: Commit**

  ```bash
  git add docs/how-to-triage-failures.md
  git commit -m "docs(v1): how-to triage failures"
  ```

---

## Task 11: `how-to-run-multi-tenant.md`

**Files:**
- Create: `docs/how-to-run-multi-tenant.md`
- Read: `conductor/site_discovery.py`, `conductor/worker.py` (look for `--sites` branches), `conductor/inflight.py`, `conductor/rate_limit.py`, `conductor/commands/depth.py`, `conductor/conductor/doctype/conductor_queue/conductor_queue.json` (for `max_rps` / `max_concurrent`)

- [ ] **Step 1: Draft three procedures.**

  - First paragraph (≤ 3 lines): operator audience; success = one process serves N sites with per-tenant caps that throttle without failing jobs.
  - **Procedure 1 — Switch a worker to pool mode.** Two invocations:

    ```bash
    bench conductor worker --sites=auto --queue default --concurrency 8
    bench conductor worker --sites=alpha.test,beta.test --queue default --concurrency 8
    ```

    Note: `--sites=auto` walks `sites/<dir>/site_config.json` and keeps only those with `conductor` in `installed_apps`. The site list is resolved once at boot — onboarding a new tenant requires restarting the pool worker.

  - **Procedure 2 — Set per-tenant caps.** Open `Conductor Queue` in the Desk for the relevant site; set `max_rps` and `max_concurrent`. Explain that throttled jobs land in `SCHEDULED_RETRY` with `last_error_message="rate_limited"` or `"inflight_capped"` — they are **not** failures.

  - **Procedure 3 — Inspect per-(site, queue) depth.**

    ```bash
    bench --site=alpha.test conductor depth
    bench conductor depth --all-sites
    ```

  - **If something went wrong** — 3 entries: (1) pool worker doesn't pick up a new site → restart required; (2) `max_rps=10` but 100 jobs ran in a second → caps are per pool process, not fleet-wide (link to `explanation-architecture.md`); (3) jobs stuck in `SCHEDULED_RETRY` → rate limit too tight, raise the cap.

- [ ] **Step 2: Verify the depth command**

  ```bash
  bench --site frappe.localhost conductor depth
  ```

  Expected: prints per-queue depth without error.

- [ ] **Step 3: Commit**

  ```bash
  git add docs/how-to-run-multi-tenant.md
  git commit -m "docs(v1): how-to run multi-tenant"
  ```

---

## Task 12: `how-to-migrate-from-rq.md`

**Files:**
- Create: `docs/how-to-migrate-from-rq.md`
- Read: `conductor/migrate_rq.py`, `conductor/commands/migrate_rq.py`

- [ ] **Step 1: Confirm the migration command surface** by reading both files. Capture: dry-run vs commit, the marker file/key, what `--force` does, what gets moved (which RQ queues / job statuses) and what does not.

- [ ] **Step 2: Draft three procedures.**

  - First paragraph (≤ 3 lines): operator audience with an existing RQ deployment; success = pending RQ jobs land on Conductor queues without duplication.
  - **Procedure 1 — Dry-run.**

    ```bash
    bench --site=alpha.test conductor migrate-from-rq
    ```

    Explain what the preview output means.

  - **Procedure 2 — Commit.**

    ```bash
    bench --site=alpha.test conductor migrate-from-rq --commit
    ```

    Explain the marker (idempotency: a re-run after success is a no-op).

  - **Procedure 3 — Re-run after the marker.**

    ```bash
    bench --site=alpha.test conductor migrate-from-rq --commit --force
    ```

    Explain when this is appropriate and the duplication risk if used carelessly.

  - **What is moved and what is not** — explicit list. Read `migrate_rq.py` and write down which RQ statuses are migrated.
  - **If something went wrong** — 3 entries: (1) "marker present, skipping" → use `--force` if you really mean it; (2) jobs land but worker doesn't pick them up → no `bench conductor worker` for that queue; (3) RQ keys still present after migration → expected; the migration copies, it does not delete RQ state.

- [ ] **Step 3: Verify command surface**

  ```bash
  bench --site frappe.localhost conductor migrate-from-rq --help
  ```

  Expected: shows `--commit` and `--force` flags. (No need to actually run the migration on the dev bench — the dry-run is enough if RQ has any pending jobs.)

- [ ] **Step 4: Commit**

  ```bash
  git add docs/how-to-migrate-from-rq.md
  git commit -m "docs(v1): how-to migrate from RQ"
  ```

---

## Task 13: `tutorial-getting-started.md`

**Files:**
- Create: `docs/tutorial-getting-started.md`
- Read: `README.md` (Install / Run / Configuration sections), `conductor/install.py`, `conductor/doctor.py`, `Procfile.conductor`

- [ ] **Step 1: Draft the tutorial as a single happy path.** No branches. ~10 minutes for a new operator on a fresh bench.

  Sections:

  1. **What you'll build** (≤ 3 lines): a working Conductor install that runs one job end-to-end.
  2. **Before you start** — bullet list of prerequisites (a Frappe bench, Redis running, a site).
  3. **Step 1: Install Conductor on a site.**

     ```bash
     bench --site <site> install-app conductor
     ```

  4. **Step 2: Configure the Redis URL.** Show `site_config.json` with `conductor.redis_url` and the fallback note. Link to `reference-configuration.md`.
  5. **Step 3: Start the worker and scheduler via Procfile.**

     ```bash
     cat apps/conductor/Procfile.conductor >> Procfile
     bench start
     ```

  6. **Step 4: Enqueue your first job.**

     ```bash
     bench --site <site> console
     ```

     ```python
     import conductor
     job_id = conductor.enqueue("frappe.utils.now")
     print(job_id)
     ```

  7. **Step 5: Watch it on the dashboard.** Open `https://<site>/conductor-dashboard`, click **Live Feed**, find the job by id.
  8. **Step 6: Run the doctor.**

     ```bash
     bench --site <site> conductor doctor --demo
     ```

     Expected output: 4 checks pass plus a full dispatch round-trip. Exit code 0.
  9. **What's next** — links to `how-to-enqueue-jobs.md` (your second job), `explanation-architecture.md` (how it works), `reference-cli.md` (everything else).

- [ ] **Step 2: Run the entire tutorial end-to-end** on the local bench. If any step fails or produces output that contradicts the doc, fix the doc.

  ```bash
  bench --site frappe.localhost conductor doctor --demo
  ```

  Expected: 4 checks plus the demo dispatch all green; exit 0.

- [ ] **Step 3: Commit**

  ```bash
  git add docs/tutorial-getting-started.md
  git commit -m "docs(v1): getting-started tutorial"
  ```

---

## Task 14: `index.md`

**Files:**
- Create: `docs/index.md`

- [ ] **Step 1: Draft the index.**

  - Title: `# Conductor — Documentation`.
  - One paragraph (≤ 3 lines): "Conductor is a reliability-first background job platform for Frappe / ERPNext. These docs are organized by what you're trying to do."
  - **Two-column "Start here" block** (rendered as two `##` sections side by side via Markdown — not literal columns; just two consecutive sections):

    - **Operate Conductor** → links to `tutorial-getting-started.md` · `how-to-schedule-jobs.md` · `how-to-triage-failures.md` · `how-to-run-multi-tenant.md` · `how-to-migrate-from-rq.md` · `reference-cli.md` · `reference-configuration.md`.
    - **Use Conductor in your app** → links to `tutorial-getting-started.md` · `how-to-enqueue-jobs.md` · `how-to-define-workflows.md` · `reference-python-api.md`.

  - **Understand Conductor** section linking the three explanations: `explanation-why-conductor.md` · `explanation-architecture.md` · `explanation-reliability.md`.
  - Footer: "Found a mistake? Open a PR — docs live in this repo and ship with the code." Link to the repo root README.

- [ ] **Step 2: Verify all links resolve** by clicking each one (or, scripted):

  ```bash
  cd /Users/osamamuhammed/frappe_15/apps/conductor/docs
  for f in $(grep -oE '\([a-z-]+\.md(#[a-z0-9-]+)?\)' index.md | sed 's/[()]//g' | cut -d'#' -f1 | sort -u); do
    [ -f "$f" ] || echo "MISSING: $f"
  done
  ```

  Expected: no `MISSING:` output.

- [ ] **Step 3: Commit**

  ```bash
  git add docs/index.md
  git commit -m "docs(v1): index landing page"
  ```

---

## Task 15: README rewrite

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rewrite the README** to keep only:

  1. Title and one-paragraph "what is Conductor".
  2. The current `## Why Conductor (vs Frappe RQ)` **At a glance** bullet list, plus one sentence pointing to `docs/explanation-why-conductor.md` for the table and methodology. **Remove** the full KPI table, methodology paragraphs, and "what we do not claim" — those live in `docs/explanation-why-conductor.md` now.
  3. Quickstart: install command, `bench --site <site> conductor doctor --demo`, the four-line `bench start` Procfile snippet. (3–5 commands total.)
  4. A `## Documentation` section with bulleted links to:
     - `docs/index.md` (start here)
     - `docs/tutorial-getting-started.md`
     - `docs/reference-cli.md`
     - `docs/reference-configuration.md`
     - `docs/explanation-why-conductor.md`
  5. Status (Phase 6 of 6 — v1) with a one-line link to the master spec. Keep this short.
  6. `## Contributing` (existing pre-commit copy, unchanged) plus one new line: "Behavior change → docs PR in the same commit."
  7. License.

  **Remove** in their entirety: the `## Operations (Phase 2+)` block, `## Workflows (Phase 5)` block, `## Multi-tenant deployments (Phase 6)` block, `## Dashboard (Phase 3)` block, and any other deep section. Each becomes a single bullet under `## Documentation` linking to the relevant `docs/` page.

- [ ] **Step 2: Verify the README renders** by opening it on GitHub or pasting into a Markdown previewer. Confirm: no broken links, no leftover headings without bodies, KPI bullets still display the emoji prefixes.

- [ ] **Step 3: Verify links resolve**

  ```bash
  cd /Users/osamamuhammed/frappe_15/apps/conductor
  for f in $(grep -oE '\(docs/[a-z-]+\.md\)' README.md | sed 's/[()]//g' | sort -u); do
    [ -f "$f" ] || echo "MISSING: $f"
  done
  ```

  Expected: no `MISSING:` output.

- [ ] **Step 4: Commit**

  ```bash
  git add README.md
  git commit -m "docs(v1): trim README to quickstart + docs links"
  ```

---

## Task 16: Cleanup and final verification

**Files:**
- Delete: `docs/audit.md`
- Verify: all of `docs/`

- [ ] **Step 1: Remove the stale audit**

  ```bash
  git rm docs/audit.md
  ```

- [ ] **Step 2: Confirm the file inventory**

  ```bash
  ls /Users/osamamuhammed/frappe_15/apps/conductor/docs/*.md
  ```

  Expected: exactly these 14 files —

  ```
  docs/index.md
  docs/tutorial-getting-started.md
  docs/how-to-enqueue-jobs.md
  docs/how-to-schedule-jobs.md
  docs/how-to-define-workflows.md
  docs/how-to-triage-failures.md
  docs/how-to-run-multi-tenant.md
  docs/how-to-migrate-from-rq.md
  docs/reference-cli.md
  docs/reference-python-api.md
  docs/reference-configuration.md
  docs/explanation-why-conductor.md
  docs/explanation-architecture.md
  docs/explanation-reliability.md
  ```

  No `audit.md`. `docs/superpowers/` unchanged.

- [ ] **Step 3: Grep for forbidden terms across all of `docs/`**

  ```bash
  grep -rniE 'dead letter|cron daemon|\btopic\b|\bconsumer\b' /Users/osamamuhammed/frappe_15/apps/conductor/docs/*.md
  ```

  Expected: no matches.

  Then check "task" usage carefully:

  ```bash
  grep -rniE '\btasks?\b' /Users/osamamuhammed/frappe_15/apps/conductor/docs/*.md
  ```

  Expected: every match is legitimate English ("the task at hand", "task list"), **never** used to mean a Conductor execution. Fix any that conflate "task" with "job".

- [ ] **Step 4: Verify every internal link resolves**

  ```bash
  cd /Users/osamamuhammed/frappe_15/apps/conductor/docs
  python3 - <<'EOF'
  import re, pathlib
  failures = []
  for p in pathlib.Path(".").glob("*.md"):
      text = p.read_text()
      for m in re.finditer(r'\]\(([^)#]+)(?:#[^)]+)?\)', text):
          target = m.group(1)
          if target.startswith(("http://", "https://", "../")):
              continue
          if not pathlib.Path(target).exists():
              failures.append(f"{p.name}: broken link → {target}")
  for f in failures:
      print(f)
  print(f"OK ({len(failures)} broken)" if not failures else f"FAIL ({len(failures)} broken)")
  EOF
  ```

  Expected: `OK (0 broken)`.

- [ ] **Step 5: Re-read each page top-to-bottom** for the conventions checklist:

  - First paragraph leads with the answer.
  - Active voice throughout.
  - Procedures use numbered steps; facts use bullets.
  - Every how-to has an "If something went wrong" section.
  - First mention of *idempotency key*, *DLQ*, *compensation*, *singleton*, *at-least-once* links to its `explanation-*` page.
  - Paragraphs ≤ 4 lines.

  Fix any drift inline.

- [ ] **Step 6: Run the doctor one last time** as a smoke test that nothing in the docs branch broke the install:

  ```bash
  bench --site frappe.localhost conductor doctor --demo
  ```

  Expected: exit 0, all checks green.

- [ ] **Step 7: Commit**

  ```bash
  git add -A docs/
  git commit -m "docs(v1): remove stale audit.md, final consistency pass"
  ```

---

## Self-review

**Spec coverage:**

- 14 files listed in the spec → 14 tasks (Tasks 1–14) producing them. ✅
- README treatment → Task 15. ✅
- `docs/audit.md` removal → Task 16, Step 1. ✅
- Conventions (active voice, lead with the answer, runnable code samples, error-recovery sections, no jargon, stable anchors, short paragraphs, consistent vocabulary) → enforced per-task in drafting steps and re-checked in Task 16, Step 5. ✅
- Cross-linking strategy → enforced in each how-to and explanation task; verified in Task 14, Step 2 and Task 16, Step 4. ✅
- `superpowers/specs/` unchanged → guarded by per-task `git add` paths. ✅
- Acceptance criterion 7 (no deprecated terms) → Task 1 Step 5, Task 16 Step 3. ✅

**Spec corrections noted in the plan (not in the spec):**

- DocType count: spec said 5; actual 9. Plan covers all 9 in Task 3.
- Python API surface: spec listed 6 symbols; actual ~10. Plan covers all in Task 2.

**No placeholders.** No "TBD", "fill in later", or "similar to Task N". Every task carries the source-file pointers and verification commands the engineer needs.

**Type / name consistency.**

- `conductor.enqueue`, `conductor.run_workflow`, `conductor.cancel`, `conductor.cancel_workflow_run`, `conductor.RetryPolicy`, `conductor.workflow.workflow`, `conductor.workflow.Step` — same names used in Tasks 2, 7, 8, 9.
- DocType names use Frappe display form (`Conductor Queue`, etc.) consistently across Tasks 3, 8, 11.
- Status names (`PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `SCHEDULED_RETRY`, `DLQ`) match in Tasks 3, 6, 11.
- File names match across cross-link references in Tasks 7–14.

---

## Execution

Per the writing-plans skill, the engineer chooses how to execute. Inline execution (`superpowers:executing-plans`) suits this plan well — same conventions across all pages benefit from a single voice — but subagent-driven execution also works because each task is self-contained with explicit source-file pointers.
