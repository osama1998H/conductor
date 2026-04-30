"""KPI 3 — Permanent-Failure Visibility (queryable DLQ).

Question: after a job exhausts its retries, can the operator find it and
retry it via a single SQL query (or HTTP call) — no SSH, no `bench
console`, no Redis CLI?

Workload: 20 jobs of `always_fail` with max_attempts=2 (kept short to
finish quickly; this KPI is about post-mortem properties, not throughput).
Once they've all reached terminal failure, we evaluate two properties.

Reports:
  sql_queryable        — True iff list_failed_jobs() is backed by SQL
  ops_to_retry_one     — discrete CLI/HTTP ops to retry ONE failed job
                         (1 = single command/click; >1 = multi-step
                         interactive workflow)
  found_count          — sanity check that the failures actually landed
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .harness import (
    Engine,
    PENDING,
)


TOTAL_JOBS = 20
DRAIN_TIMEOUT_SECONDS = 240.0


@dataclass
class KPI3Result:
    engine: str
    sql_queryable: bool
    ops_to_retry_one: int
    found_count: int
    expected_count: int
    retry_command: str
    notes: str = ""


# How many discrete operator steps does it take to retry one failed job?
#   Conductor: `bench --site <site> conductor dlq retry --job <id>`  → 1
#   RQ: open `bench console` → import rq → fetch FailedJobRegistry →
#       call requeue() on it → exit. 4 steps minimum, even if you scripted
#       it as a one-liner you still need a Python interpreter with Frappe
#       initialized (i.e. a `bench --site <site> execute ...`). Counted as
#       3 (interpreter + import + retry call).
RETRY_OPS = {
    "conductor": (
        1,
        "bench --site <site> conductor dlq retry --job <job_id>",
    ),
    "rq": (
        3,
        "bench --site <site> execute 'rq.registry.FailedJobRegistry(...).requeue(<id>)'",
    ),
}


def run(engine: Engine) -> KPI3Result:
    print(f"\n=== KPI 3 (dlq-visibility) — engine={engine.name} ===")
    engine.setup()
    if hasattr(engine, "spawn_scheduler"):
        engine.spawn_scheduler()
    engine.spawn_worker()

    job_ids: list[str] = []
    for _ in range(TOTAL_JOBS):
        jid = engine.enqueue(
            "conductor.kpi_workload.always_fail",
            timeout=60,
            max_attempts=2,
            counter_name="kpi03",
        )
        job_ids.append(jid)

    deadline = time.time() + DRAIN_TIMEOUT_SECONDS
    terminal: set[str] = set()
    while time.time() < deadline and len(terminal) < TOTAL_JOBS:
        for jid in job_ids:
            if jid in terminal:
                continue
            if engine.get_status_nonblocking(jid) != PENDING:
                terminal.add(jid)
        time.sleep(1.0)

    failed = engine.list_failed_jobs()
    found_count = len(failed)
    sql_queryable = engine.queryable_via_sql()
    ops, retry_cmd = RETRY_OPS[engine.name]

    notes = ""
    if found_count < TOTAL_JOBS:
        notes = f"found {found_count}/{TOTAL_JOBS} failed jobs (drain may have timed out)"

    print(f"=== sql_queryable={sql_queryable} ops_to_retry_one={ops} found={found_count}/{TOTAL_JOBS} ===")
    print(f"=== retry command: {retry_cmd}")

    engine.teardown()
    return KPI3Result(
        engine=engine.name,
        sql_queryable=sql_queryable,
        ops_to_retry_one=ops,
        found_count=found_count,
        expected_count=TOTAL_JOBS,
        retry_command=retry_cmd,
        notes=notes,
    )
