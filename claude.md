# CLAUDE.md — Clean Code Rules

Use this file as the default coding standard for this repository.  
When in doubt, optimize for readability, change safety, and low cognitive load.

## Core principles

- Prefer code that is easy for humans to read, understand, and modify.
- Keep the design simple; do not introduce abstraction unless it clearly reduces complexity.
- Remove duplication aggressively.
- Make intent obvious in the code itself.
- Leave every file, function, and class cleaner than you found it.

## Naming

- Use intention-revealing names.
- Choose names that explain purpose, not implementation details.
- Avoid abbreviations unless they are universally understood in the codebase.
- Avoid names that differ by only a letter or two.
- Keep names pronounceable and searchable.
- Use domain vocabulary consistently.
- Do not encode types, prefixes, or implementation details in names unless they add real value.
- Prefer nouns for classes and verbs for functions.
- Prefer precise names over short clever ones.
- Use one word per concept and one concept per word.

## Functions

- Keep functions small.
- Each function should do one thing and do it well.
- A function should have a single level of abstraction.
- Read code top to bottom like a story.
- Minimize arguments; 0–2 is ideal, 3 is a warning sign, more than 3 should be exceptional.
- Avoid output parameters.
- Prefer pure functions when possible.
- Avoid flag arguments.
- Avoid side effects unless they are the explicit purpose of the function.
- Use descriptive names for functions.
- Prefer command/query separation: a function should either do work or return information, not both.
- Keep control flow straightforward and shallow.
- Extract nested logic into well-named helper functions.
- Avoid switch or if chains that repeat the same pattern; replace them with polymorphism, maps, or strategy objects when appropriate.

## Comments

- Write comments only when they add information that the code cannot express itself.
- Do not use comments to explain bad names or bad structure; fix the code instead.
- Avoid redundant, stale, or misleading comments.
- Avoid commented-out code.
- Use comments for legal requirements, non-obvious intent, public API constraints, and unusually tricky tradeoffs.
- Prefer self-explanatory code over comment-heavy code.

## Formatting

- Keep formatting consistent across the repository.
- Use vertical whitespace to separate concepts.
- Keep related code close together.
- Use blank lines to show logical boundaries.
- Keep line length reasonable for readability.
- Align formatting with the team’s conventions and automated formatters.
- Make the visual structure of the file communicate the structure of the design.

## Objects and data structures

- Prefer objects when behavior should stay close to data.
- Prefer data structures when you want to add new functions without changing existing types.
- Prefer encapsulation over exposing internals.
- Do not violate the Law of Demeter; talk to friends, not strangers.
- Hide implementation details behind behavior-focused methods.
- Avoid train-wreck navigation chains.
- Choose the right abstraction for the job; “everything is an object” is not a rule.

## Error handling

- Use exceptions rather than return codes when the language and architecture support them.
- Keep error handling separate from the happy path.
- Handle errors at the correct level of abstraction.
- Do not let error-handling logic obscure business logic.
- Fail fast on invalid inputs.
- Validate assumptions at boundaries.
- Throw meaningful errors with enough context to diagnose the failure.
- Prefer one clear strategy for error propagation in each layer.
- Do not swallow errors silently.

## Tests

- Test code must be as clean as production code.
- Tests should be readable, focused, and easy to maintain.
- Keep test setup minimal and expressive.
- Use descriptive test names that explain behavior.
- Test one behavior per test when practical.
- Keep tests deterministic.
- Cover boundary conditions, error paths, and important edge cases.
- Prefer automated tests over manual verification.
- Refactor dirty tests immediately; dirty tests are technical debt.
- Tests should protect design, not just validate outputs.

## Classes

- Keep classes small.
- A class should have one reason to change.
- Prefer cohesion over convenience.
- Put related behavior together.
- Expose the smallest useful surface area.
- Avoid “god classes” and classes that mix too many responsibilities.
- Keep constructors simple.
- Prefer composition over inheritance when it reduces coupling.
- Classes should read like focused parts of a system, not mini-applications.

## Concurrency

- Treat concurrency as a design constraint, not an afterthought.
- Keep shared mutable state to a minimum.
- Prefer immutability where possible.
- Separate what must happen from when it happens.
- Keep concurrent code as simple and isolated as possible.
- Make thread-safety assumptions explicit.
- Test concurrent behavior carefully.

## Smells to eliminate

- Duplication.
- Long functions.
- Large classes.
- Deep nesting.
- Mixed abstraction levels.
- Hard-coded magic values.
- Poorly chosen names.
- Excessive comments.
- Hidden side effects.
- Tight coupling.
- Premature generalization.
- Data clumps.
- Feature envy.
- Dead code.
- Inconsistent formatting.
- Dirty tests.

## Practical decision rules

- If the code is hard to explain, simplify it.
- If a name needs a comment, rename it.
- If a function needs a paragraph of explanation, split it.
- If a class keeps growing, split responsibilities.
- If a change touches too many files, revisit the boundaries.
- If a test is hard to read, rewrite it.
- If a design choice only helps today’s case, avoid locking it in too early.
- If two things change for different reasons, separate them.

## Review checklist

Before merging, verify:

- Names reveal intent.
- Functions are short and single-purpose.
- Tests are clear and sufficient.
- Comments are necessary and accurate.
- Formatting is consistent.
- Error handling does not obscure logic.
- Classes are cohesive and small.
- The code avoids unnecessary duplication.
- The design is easy to extend without large rewrites.
- The final result is simpler than the version that came before it.

## Project structure

`conductor/` is a Frappe app shipping a reliability-first background job
platform. It coexists with `frappe.enqueue` / RQ on the same Redis instance.

```
conductor/                                          repo root
├── conductor/                                      Python package (the Frappe app)
│   ├── __init__.py                                 public API: enqueue, job, RetryPolicy, run_workflow, cancel
│   ├── api/                                        whitelisted Frappe endpoints
│   │   ├── dashboard.py                            REST surface consumed by the SPA
│   │   ├── workflows.py                            workflow-specific endpoints
│   │   └── json_safety.py                          JSON serialization helpers
│   ├── commands/                                   `bench conductor <subcommand>` entrypoints
│   │   ├── worker.py                               long-lived worker (single-site or pool mode)
│   │   ├── scheduler.py                            singleton scheduler (delay / cron / reaper / drift)
│   │   ├── doctor.py                               health-check + optional --demo round-trip
│   │   ├── schedule.py                             list / enable / disable / run-now schedules
│   │   ├── dlq.py                                  inspect + bulk-retry the DLQ
│   │   ├── depth.py                                queue-depth dump
│   │   ├── cancel.py                               cancel a running job
│   │   ├── workflow.py                             workflow-run inspection + cancel
│   │   └── migrate_rq.py                           one-shot RQ → Conductor importer
│   ├── conductor/doctype/                          DocType definitions (JSON + controllers)
│   │   ├── conductor_queue/                        queue config + per-tenant limits
│   │   ├── conductor_job/                          one row per dispatch (audit head)
│   │   ├── conductor_job_run/                      one row per attempt (per-attempt audit)
│   │   ├── conductor_dlq_entry/                    dead-letter rows
│   │   ├── conductor_schedule/                     cron schedules
│   │   ├── conductor_worker/                       worker registration + heartbeat
│   │   ├── conductor_workflow/                     workflow definition snapshot
│   │   ├── conductor_workflow_run/                 one row per workflow run
│   │   └── conductor_workflow_step_run/            one row per step attempt (incl. compensations)
│   ├── workflow/                                   DAG runner
│   │   ├── decorator.py                            @workflow + Step descriptors
│   │   ├── dispatcher.py                           run_workflow entrypoint
│   │   ├── advancer.py                             post-step DAG re-evaluation
│   │   ├── topo.py                                 topological sort + cycle detection
│   │   ├── lua.py                                  fan-in dependency counter (single-key)
│   │   ├── snapshot.py                             definition versioning (immutable per run)
│   │   ├── idempotency.py                          per-step idempotency keys
│   │   ├── cancellation.py                         cancel_workflow_run
│   │   ├── worker_hooks.py                         step lifecycle hooks called from worker
│   │   └── keys.py                                 Redis key namespacing
│   ├── config/                                     site-config loader
│   ├── patches/                                    one-shot migrations run on `bench migrate`
│   ├── public/                                     static assets served by Frappe
│   ├── templates/                                  Frappe Jinja templates
│   ├── www/                                        public routes (e.g. /conductor-dashboard)
│   ├── dispatcher.py                               write Job row → idem lock → XADD → publish
│   ├── worker.py                                   XREADGROUP loop + execution lock + retry/DLQ
│   ├── scheduler.py                                leader election + lock renewer
│   ├── scheduler_loops.py                          delay drainer, cron loop, reaper, drift correction
│   ├── retry.py                                    RetryPolicy + backoff strategies
│   ├── messages.py                                 stream message schema (encode/decode)
│   ├── streams.py                                  per-(site, queue) stream key + consumer group
│   ├── rate_limit.py / rate_limit.lua              per-(site, queue) token bucket
│   ├── inflight.py / inflight.lua                  per-(site, queue) concurrency cap
│   ├── execution_lock.py                           per-job lock around user code
│   ├── idempotency.py                              dispatch-time idempotency lock
│   ├── scheduler_lock.py                           scheduler leader lock
│   ├── cancellation.py                             cooperative cancel API
│   ├── decorator.py                                @conductor.job decorator + metadata
│   ├── client.py                                   Redis client factory
│   ├── frappe_compat.py                            opt-in shim for `frappe.enqueue`
│   ├── migrate_rq.py                               implementation behind `bench conductor migrate-from-rq`
│   ├── site_discovery.py                          enumerate conductor-installed sites for pool mode
│   ├── sweeper.py                                  stream MAXLEN / XTRIM
│   ├── kpi_workload.py                             test fixtures shared with comparative harness
│   ├── demo.py                                     functions used by `doctor --demo` and chaos tests
│   ├── context.py                                  per-job context (job_id, attempt, deadline, cancel)
│   ├── cron.py                                     cron expression evaluation
│   ├── scheduled.py                                scheduled-set helpers
│   ├── serialization.py                            msgpack / base64 wrappers
│   ├── logging.py                                  structlog setup
│   ├── doctor.py                                   doctor command implementation
│   ├── install.py                                  fixtures + post-install hooks
│   └── hooks.py                                    Frappe app manifest
├── dashboard/                                      Vue 3 + Vite SPA served at /conductor-dashboard
│   ├── src/
│   │   ├── App.vue, main.js, router.js, app.css   shell + routing + Tailwind v4 entry
│   │   ├── api.js                                  REST client (calls conductor/api/*)
│   │   ├── realtime.js                             Frappe socketio subscription
│   │   ├── pages/                                  one component per route
│   │   ├── components/                             shared UI (badges, tables, dialogs)
│   │   └── stores/                                 Pinia stores
│   ├── index.html, vite.config.js, package.json
├── docs/                                           Diátaxis user docs
│   ├── tutorial-getting-started.md
│   ├── how-to-*.md                                 enqueue, schedule, triage, multi-tenant, RQ migration, workflows
│   ├── reference-cli.md                            every `bench conductor` subcommand
│   ├── reference-configuration.md                  every site_config / env knob
│   ├── reference-python-api.md                     enqueue / job / RetryPolicy / workflow API
│   ├── explanation-architecture.md                 dispatcher / worker / scheduler topology
│   ├── explanation-reliability.md                  state machine + invariants
│   ├── explanation-why-conductor.md                Conductor vs RQ KPI summary
│   ├── index.md                                    docs landing page
│   └── roadmap/v1.md                               what shipped per milestone
├── tests/                                          unit + integration tests (run under bench env pytest)
│   ├── benchmarks/                                 non-gating perf measurements
│   └── comparative/                                Conductor-vs-RQ KPI harness
├── tests_chaos/                                    subprocess-spawning chaos suite (kill -9, reclaim, etc.)
├── pyproject.toml                                  Python package metadata + ruff config
├── package.json                                    `yarn build` proxy that builds the dashboard
├── pytest.ini, .pre-commit-config.yaml, .eslintrc, .editorconfig
├── Procfile.conductor                              sample bench Procfile entries
└── README.md, license.txt, claude.md
```

### Where to look first

- **Adding a new CLI subcommand** → `conductor/commands/<name>.py` + register in `hooks.py`.
- **Adding a DocType field** → `conductor/conductor/doctype/<doctype>/<doctype>.json` + matching controller; write a patch under `conductor/patches/` if existing rows need backfill.
- **Changing job lifecycle behavior** → `conductor/worker.py` (execution) or `conductor/dispatcher.py` (dispatch).
- **Changing scheduling** → `conductor/scheduler_loops.py`.
- **Workflow changes** → `conductor/workflow/`.
- **Dashboard changes** → frontend in `dashboard/src/`, server endpoints in `conductor/api/dashboard.py`.
- **Tests** → unit/integration in `tests/`, chaos (real subprocesses, real Redis) in `tests_chaos/`.

### Run locally

- Tests: `/Users/osamamuhammed/frappe_15/env/bin/pytest tests` (the bench virtualenv, not bare `pytest`).
- Dashboard build: `yarn build` from repo root (delegates to `dashboard/`).
- Worker: `bench --site <site> conductor worker --queue default`.
- Scheduler: `bench --site <site> conductor scheduler`.
- Health check: `bench --site <site> conductor doctor [--demo]`.
