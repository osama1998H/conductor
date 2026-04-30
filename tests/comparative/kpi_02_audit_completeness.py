"""KPI 2 — Per-Attempt Audit Completeness.

Question: when a job fails repeatedly, can an operator inspect each
individual attempt — its traceback, its timestamps, the worker that ran
it — without leaving the database?

Workload: 50 jobs of `always_fail`. Each runs to terminal failure. We
then count per-attempt records on each side.

Conductor: each attempt produces a `Conductor Job Run` row (Phase 1 spec
P1-15). With queue default_max_attempts=3, expect 150 rows.

RQ: the `failed` registry stores one record per *job* (the last
exception only). Intermediate retry attempts (RQ retries only on DB
deadlock) leave no per-attempt artifact.

Reports:
  attempt_records_total       — sum of records over all 50 jobs
  expected_total              — 50 * default_max_attempts
  audit_coverage              — attempt_records_total / expected_total
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from .harness import (
    Engine,
    PENDING,
)
from . import workload


TOTAL_JOBS = 50
DRAIN_TIMEOUT_SECONDS = 360.0


@dataclass
class KPI2Result:
    engine: str
    total_jobs: int
    attempt_records_total: int
    expected_total: int
    audit_coverage: float
    notes: str = ""


def run(engine: Engine) -> KPI2Result:
    print(f"\n=== KPI 2 (audit-completeness) — engine={engine.name} ===")
    engine.setup()
    if hasattr(engine, "spawn_scheduler"):
        engine.spawn_scheduler()
    engine.spawn_worker()

    # Counter just to confirm the workload actually executed.
    workload.reset_counter("kpi02")

    job_ids: list[str] = []
    # Both engines configured for max_attempts=3 so the question becomes
    # "given retries WERE performed, what attempt-level audit did the
    # platform preserve?" — not "did retries happen?" (that's KPI 1).
    for _ in range(TOTAL_JOBS):
        jid = engine.enqueue(
            "conductor.kpi_workload.always_fail",
            timeout=120,
            max_attempts=3,
            counter_name="kpi02",
        )
        job_ids.append(jid)
    print(f"enqueued {TOTAL_JOBS} always-fail jobs (max_attempts=3 on both)")

    # Drain.
    deadline = time.time() + DRAIN_TIMEOUT_SECONDS
    terminal: set[str] = set()
    while time.time() < deadline and len(terminal) < TOTAL_JOBS:
        for jid in job_ids:
            if jid in terminal:
                continue
            status = engine.get_status_nonblocking(jid)
            if status != PENDING:
                terminal.add(jid)
        time.sleep(1.0)

    # Use the workload counter as the source of truth for "how many attempts
    # actually ran." The two engines have different semantics for max_attempts
    # (Conductor: total attempts; RQ Retry(max=N): initial + N retries), so a
    # hardcoded `expected = jobs × 3` is misleading. The honest comparison is
    # `records / actual_executions` — what fraction of attempts left a
    # queryable per-attempt artifact?
    actual_executions = workload.get_counter("kpi02")
    expected_total = actual_executions  # the executions that DID happen

    attempt_records_total = sum(
        engine.count_attempt_records(jid) for jid in job_ids
    )
    audit_coverage = attempt_records_total / expected_total if expected_total else 0.0

    notes = ""
    if len(terminal) < TOTAL_JOBS:
        notes = f"drain timed out at {DRAIN_TIMEOUT_SECONDS:.0f}s; {TOTAL_JOBS - len(terminal)} jobs still pending"

    print(f"=== records={attempt_records_total}/{expected_total} coverage={audit_coverage:.0%} ===")

    engine.teardown()
    return KPI2Result(
        engine=engine.name,
        total_jobs=TOTAL_JOBS,
        attempt_records_total=attempt_records_total,
        expected_total=expected_total,
        audit_coverage=audit_coverage,
        notes=notes,
    )
