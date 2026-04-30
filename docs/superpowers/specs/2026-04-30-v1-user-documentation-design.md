# Conductor v1 — User Documentation (Design)

Date: 2026-04-30
Status: Approved (brainstorming complete; awaiting user review of this spec)
Scope: Documentation only. App polish is deferred to a separate branch.

## Goal

Ship a complete, scannable, user-facing documentation set for Conductor v1
under `docs/` using the Diátaxis framework (tutorials / how-to / reference /
explanation). Audience is operators first, app developers second. The README
shrinks to a quickstart and links into `docs/` for everything else.

## Non-goals

- App polish (code refactors, audit follow-up, dashboard UX). Deferred.
- Static-site generator (MkDocs/Sphinx). v1 ships plain Markdown that renders
  on GitHub. Re-evaluate in v1.1.
- Translating existing internal specs (`docs/superpowers/specs/`) into user
  docs. Those stay where they are as design history.
- New features. If a docs draft surfaces a missing behavior, file an issue —
  do not patch the code on this branch.

## Audience

Two reader personas, both served by the same docs but with operator-first
ordering:

1. **Operator** (primary) — Frappe sysadmin who installs Conductor, runs
   workers and the scheduler, configures `site_config.json`, triages the
   DLQ, manages schedules in the Desk dashboard. Reads CLI and configuration
   reference; rarely writes Python.
2. **App developer** (secondary) — Frappe app author who calls
   `conductor.enqueue(...)`, defines `@workflow` classes, registers
   schedules. Reads the Python API reference; rarely touches Procfiles.

The index page splits navigation by persona. Tutorials and how-tos are
written for the persona who will perform that task most often.

## Layout

Flat hierarchy. Every user-facing page sits directly under `docs/`. One
`index.md` is the landing page; all other Markdown files are leaf documents.
File names start with the Diátaxis type so the directory listing is itself
navigation.

```
docs/
├── index.md
├── tutorial-getting-started.md
├── how-to-enqueue-jobs.md
├── how-to-schedule-jobs.md
├── how-to-define-workflows.md
├── how-to-triage-failures.md
├── how-to-run-multi-tenant.md
├── how-to-migrate-from-rq.md
├── reference-cli.md
├── reference-python-api.md
├── reference-configuration.md
├── explanation-why-conductor.md
├── explanation-architecture.md
├── explanation-reliability.md
└── superpowers/                # unchanged — internal design history
    └── specs/
        └── …
```

`docs/audit.md` is removed (stale internal audit; user opted to defer the
findings, so the document no longer earns its place).

## Per-page contracts

Each page has one job. The contract below is what reviewers check the
draft against.

### `index.md`

- Two-column landing: "Operate Conductor" vs "Use Conductor in your app".
- Each column links the relevant tutorial → how-tos → reference page.
- A bottom row links the three explanation pages.
- ≤ 80 lines. No prose beyond the two introductory paragraphs (one per
  persona).

### `tutorial-getting-started.md`

- Operator-first 10-minute guided walkthrough.
- Single happy path; no branches; no "if you also want X" detours.
- Steps: install the app on a site → set `conductor.redis_url` →
  append the Procfile lines and start `bench start` → enqueue one job
  from `bench console` → watch it complete on the dashboard → run
  `bench conductor doctor --demo`.
- Ends with "What's next" linking to two how-tos and the architecture
  explanation.

### `how-to-enqueue-jobs.md`

Three named procedures:

1. Enqueue a job from a Frappe app (`conductor.enqueue(...)`).
2. Make an enqueue idempotent (`idempotency_key`).
3. Override `frappe.enqueue` app-wide via `hooks.py`.

Each procedure: 3–6 numbered steps + a copy-pasteable code block. Page
ends with "If something went wrong" listing the 2–4 most likely failures.

### `how-to-schedule-jobs.md`

Procedures:

1. Create a `Conductor Schedule` in the Desk (required fields, cron
   validation, timezone).
2. Manage schedules from the CLI (`schedule list/enable/disable/run-now`).
3. Make a scheduled method safe under at-least-once delivery.

### `how-to-define-workflows.md`

Procedures:

1. Define a DAG with `@workflow` and `Step(...)`.
2. Add a compensation for a step.
3. Trigger a run (`conductor.run_workflow(...)`), check status, cancel.
4. Understand partial-rollback semantics when a compensation itself
   fails (link to `explanation-reliability.md`).

### `how-to-triage-failures.md`

Procedures:

1. Find a failed job (dashboard DLQ tab + `dlq list`).
2. Retry one job, retry many, edit-and-retry, discard.
3. Permissions: who can do what (System Manager vs Conductor Operator).

### `how-to-run-multi-tenant.md`

Procedures:

1. Switch a worker to pool mode (`--sites=auto` / `--sites=a,b`).
2. Set `max_rps` and `max_concurrent` on a `Conductor Queue`.
3. Inspect per-(site, queue) depth (`depth --all-sites`).

### `how-to-migrate-from-rq.md`

Procedures:

1. Dry-run the migration.
2. Commit the migration.
3. Re-run after the marker is set (`--force`); what is moved and what is
   not.

### `reference-cli.md`

One subsection per subcommand. Each subsection:

- Synopsis (one line).
- Options table.
- 1–2 examples.
- Exit codes (where non-trivial).

Subcommands covered: `worker`, `scheduler`, `doctor`, `schedule *`, `dlq *`,
`depth`, `migrate-from-rq`, `workflow *`, `cancel`.

### `reference-python-api.md`

One subsection per public symbol. Each subsection:

- Signature (Python type-annotated).
- Parameters (table).
- Return value.
- Raises.
- Minimal example.

Symbols covered: `conductor.enqueue`, `conductor.run_workflow`,
`conductor.workflow.workflow` (decorator), `conductor.workflow.Step`,
`conductor.context.Context`, `conductor.frappe_compat.enqueue`.

### `reference-configuration.md`

Three subsections:

1. `site_config.json` keys (table: key, type, default, meaning).
2. DocType fields — `Conductor Queue`, `Conductor Job`, `Conductor
   Worker`, `Conductor Schedule`, `Conductor Workflow Run` (one table
   per DocType).
3. Roles and permissions — System Manager vs Conductor Operator,
   matrixed against destructive vs read-only actions.
4. Job state machine — Mermaid `stateDiagram-v2` showing PENDING →
   RUNNING → SUCCEEDED / FAILED / SCHEDULED_RETRY → DLQ with allowed
   transitions.

### `explanation-why-conductor.md`

- The KPI table from the current README, verbatim.
- Methodology paragraph (how each KPI was measured).
- "What we do not claim" honesty paragraph (KPI 6 dropped, Linux caveat).
- Link to the KPI plan spec.

### `explanation-architecture.md`

- Redis stream keyspace (`conductor:{site}:stream:{queue}`,
  `…:rate:{queue}`, `…:inflight:{queue}`).
- Dispatcher → stream → worker hand-off.
- Scheduler singleton + lock; failover within ~20 s.
- Pool worker model and site discovery.
- Sweeper / reaper loops.
- One architecture diagram (Mermaid `flowchart LR`).

### `explanation-reliability.md`

- At-least-once delivery contract.
- Idempotency keys (Lua-enforced; what protects against; what does not).
- Retry backoff and `SCHEDULED_RETRY` lifecycle.
- DLQ semantics (when a job lands there; when it does not).
- Workflow compensation order; partial-rollback rule when a
  compensation itself terminally fails.

## Conventions

These apply to every page. Reviewers check drafts against this checklist.

- **Lead with the answer.** First paragraph (≤ 3 lines): what the page
  covers, who it is for, what success looks like.
- **Active voice.** "Run `bench conductor doctor`" — not "the doctor
  command should be run".
- **Numbered steps for procedures, bullets for facts.** Consistent
  across all pages.
- **Runnable code samples.** Every `bench …` and `import conductor`
  snippet must work against a real install. No pseudocode.
- **Errors are recoverable.** Every how-to ends with an "If something
  went wrong" section: 2–4 most likely failures, each with a one-line
  fix.
- **Define jargon on first use.** First mention of *idempotency key*,
  *DLQ*, *compensation*, *singleton*, *at-least-once* links to its
  `explanation-*` page.
- **Stable anchors.** Every `## heading` becomes a link target. Do not
  rename a heading without grepping the docs for incoming links.
- **Short paragraphs (≤ 4 lines).** Long blocks break into bullets.
- **Domain vocabulary is consistent.** "Job" not "task"; "queue" not
  "topic"; "worker" not "consumer"; "scheduler" not "cron daemon";
  "DLQ" not "dead letter".

## Cross-linking

- How-tos link forward to reference for any flag/method they use.
- How-tos link back to explanation for any concept they invoke.
- Explanation pages link down to reference (concrete) and up to the
  tutorial (newcomers).
- The reference pages do not link to how-tos (reference is a lookup
  surface; readers come in cold).

## README treatment

Today's README is comprehensive and partly duplicates what the new docs
will cover. After docs land, the README shrinks to:

1. One-paragraph "what is Conductor".
2. The KPI summary bullet list (the "At a glance" block) — kept for
   GitHub readers — with a link to `docs/explanation-why-conductor.md`.
3. Quickstart: install, run worker, enqueue. (3–5 commands.)
4. A "Documentation" section linking to `docs/index.md` and the four
   most-trafficked pages (tutorial, configuration reference, CLI
   reference, why-conductor).
5. Status, contributing, license.

The Operations / Workflows / Multi-tenant sections move out of the
README entirely. Their replacement is one-line "see
[`docs/how-to-…`]" links.

## Maintenance (docs-as-code)

- Docs live in the same repo, reviewed in the same PR as the code that
  changes them.
- A one-line note in `CONTRIBUTING.md` (or this README's contributing
  section): *"Behavior change → docs PR in the same commit."*
- No CI doc-build for v1; GitHub renders the Markdown. Re-evaluate
  MkDocs / Sphinx in v1.1 only if the page count or cross-linking
  outgrows plain Markdown.

## Out of scope (explicit list)

- Translating internal specs into user docs.
- Building a docs site or hosting outside GitHub.
- API-stability guarantees beyond what the code documents.
- Acting on `docs/audit.md` findings. The file is removed; findings can
  be re-filed as issues if revisited.
- Changes to the Conductor codebase, except to fix a docstring or
  example that the new docs would otherwise misquote.

## Acceptance criteria

The docs branch is done when:

1. All 14 files listed above exist under `docs/` and pass a manual
   read-through.
2. Every code sample in every how-to has been executed against a real
   bench (`/Users/osamamuhammed/frappe_15`) and produced the documented
   result.
3. Every Diátaxis type tag in a filename matches the page's content
   type (no how-to disguised as reference, etc.).
4. The README has been trimmed per the "README treatment" section and
   links to `docs/index.md`.
5. `docs/audit.md` is removed.
6. `docs/superpowers/specs/` is unchanged.
7. A grep for the deprecated terms ("dead letter", "task" used for
   "job", "cron daemon") returns zero hits in `docs/`.
