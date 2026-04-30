"""KPI 1 — Transient-Failure Recovery Rate.

Question: when a job fails for a reason that is not a DB deadlock, what
fraction of jobs eventually succeed under the platform's default retry
behavior — with no application-layer retry code?

Workload: 50 jobs of `transient_failure(idempotency_key=...)`. The
function fails on attempts 1 and 2 (raising `ConnectionError`) and
succeeds on attempt 3, using a Redis-backed attempt counter keyed by
`idempotency_key` so the same logical job "learns" across retries.

Conductor: enqueued with `max_attempts=3, retry_on=(ConnectionError,)`.
RQ: enqueued at default. RQ has no retry for non-DB exceptions; the
whole job goes to the `failed` registry on attempt 1.

Reports:
  recovery_rate            — succeeded / total
  mean_attempts_per_success — Redis counter mean across succeeded jobs
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from statistics import mean

from .harness import (
    Engine,
    PENDING,
    TERMINAL_SUCCEEDED,
)
from . import workload


TOTAL_JOBS = 50
DRAIN_TIMEOUT_SECONDS = 480.0


@dataclass
class KPI1Result:
    engine: str
    total: int
    succeeded: int
    failed_or_dlq: int
    recovery_rate: float
    mean_attempts_per_success: float
    notes: str = ""


def run(engine: Engine) -> KPI1Result:
    print(f"\n=== KPI 1 (transient-recovery) — engine={engine.name} ===")
    engine.setup()

    # Conductor's Phase 2+ retry path requires the scheduler process —
    # it owns the delay-drain loop that pulls SCHEDULED_RETRY jobs back
    # to the queue. RQ's retry (when configured) is in-worker and needs
    # no separate process.
    if hasattr(engine, "spawn_scheduler"):
        engine.spawn_scheduler()
    engine.spawn_worker()

    # Pre-clear attempt counters for the keys we are about to use.
    from conductor.kpi_workload import _redis
    r = _redis()
    for k in r.scan_iter(match="kpi:attempts:kpi01-*"):
        r.delete(k)

    # Enqueue 50 jobs, each with a unique idempotency key (so the per-job
    # attempt counter is isolated).
    job_ids: list[tuple[str, str]] = []  # (job_id, idem_key)
    # NOTE: deliberately no `max_attempts=...` argument. The point of this
    # KPI is "what does each platform do out-of-the-box?" Conductor uses the
    # queue's default_max_attempts=3 (master §6.1); RQ uses its own default
    # of 1 attempt (no retry config means no Retry wrapper). Asymmetric
    # parameters reflect asymmetric platform defaults.
    for i in range(TOTAL_JOBS):
        attempt_key = f"kpi01-{uuid.uuid4().hex[:12]}"
        jid = engine.enqueue(
            "conductor.kpi_workload.transient_failure",
            timeout=120,
            attempt_key=attempt_key,
            fail_attempts=2,
        )
        job_ids.append((jid, attempt_key))
    print(f"enqueued {TOTAL_JOBS} transient-failure jobs")

    # Drain.
    deadline = time.time() + DRAIN_TIMEOUT_SECONDS
    terminal: dict[str, str] = {}  # job_id -> final status
    while time.time() < deadline and len(terminal) < TOTAL_JOBS:
        for jid, _idem in job_ids:
            if jid in terminal:
                continue
            status = engine.get_status_nonblocking(jid)
            if status != PENDING:
                terminal[jid] = status
        time.sleep(1.0)

    succeeded = sum(1 for s in terminal.values() if s == TERMINAL_SUCCEEDED)
    failed_or_dlq = sum(1 for s in terminal.values() if s != TERMINAL_SUCCEEDED)
    recovery_rate = succeeded / TOTAL_JOBS

    # Per-success attempt count: read each job's attempt counter. The
    # function increments before raising/returning, so a job that succeeded
    # on attempt 3 has counter==3.
    successful_attempts: list[int] = []
    for jid, attempt_key in job_ids:
        if terminal.get(jid) != TERMINAL_SUCCEEDED:
            continue
        raw = r.get(f"kpi:attempts:{attempt_key}")
        if raw:
            successful_attempts.append(int(raw))
    mean_attempts = mean(successful_attempts) if successful_attempts else 0.0

    notes = ""
    if len(terminal) < TOTAL_JOBS:
        notes = f"drain timed out at {DRAIN_TIMEOUT_SECONDS:.0f}s; {TOTAL_JOBS - len(terminal)} jobs still pending"

    print(f"=== drained: succeeded={succeeded}/{TOTAL_JOBS} (failed/DLQ={failed_or_dlq}) ===")
    print(f"=== recovery_rate={recovery_rate:.0%} mean_attempts_per_success={mean_attempts:.2f} ===")

    engine.teardown()
    return KPI1Result(
        engine=engine.name,
        total=TOTAL_JOBS,
        succeeded=succeeded,
        failed_or_dlq=failed_or_dlq,
        recovery_rate=recovery_rate,
        mean_attempts_per_success=mean_attempts,
        notes=notes,
    )
