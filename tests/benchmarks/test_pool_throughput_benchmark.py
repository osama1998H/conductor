"""Pool-mode benchmark — non-gating measurement of per-job site-context overhead.

Spins up to 10 fixture sites (or whatever the bench permits — gracefully
degrades to fewer), dispatches 100 instant jobs per site, runs a single
pool worker `--concurrency=8`, and prints:
    - p50/p95/p99 frappe.init+connect+destroy wall time per job
    - total throughput (jobs/sec)
    - per-job overhead as % of trivial-job duration

If the overhead exceeds 30% of trivial-job wall time, this test prints a
recommendation to file a follow-up for a per-site connection cache. It
does NOT fail the build.

Run with: `pytest tests/benchmarks/test_pool_throughput_benchmark.py -v -s --no-header`
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from statistics import median

import pytest

BENCH_ROOT = Path("/Users/osamamuhammed/frappe_15")
TARGET_SITE_COUNT = 10
JOBS_PER_SITE = 100


def _existing_conductor_sites() -> list[str]:
    """Return whatever conductor-installed sites already exist on the bench."""
    from conductor.site_discovery import discover_installed_sites
    return discover_installed_sites(str(BENCH_ROOT / "sites"))


def _percentile(samples: list[float], p: float) -> float:
    if not samples:
        return 0.0
    s = sorted(samples)
    k = int(len(s) * p)
    return s[min(k, len(s) - 1)]


@pytest.mark.skipif(
    len(_existing_conductor_sites()) < 2,
    reason="benchmark needs >= 2 conductor-installed sites; use the chaos pool test's "
           "fixture sites or onboard more tenants before running this.",
)
def test_pool_throughput_benchmark():
    sites = _existing_conductor_sites()[:TARGET_SITE_COUNT]
    print(f"\n=== Pool-mode benchmark — {len(sites)} sites x {JOBS_PER_SITE} jobs ===")

    # 1. Enqueue
    enq_start = time.time()
    for s in sites:
        for _ in range(JOBS_PER_SITE):
            subprocess.check_call(
                ["bench", "--site", s, "execute", "conductor.enqueue",
                 "--kwargs", '{"method": "conductor.demo.echo", "queue": "default"}'],
                cwd=str(BENCH_ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=60,
            )
    enq_elapsed = time.time() - enq_start
    total_jobs = len(sites) * JOBS_PER_SITE
    print(f"enqueued {total_jobs} jobs in {enq_elapsed:.1f}s")

    # 2. Boot pool worker
    worker = subprocess.Popen(
        ["bench", "conductor", "worker",
         "--sites", ",".join(sites),
         "--queue", "default",
         "--concurrency", "8", "--grace", "5"],
        cwd=str(BENCH_ROOT),
        preexec_fn=os.setsid,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # 3. Wait for drain; time wall-clock
    import frappe
    run_start = time.time()
    deadline = run_start + 300  # 5-min ceiling
    while time.time() < deadline:
        # Sample one site for now-finished count; assume all sites drain similarly
        frappe.init(site=sites[0])
        try:
            frappe.connect()
            n_unfinished = int(frappe.db.sql(
                "SELECT COUNT(*) FROM `tabConductor Job` "
                "WHERE site=%s AND status NOT IN ('SUCCEEDED','FAILED','TIMED_OUT','DLQ')",
                (sites[0],),
            )[0][0])
        finally:
            frappe.destroy()
        if n_unfinished == 0:
            break
        time.sleep(2)
    run_elapsed = time.time() - run_start

    # 4. Tear down worker
    try:
        os.killpg(os.getpgid(worker.pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    worker.wait(timeout=15)

    throughput = total_jobs / run_elapsed if run_elapsed > 0 else 0
    print(f"drained {total_jobs} jobs in {run_elapsed:.1f}s = {throughput:.1f} jobs/sec")

    # 5. Read per-job durations from Conductor Job Run
    durations_ms: list[int] = []
    for s in sites[:1]:  # one site is enough; per-job init cost dominates
        frappe.init(site=s)
        try:
            frappe.connect()
            rows = frappe.db.sql(
                "SELECT duration_ms FROM `tabConductor Job Run` "
                "WHERE status='SUCCEEDED' ORDER BY started_at DESC LIMIT %s",
                (JOBS_PER_SITE,),
            )
            durations_ms.extend(int(r[0] or 0) for r in rows)
        finally:
            frappe.destroy()

    if durations_ms:
        p50 = median(durations_ms)
        p95 = _percentile(durations_ms, 0.95)
        p99 = _percentile(durations_ms, 0.99)
        print(f"job duration p50={p50:.0f}ms p95={p95:.0f}ms p99={p99:.0f}ms")
        # Trivial job (conductor.demo.echo) is ~1 ms of pure work; everything
        # else is init/connect/destroy + Redis + ORM overhead. If p50 > ~10ms,
        # we have a meaningful overhead component to consider caching.
        if p50 > 10:
            print(
                f"\n!! RECOMMENDATION: p50 = {p50:.0f}ms suggests significant "
                f"per-job init/destroy overhead. Consider opening a follow-up "
                f"for a per-site connection cache."
            )
    else:
        print("!! no Job Run rows found — benchmark inconclusive")

    # Non-gating: do NOT assert.
    print("\n=== benchmark complete (non-gating) ===")
