# Reliability

Conductor's reliability story has four pieces: at-least-once delivery, idempotency keys, retries with a DLQ, and workflow compensations. This page explains each, including what each does **not** protect against. The companion architecture page is [`explanation-architecture.md`](explanation-architecture.md).

The short version: Conductor will not lose a dispatch, will not silently drop a failure, and will not double-execute a logically-keyed dispatch. It cannot make your job's *side effects* idempotent for you — that is your code's job.

---

## At-least-once delivery

Every dispatch survives at least one process crash. Worker death between executing a job and `XACK`-ing the stream means the message stays in the consumer group's pending entries list and is re-delivered to a healthy worker.

The places where a duplicate execution can occur:

- **Worker SIGKILL after work, before `XACK`.** A peer reads the still-pending message and runs it again.
- **Scheduler crash between `enqueue(...)` and the schedule's `next_run_at` write.** The next lock holder re-fires the schedule.
- **Network partition between worker and Redis after work completed.** Same shape as the SIGKILL case — the operation succeeded but Conductor cannot prove it.

What Conductor does not give you:

- **Exactly-once execution.** Nothing reasonable can. The standard fix is to make your job idempotent at the side-effect boundary (idempotent DB writes, idempotent external API calls).
- **Ordered delivery.** Workers in a consumer group race for messages; nothing pins a message to a slot.

---

## Idempotency keys

The `idempotency_key=` parameter to `conductor.enqueue` (and `run_workflow`) deduplicates **dispatches** — not executions. Two `enqueue` calls with the same key, while the first job is still tracked, return the same `job_id` and only one job runs.

The key is:

- Stored under `conductor:{site}:idem:<sha256(key)>` (workflows: `…:wfidem:<sha256(key)>`).
- Set with `SET NX EX <ttl>`. TTL defaults to 24 h (`conductor.idempotency_ttl_seconds`).
- **Not** released on terminal status. The TTL is the only release mechanism. A duplicate dispatch within the TTL is the entire point.

What this protects:

- Concurrent producers racing on the same business key (KPI 4).
- Replay loops (a webhook delivered twice, a retry of a request that already enqueued).

What this does not protect:

- A job whose body calls a non-idempotent external API. The dispatch was deduped; the side effect could still fire twice if at-least-once semantics double-execute. Make the body idempotent at the side-effect boundary.
- Re-dispatch *after* the TTL elapses. The same key may then be reused legitimately.
- Different keys for the same logical action. Two callers with different `idempotency_key` values get two jobs.

---

## Retries and `SCHEDULED_RETRY`

When a job raises, Conductor consults the `RetryPolicy` stamped into the job message at dispatch time. If the policy says retry (the exception matches `retry_on`, does not match `no_retry_on`, and `attempt < max_attempts`), the job moves to `SCHEDULED_RETRY` rather than `FAILED`.

The retry message is `ZADD`-ed to `conductor:{site}:scheduled` with `score = run_at_unix_ms`. The scheduler's drain loop pops due members and `XADD`s them back to the stream. A retried message looks like a fresh dispatch to the worker — same `job_id`, incremented `attempt`.

The default backoff is exponential with full jitter:

| Field | Default |
|---|---|
| `max_attempts` | 3 |
| `backoff` | `exponential` (also: `linear`, `fixed`) |
| `base_delay_seconds` | 2 |
| `max_delay_seconds` | 600 |
| `jitter` | `full` (also: `none`, `equal`) |

`compute_next_delay(attempt)` for `exponential` is `random.uniform(0, min(base * 2^(attempt-1), max))`. Per-attempt rows live in `tabConductor Job Run` so the audit shows every retry separately, not just the last one (KPI 2).

`SCHEDULED_RETRY` is also where throttled jobs land — over `max_rps` or `max_concurrent`. They ride the same drain loop and rejoin the queue when capacity returns. `last_error_message` is `"rate_limited"` or `"inflight_capped"`. **They are not failures.**

The dispatch-time policy stamp is intentional — a job that started under one policy keeps that policy across redeploys. A code change that tightens `max_attempts` does not retroactively kill jobs already in flight.

---

## The DLQ

A job lands in the DLQ when it has terminally failed: either the retry budget is exhausted (`FAILED` after `max_attempts`), the deadline elapsed and retries are also exhausted (`TIMED_OUT`), or the policy refused to retry the exception (`no_retry_on` matched, or the exception was outside `retry_on`).

The sweeper loop runs in the scheduler. For each terminally-failed job, it:

1. Inserts a `Conductor DLQ Entry` row with the failure metadata and the original message payload.
2. Sets the `Conductor Job` status to `DLQ`.
3. `XACK`s the stream entry.

DLQ entries are first-class SQL rows (KPI 3). Operators retry, edit-and-retry, or discard them via the dashboard or `bench conductor dlq` — see [`how-to-triage-failures.md`](how-to-triage-failures.md).

What the DLQ is not:

- An automatic recovery mechanism. Nothing in Conductor watches the DLQ and replays its contents. Operators decide whether each entry is a bug, transient infrastructure trouble, or noise.
- A replacement for monitoring. A growing DLQ is a signal — alert on it from your existing observability stack.

---

## The orphan sweeper (dispatch crash window)

`enqueue` writes the `Conductor Job` row, commits, then `XADD`s the message. A crash between the commit and the `XADD` would leave a row stuck at `QUEUED` with no Redis message. The orphan sweeper (`conductor.sweeper.sweep_orphans`) runs as a scheduler loop, finds rows in this state older than 30 s, and re-`XADD`s them. If the re-`XADD` also fails, the row moves to `DISPATCH_FAILED`.

Sweeper-recovered messages fall back to **queue defaults** for retry policy fields, because the v1 `Conductor Job` row does not store the full per-job `RetryPolicy`. For most workloads this is acceptable degradation; if you depend on a custom per-job policy, monitor `DISPATCH_FAILED` rates so the sweeper rarely needs to act.

---

## Workflow compensations

When a step in a workflow run terminally fails, the run enters `COMPENSATING`. The advancer dispatches compensation methods for **already-completed** steps in **reverse-topological order** (a downstream step's compensation runs before an upstream step's). Steps that have not yet started are marked `SKIPPED`; in-flight steps are cancelled via the regular `cancel(job_id)` path.

Each compensation runs as a normal Conductor Job — it inherits retry, timeout, idempotency, and DLQ semantics. Steps without a `compensation=` declaration get a no-op `COMPENSATED` row and the advancer moves on.

The partial-rollback rule:

> If a compensation step itself terminally fails, earlier completed steps are **not** compensated. The run lands `FAILED` with a `last_error` describing the compensation failure. Operators triage from the dashboard.

This is intentional. Cascading rollbacks across a partially-rolled-back run can leave inconsistent partial state in distributed services. Conductor stops at the first failed compensation and asks an operator to decide.

What workflows do not give you:

- **Distributed transactions.** Compensations are best-effort, and the rule above means partial rollback is possible.
- **Sub-workflow nesting.** A workflow step is a single Conductor Job. To "call" another workflow from a step, enqueue it explicitly with `run_workflow(...)` and treat that step's success as the dispatch returning a `run_id`.

---

## Failure modes Conductor does not handle

Surfacing these so you do not assume Conductor handles them:

- **Side-effect non-idempotency.** Discussed above. Make the job body idempotent at the side-effect boundary.
- **External API outages longer than your retry budget.** Conductor will eventually move the job to the DLQ; use a separate circuit-breaker or pause queue at that layer if you need different behavior.
- **Mass duplicate enqueues from a buggy producer.** The idempotency-key system requires the producer to use a stable key. A producer that generates a fresh UUID for every dispatch will get N jobs.
- **Cluster-wide rate limits.** `max_rps` and `max_concurrent` are per pool process. Cluster-wide caps require a token broker outside Conductor.
- **Job bodies that swallow `should_cancel()`.** Cooperative cancellation only works if the body checks. A tight C-extension loop will not be cancelled until it returns.

---

## See also

- [`reference-configuration.md`](reference-configuration.md) — `RetryPolicy` defaults, the job state machine, role permissions for retry vs discard.
- [`reference-python-api.md`](reference-python-api.md) — the `idempotency_key`, `cancel`, and `cancel_workflow_run` surfaces.
- [`how-to-triage-failures.md`](how-to-triage-failures.md) — the DLQ in practice.
