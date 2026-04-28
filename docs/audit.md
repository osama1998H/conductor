# Conductor — CLAUDE.md compliance audit + suggested approach

## Context

The user asked for a research pass over the Conductor app (a Frappe-based job queue,
~3,900 lines of production Python across ~30 modules) to find areas that diverge from
the rules in [CLAUDE.md](CLAUDE.md), and to recommend an approach.

CLAUDE.md is the project's clean-code ruleset: small functions, single-purpose
classes, intention-revealing names, no commented-out code, no swallowed errors,
no magic values without rationale, clean tests, low cognitive load.

Three Explore agents audited disjoint slices of the tree (worker/dispatcher,
scheduler/commands, hooks/doctypes/tests). Findings were spot-checked against
the actual code; weak/contested findings (e.g., "imports inside test methods" —
that's the standard Frappe pattern that defers imports until after `frappe.init`
runs) were dropped. What follows is the verified, material set.

The intended outcome: the user can decide whether to leave this as documentation,
take one high-leverage slice, or do a full clean-up pass.

---

## Findings, by theme

### Theme 1 — Frappe-session lifecycle is duplicated everywhere (highest leverage)

The same six-line incantation —

```python
frappe.init(site=site, sites_path=sites_path)
frappe.connect()
try:
    ...
finally:
    frappe.destroy()
```

— appears in at least seven places:

- [worker.py:283-297](conductor/worker.py#L283-L297) — `CancelPoller._run`
- [worker.py:319-402](conductor/worker.py#L319-L402) — `_handle_one`
- [scheduler_loops.py:90-99](conductor/scheduler_loops.py#L90-L99) — `_cron_loop`
- [scheduler_loops.py](conductor/scheduler_loops.py) — `_reaper_loop` and `_sweeper_loop`
- [commands/schedule.py:19-44](conductor/commands/schedule.py#L19-L44),
  [53-65](conductor/commands/schedule.py#L53-L65),
  [73-86](conductor/commands/schedule.py#L73-L86),
  [98-124](conductor/commands/schedule.py#L98-L124) — four CLI subcommands

`frappe_compat.py` does **not** already provide a session helper (verified — it
is only a `frappe.enqueue` shim).

CLAUDE.md rules violated: *"Remove duplication aggressively"*, *"If a change
touches too many files, revisit the boundaries"*, *"Make thread-safety
assumptions explicit"* (the lifecycle is what makes each loop thread-safe and
that contract should be visible in one place).

### Theme 2 — `worker._handle_one` is a 93-line god function

[worker.py:310-402](conductor/worker.py#L310-L402) does, in one body:
status pre-check, exec-lock acquire, watchdog start, function dispatch,
exception capture, four-branch outcome (CANCELLED / SUCCEEDED / TIMED_OUT /
FAILED), retry-or-DLQ decision, job-run row write, watchdog cancel, lock
release, stream ack, and frappe teardown. Nesting reaches four levels deep
(`def → try → try → if/elif/else`).

Plus a redundant statement: lines [394-395](conductor/worker.py#L394-L395) pop
`_cancel_events[msg.job_id]` under the lock, and the `finally` at
[399-400](conductor/worker.py#L399-L400) does it again. The inner pop is dead
on every code path.

CLAUDE.md rules violated: *"Keep functions small"*, *"Each function should do
one thing"*, *"A function should have a single level of abstraction"*, *"Read
code top to bottom like a story"*.

### Theme 3 — Silent exception swallowing in dispatch

[dispatcher.py:56-60](conductor/dispatcher.py#L56-L60):

```python
try:
    func = frappe.get_attr(method)
    meta = get_metadata(func)
except Exception:
    pass
```

If method resolution or metadata lookup fails, the dispatcher silently falls
back to queue defaults — a real bug (typo'd method name, broken decorator)
will produce no signal. CLAUDE.md: *"Do not swallow errors silently"*, *"Throw
meaningful errors with enough context to diagnose the failure"*.

The `except Exception: pass` shape also appears in
[cancellation.py:56-63](conductor/cancellation.py#L56-L63) when iterating
the scheduled set.

### Theme 4 — `RetryPolicy` is rebuilt verbatim to override one field

[dispatcher.py:81-90](conductor/dispatcher.py#L81-L90):

```python
if per_call_max_attempts is not None:
    policy = RetryPolicy(
        max_attempts=per_call_max_attempts,
        backoff=policy.backoff,
        base_delay_seconds=policy.base_delay_seconds,
        max_delay_seconds=policy.max_delay_seconds,
        jitter=policy.jitter,
        retry_on=policy.retry_on,
        no_retry_on=policy.no_retry_on,
    )
```

Seven lines that say "copy everything except `max_attempts`". CLAUDE.md:
*"Remove duplication aggressively"*. If `RetryPolicy` is a `dataclass`,
`dataclasses.replace(policy, max_attempts=per_call_max_attempts)` is one line.

### Theme 5 — Magic values without rationale

Each of these is a tuning knob in a concurrency-sensitive path with no comment
explaining *why* the number is safe:

- [worker.py:329](conductor/worker.py#L329) — `msg.timeout_seconds + 30` — the
  exec-lock TTL buffer. Why 30s? If a job runs to its full timeout, will the
  lock outlive the watchdog or not?
- [scheduler_loops.py:140-142](conductor/scheduler_loops.py#L140-L142) —
  `REAPER_STALE_AGE_SECONDS = 30`, `REAPER_GONE_AGE_SECONDS = 120`,
  `REAPER_PRUNE_AGE_SECONDS = 7 * 24 * 3600`. Both 30/120 must relate to
  the heartbeat interval; that relationship is invisible.
- [install.py:12-16](conductor/install.py#L12-L16) — queue defaults
  (`concurrency=4`, `default_max_attempts=3`, `default_timeout=300/60/3600`)
  inlined as literals.

CLAUDE.md: *"Hard-coded magic values"* under "Smells to eliminate".

### Theme 6 — Boilerplate clutter in `hooks.py`

[hooks.py](conductor/hooks.py) is 251 lines, of which **active code is 9 lines**
(1-6 plus 86 `after_install`, 88 `commands`). The remaining ~242 lines are the
default Frappe hook scaffold left commented-out. CLAUDE.md: *"Avoid
commented-out code"*. (Counterpoint: this *is* the conventional Frappe
template; some teams keep it as a menu of opt-ins. Stylistic call.)

### Theme 7 — Test hygiene in `test_worker_e2e.py`

[test_worker_e2e.py](conductor/conductor/doctype/conductor_job/test_worker_e2e.py)
is the largest test file (221 lines) and has three structural problems:

1. **Production-module monkey-patch from `setUp`**:
   [lines 82-92](conductor/conductor/doctype/conductor_job/test_worker_e2e.py#L82-L92)
   set `conductor.demo._fail_count = 0` and `conductor.demo.flaky = flaky`.
   Tests are mutating the production module to install a fake. Risk: state
   leaks across tests if `tearDown` doesn't run; the real `conductor.demo`
   module surface is now ambiguous.
2. **Copy-pasted `setUp` across four test classes** — the Redis flush sequence
   `load_config → get_redis → stream_key → r.delete` is repeated verbatim.
3. **Sleep-based polling** for status convergence with a fixed-iteration retry
   loop ([lines 122-131](conductor/conductor/doctype/conductor_job/test_worker_e2e.py#L122-L131)) —
   non-deterministic and slow.

CLAUDE.md: *"Test setup should be minimal and expressive"*, *"Keep tests
deterministic"*, *"Refactor dirty tests immediately"*.

---

## Suggested approach

CLAUDE.md itself says *"if a change touches too many files, revisit the
boundaries"* — so do **not** do all of this in one PR. The themes are roughly
independent and decreasing in payoff.

**Recommended order (each shippable on its own):**

| # | Slice | Touches | Risk | Payoff |
|---|---|---|---|---|
| A | Add `frappe_session(site, sites_path)` context manager (new module, e.g. `conductor/session.py`) and replace 7 duplicated lifecycle blocks | worker.py, scheduler_loops.py, commands/schedule.py | Low — pure extract | High |
| B | `dataclasses.replace` for `RetryPolicy` override + raise/log instead of swallow on metadata-resolution failure | dispatcher.py | Low | Medium |
| C | Split `_handle_one` into `_decide_outcome()` (computes status + retry/DLQ decision, pure) and `_finalize()` (writes job-run row, releases lock, acks); remove redundant `_cancel_events.pop` | worker.py | Medium — concurrency-sensitive, needs the existing tests green | High |
| D | Document magic constants in place: a one-line `# Why 30s buffer:` comment on each, or move them to `conductor/config/__init__.py` with rationale | worker.py, scheduler_loops.py, install.py | Low | Low/Medium (mostly review-debt) |
| E | Test cleanup: extract a `RedisFixtureMixin` or a `pytest` fixture for the Redis flush; replace `conductor.demo` monkey-patch with `unittest.mock.patch.object`; replace fixed-iteration sleep loops with a deterministic drain helper | tests | Medium — easy to break a flaky test further | Medium |
| F | (Optional) Strip commented Frappe boilerplate from `hooks.py` | hooks.py | Trivial | Low (stylistic) |

**Reusable code already in the repo to lean on:**

- [`conductor/scheduler_lock.py`](conductor/scheduler_lock.py) — already encapsulates the renew/release pattern; the lifecycle helper should mirror its shape (small, single-purpose, context-manager-friendly).
- [`conductor/streams.py`](conductor/streams.py) — `stream_key`, `ensure_consumer_group` are the right level of helper to model the new session helper after.
- The existing `_decode_kwargs` private in `scheduler_loops.py` is imported by `commands/schedule.py:106-107` — when slice A lands, consider whether `_decode_kwargs` should move to a shared utility module so commands don't import a private from a loops module.

**What I would NOT do:**

- Don't introduce a "JobLifecycle" class to "encapsulate" `_handle_one`. CLAUDE.md
  warns against premature generalization. A pair of small free functions is
  enough.
- Don't touch `cron.py`, `serialization.py`, `idempotency.py`,
  `execution_lock.py` — these are already small and single-purpose; nothing
  material was found there.
- Don't rewrite the four-thread scheduler architecture
  ([scheduler.py](conductor/scheduler.py) + [scheduler_loops.py](conductor/scheduler_loops.py)).
  The split is the deliberate seam between "process supervisor" and "loop
  bodies"; the duplication concern dissolves once slice A lands.

---

## Verification (when a slice is implemented)

- `pytest /Users/osamamuhammed/frappe_15/apps/conductor/tests` and
  `pytest /Users/osamamuhammed/frappe_15/apps/conductor/conductor/conductor/doctype` — full unit + DocType test suite must stay green.
- `pytest /Users/osamamuhammed/frappe_15/apps/conductor/tests_chaos` — chaos
  tests (scheduler kill-9 handoff, etc.) are the load-bearing concurrency
  proof; especially important after slice A or C.
- `bench --site <site> conductor doctor` — the existing doctor command exercises the dispatch round-trip end-to-end.
- For slice C specifically: re-run the worker e2e tests that exercise the
  retry-then-succeed and DLQ-exhaustion paths.

---

---

## Decision (2026-04-28)

The user chose **audit only — no code changes**. This document is the
deliverable; slices A–F are deferred. No implementation will be performed in
this session.

---

## Critical files (where the work actually lands, when picked up later)

- [conductor/worker.py](conductor/worker.py) — slices A, C, D
- [conductor/dispatcher.py](conductor/dispatcher.py) — slice B
- [conductor/scheduler_loops.py](conductor/scheduler_loops.py) — slices A, D
- [conductor/commands/schedule.py](conductor/commands/schedule.py) — slice A
- [conductor/install.py](conductor/install.py) — slice D
- [conductor/conductor/doctype/conductor_job/test_worker_e2e.py](conductor/conductor/doctype/conductor_job/test_worker_e2e.py) — slice E
- New file `conductor/session.py` (or co-located in `frappe_compat.py`) — slice A
- [conductor/hooks.py](conductor/hooks.py) — slice F
