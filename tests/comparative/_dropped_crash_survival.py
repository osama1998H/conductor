"""KPI 1 — Time-to-Recovery After Worker SIGKILL.

The "survival rate" framing was reset after empirical evidence: with a peer
worker alive, both engines hit ~100% survival (RQ's `clean_registries`
recovers from dead-worker started-registry entries; Conductor's `XAUTOCLAIM`
does the same for stream PEL). The discriminator is **how long** in-flight
jobs take to be recovered after their worker dies.

Workload: 20 jobs of `sleep(5s); incr_counter`. Two workers (concurrency=1
each, so each holds at most 1 in-flight at the kill moment). At t=2s after
enqueue, SIGKILL worker A (which has 1 job in flight). Wait up to 360s for
the rest of the work to drain.

Reports:
  survival_rate         — succeeded / total       (expect ~100% for both)
  p95_recovery_seconds  — p95 of (kill→terminal) for jobs that became
                          terminal AFTER the kill — this is the KPI metric
  duplicate_rate        — (counter - succeeded) / total — informational
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from statistics import median

from .harness import (
    Engine,
    PENDING,
    TERMINAL_SUCCEEDED,
)
from . import workload


TOTAL_JOBS = 20
SLEEP_SECONDS = 5.0
KILL_AT_SECONDS = 2.0
DRAIN_TIMEOUT_SECONDS = 360.0
COUNTER_NAME = "kpi01"


@dataclass
class KPI1Result:
    engine: str
    total: int
    succeeded: int
    counter_value: int
    survival_rate: float
    duplicate_rate: float
    p50_recovery_seconds: float
    p95_recovery_seconds: float
    notes: str = ""


def _percentile(samples: list[float], p: float) -> float:
    if not samples:
        return 0.0
    s = sorted(samples)
    k = int(len(s) * p)
    return s[min(k, len(s) - 1)]


def run(engine: Engine) -> KPI1Result:
    print(f"\n=== KPI 1 (crash-survival) — engine={engine.name} ===")
    engine.setup()
    workload.reset_counter(COUNTER_NAME)

    # Spawn worker A and worker B before enqueue, so both are ready to
    # consume. Worker A will pick up the first batch; worker B will mostly
    # idle until A is killed and reclaim kicks in.
    worker_a = engine.spawn_worker()
    worker_b = engine.spawn_worker()
    print(f"workers spawned: A={worker_a} B={worker_b}")

    enqueue_start = time.time()
    job_ids: list[str] = []
    for i in range(TOTAL_JOBS):
        jid = engine.enqueue(
            "conductor.kpi_workload.slow_then_count",
            counter_name=COUNTER_NAME,
            sleep_seconds=SLEEP_SECONDS,
        )
        job_ids.append(jid)
    print(f"enqueued {TOTAL_JOBS} jobs in {time.time() - enqueue_start:.1f}s")

    # Sleep to let worker A claim a chunk of jobs and start sleeping.
    time.sleep(KILL_AT_SECONDS)

    kill_at = time.time()
    engine.kill_worker(worker_a)
    print(f"killed worker A (pid={worker_a}) at t={KILL_AT_SECONDS:.1f}s")

    # Drain — single non-blocking pass over all jobs, every 0.5s.
    terminal_at: dict[str, float] = {}
    deadline = kill_at + DRAIN_TIMEOUT_SECONDS
    while time.time() < deadline and len(terminal_at) < TOTAL_JOBS:
        for jid in job_ids:
            if jid in terminal_at:
                continue
            status = engine.get_status_nonblocking(jid)
            if status == PENDING:
                continue
            if status == TERMINAL_SUCCEEDED:
                terminal_at[jid] = time.time()
            # FAILED or DLQ — we still record terminal_at because the job
            # reached a terminal state, even if not the desired one. KPI 1
            # measures time-to-terminal, regardless of outcome.
            else:
                terminal_at[jid] = time.time()
        time.sleep(0.5)
    final_drain_time = time.time()

    counter_value = workload.get_counter(COUNTER_NAME)
    # `succeeded` is the count we explicitly observed in SUCCEEDED state.
    # `terminal` is the count that reached any terminal state (used for
    # recovery-time stats since FAILED/DLQ also count as recovered).
    terminal_count = len(terminal_at)
    succeeded = sum(
        1 for jid in terminal_at
        if engine.get_status_nonblocking(jid) == TERMINAL_SUCCEEDED
    )
    survival_rate = succeeded / TOTAL_JOBS
    duplicate_rate = max(0.0, (counter_value - succeeded) / TOTAL_JOBS)

    # Recovery latency: for jobs that became terminal AFTER the kill.
    # This is the discriminator KPI — XAUTOCLAIM (8s test threshold,
    # 60s production) vs RQ clean_registries gating on heartbeat TTL.
    post_kill_completions = [t - kill_at for t in terminal_at.values() if t > kill_at]
    p50_recovery = median(post_kill_completions) if post_kill_completions else 0.0
    p95_recovery = _percentile(post_kill_completions, 0.95)

    notes = ""
    if terminal_count < TOTAL_JOBS and (final_drain_time - kill_at) >= DRAIN_TIMEOUT_SECONDS - 1:
        notes = f"drain timed out at {DRAIN_TIMEOUT_SECONDS:.0f}s; {TOTAL_JOBS - terminal_count} jobs not yet terminal"

    print(f"=== terminal: {terminal_count}/{TOTAL_JOBS} (succeeded={succeeded}) counter={counter_value} ===")
    print(f"=== survival={survival_rate:.0%} duplicates={duplicate_rate:.0%} p95_recovery={p95_recovery:.1f}s ===")

    engine.teardown()
    return KPI1Result(
        engine=engine.name,
        total=TOTAL_JOBS,
        succeeded=succeeded,
        counter_value=counter_value,
        survival_rate=survival_rate,
        duplicate_rate=duplicate_rate,
        p50_recovery_seconds=p50_recovery,
        p95_recovery_seconds=p95_recovery,
        notes=notes,
    )
