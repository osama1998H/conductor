"""KPI 4 — Dispatch Idempotency Under Concurrent Producers.

Question: when N independent producers race to enqueue the same logical
work using a *business-derived* key (not a synthetic uuid), how many
times does the underlying function execute?

Workload: 50 concurrent threads each call
    enqueue(
        "conductor.kpi_workload.increment_only",
        idempotency_key="invoice:INV-001:email",
        counter_name="kpi04",
    )
The enqueued function INCRs a Redis counter and returns. The counter
delta after drain == number of executions of the logical job.

Conductor: SET NX EX on `conductor:{site}:idem:{sha256(key)}` → 1 dispatch,
1 row, 1 execution. Out-of-the-box.

RQ: has no `idempotency_key` parameter and no content-based dedupe. The
harness ignores the key for RQ (per `RQEngine.enqueue` docstring), so each
producer's enqueue is independent → 50 executions. RQ users CAN simulate
some dedupe by manually translating the business key to `job_id` and
accepting the registry-eviction window — that's noted in the report.

Reports:
  executions_per_logical_job   — counter delta (target = 1)
  unique_job_ids_dispatched    — count of distinct platform-level job
                                  records created
"""

from __future__ import annotations

import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from .harness import (
    BENCH_ROOT,
    Engine,
    PENDING,
    SITE,
    TERMINAL_SUCCEEDED,
)
from . import workload


CONCURRENT_PRODUCERS = 50
DRAIN_TIMEOUT_SECONDS = 120.0
IDEM_KEY_TEMPLATE = "invoice:INV-001:email:{ts}"  # one logical job per run


@dataclass
class KPI4Result:
    engine: str
    producers: int
    executions: int
    unique_job_ids: int
    target_executions: int
    notes: str = ""


def run(engine: Engine) -> KPI4Result:
    print(f"\n=== KPI 4 (idempotency) — engine={engine.name} ===")
    engine.setup()
    if hasattr(engine, "spawn_scheduler"):
        engine.spawn_scheduler()
    engine.spawn_worker()

    # Fresh logical-job key for this run.
    counter_name = f"kpi04-{uuid.uuid4().hex[:8]}"
    idem_key = IDEM_KEY_TEMPLATE.format(ts=int(time.time() * 1000))
    workload.reset_counter(counter_name)

    # Multiprocessing — the spec requires "distinct OS processes" because
    # Frappe's thread-local context can't be shared across producer threads
    # cleanly. Each subprocess does its own frappe.init and exits.
    bench_python = str(BENCH_ROOT / "env" / "bin" / "python")
    method = "conductor.kpi_workload.increment_only"

    def producer() -> tuple[bool, str]:
        proc = subprocess.run(
            [bench_python, "-m", "tests.comparative._idempotency_producer",
             engine.name, SITE, method, idem_key, counter_name],
            cwd=str(BENCH_ROOT / "apps" / "conductor"),
            capture_output=True,
            text=True,
            timeout=60,
        )
        out = (proc.stdout or "").strip().splitlines()
        for line in reversed(out):
            if line.startswith("OK:"):
                return True, line[3:]
            if line.startswith("ERR:"):
                return False, line[4:]
        return False, f"no result; rc={proc.returncode}; stderr={proc.stderr[:200]}"

    job_ids: list[str] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=CONCURRENT_PRODUCERS) as pool:
        # Threads only orchestrate the subprocess fan-out; no Frappe state
        # crosses thread boundaries.
        futures = [pool.submit(producer) for _ in range(CONCURRENT_PRODUCERS)]
        for f in as_completed(futures):
            ok, payload = f.result()
            if ok:
                job_ids.append(payload)
            else:
                errors.append(payload)

    print(f"producers finished: {len(job_ids)} enqueues, {len(errors)} errors")
    if errors:
        print(f"sample error: {errors[0]}")

    # Drain — wait for whatever was actually dispatched to complete.
    deadline = time.time() + DRAIN_TIMEOUT_SECONDS
    unique_job_ids = sorted(set(job_ids))
    while time.time() < deadline:
        all_terminal = True
        for jid in unique_job_ids:
            status = engine.get_status_nonblocking(jid)
            if status == PENDING:
                all_terminal = False
                break
        if all_terminal:
            break
        time.sleep(0.5)

    # Settle window so any in-flight INCR commits to redis.
    time.sleep(2.0)

    executions = workload.get_counter(counter_name)
    notes = ""
    if errors:
        notes += f"{len(errors)} producer errors; "

    print(f"=== executions={executions} unique_dispatched={len(unique_job_ids)} (target=1) ===")

    engine.teardown()
    return KPI4Result(
        engine=engine.name,
        producers=CONCURRENT_PRODUCERS,
        executions=executions,
        unique_job_ids=len(unique_job_ids),
        target_executions=1,
        notes=notes,
    )
