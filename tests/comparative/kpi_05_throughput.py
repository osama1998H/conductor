"""KPI 5 — Throughput Across Job Durations (the honest cost).

Question: what does Conductor's reliability cost you in raw throughput,
and how does that cost shrink as jobs do more real work?

Workload: 500 jobs at each of three durations on a single worker
(concurrency=4 for Conductor, 1 for RQ — RQ's natural fork model).
We measure wall time from "all 500 enqueued" until "all 500 terminal."

Buckets:
  1ms   — `conductor.kpi_workload.echo`              (pure return)
  50ms  — `slow_then_count(sleep_seconds=0.05)`      (typical Frappe op)
  500ms — `slow_then_count(sleep_seconds=0.5)`       (heavier work)

Reports per bucket:
  jobs_per_sec
  wall_seconds

This is the "honest disadvantage" KPI — Conductor is expected to lag on
the 1ms bucket (per-job DocType + Redis Stream overhead dominates) and
converge as real work grows.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .harness import (
    Engine,
    PENDING,
    TERMINAL_SUCCEEDED,
)
from . import workload


JOBS_PER_BATCH = 500
COUNTER_NAME = "kpi05"
DRAIN_TIMEOUT_SECONDS = 600.0
BUCKETS = [
    ("1ms",   "conductor.kpi_workload.echo",            {}),
    ("50ms",  "conductor.kpi_workload.slow_then_count", {"sleep_seconds": 0.05}),
    ("500ms", "conductor.kpi_workload.slow_then_count", {"sleep_seconds": 0.5}),
]


@dataclass
class BucketResult:
    bucket: str
    method: str
    jobs: int
    wall_seconds: float
    jobs_per_sec: float


@dataclass
class KPI5Result:
    engine: str
    buckets: list[BucketResult] = field(default_factory=list)
    notes: str = ""


def _drain(engine: Engine, job_ids: list[str], deadline: float) -> int:
    terminal: set[str] = set()
    while time.time() < deadline and len(terminal) < len(job_ids):
        for jid in job_ids:
            if jid in terminal:
                continue
            if engine.get_status_nonblocking(jid) != PENDING:
                terminal.add(jid)
        time.sleep(0.5)
    return len(terminal)


def _run_bucket(engine: Engine, bucket: str, method: str, kwargs: dict) -> BucketResult:
    workload.reset_counter(COUNTER_NAME)

    job_ids: list[str] = []
    enqueue_start = time.time()
    for _ in range(JOBS_PER_BATCH):
        jid = engine.enqueue(method, timeout=120,
                             counter_name=COUNTER_NAME, **kwargs)
        job_ids.append(jid)
    enqueue_elapsed = time.time() - enqueue_start

    drain_start = time.time()
    deadline = drain_start + DRAIN_TIMEOUT_SECONDS
    terminal_count = _drain(engine, job_ids, deadline)
    drain_elapsed = time.time() - drain_start

    # Wall time is enqueue + drain — the user sees both.
    wall = enqueue_elapsed + drain_elapsed
    jps = terminal_count / wall if wall > 0 else 0.0

    print(f"  bucket={bucket}: {terminal_count}/{JOBS_PER_BATCH} terminal "
          f"in {wall:.1f}s = {jps:.1f} jobs/sec (enqueue {enqueue_elapsed:.1f}s, drain {drain_elapsed:.1f}s)")

    return BucketResult(
        bucket=bucket, method=method, jobs=terminal_count,
        wall_seconds=wall, jobs_per_sec=jps,
    )


def run(engine: Engine) -> KPI5Result:
    print(f"\n=== KPI 5 (throughput) — engine={engine.name} ===")
    engine.setup()
    # No scheduler needed — these are happy-path jobs, no retries.
    engine.spawn_worker()

    buckets: list[BucketResult] = []
    for bucket, method, kwargs in BUCKETS:
        engine.cleanup_state()  # fresh state per bucket
        # Re-spawn worker so each bucket gets a clean executor (matters for
        # Conductor where the worker's pool may carry over).
        engine.teardown()
        engine.spawn_worker()
        buckets.append(_run_bucket(engine, bucket, method, kwargs))

    engine.teardown()
    return KPI5Result(engine=engine.name, buckets=buckets)
