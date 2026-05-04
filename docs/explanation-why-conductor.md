# Why Conductor (vs Frappe RQ)

Conductor positions itself as a reliability-first replacement for Frappe RQ. This page is the receipts: the measurements, the methodology, and the limits of what those measurements prove.

The KPI suite is reproducible — every number comes from running both engines on the same site, under the same workload, on the same bench.

---

## At a glance

Measured on the same site, same workload:

- ⚡ **~4× faster throughput** at every job size (1 ms · 50 ms · 500 ms)
- 🔁 **50× fewer duplicate executions** under concurrent producers (1 vs 50)
- 📋 **4× more audit detail** when retries fire (100% vs 25% per-attempt records preserved)
- ♻️ **Recovers transient failures by default** — RQ does not retry non-DB exceptions at all
- 🔍 **DLQ in SQL, retry in one command** — RQ needs `bench console` + Python

---

## The KPI table

| KPI | Conductor | Frappe RQ | Conductor wins? |
|---|---|---|---|
| **1. Transient-failure recovery** — % of jobs failing with a non-DB exception that recover via the platform's default retry | **100%** (mean 3.00 attempts) | **0%** | ✅ |
| **2. Per-attempt audit completeness** — records preserved / actual attempts that ran (counter-verified, both engines configured for retries) | **100%** (150/150) | **25%** (50/200 — RQ runs 4 attempts but stores only the last failure per job) | ✅ |
| **3. DLQ visibility** — failed jobs queryable via SQL? Distinct ops to retry one failed job? | **yes** / **1 op** (`bench conductor dlq retry`) | **no** / **3+ ops** (`bench console` + Python) | ✅ |
| **4. Dispatch idempotency** — executions per logical job when 50 producers race the same business key (target: 1) | **1** | **50** (RQ has no `idempotency_key` parameter; users can manually translate the business key to `job_id` and get partial dedup with registry-eviction caveats — Conductor does this natively) | ✅ |
| **5. Throughput** — jobs/sec, single worker | 1 ms: **144** · 50 ms: **49** · 500 ms: **7.4** | 1 ms: 34 · 50 ms: 11 · 500 ms: 1.8 | ✅ (4.1–4.3×) |

---

## Methodology

The suite lives at [`tests/comparative/`](../tests/comparative/) and is driven by [`tests/comparative/run_kpis.py`](../tests/comparative/run_kpis.py).

For each KPI, the harness:

1. Picks a workload that isolates the property under test (transient failure injection for KPI 1, parallel producers racing one key for KPI 4, etc.).
2. Runs the workload first against Conductor, then against Frappe RQ — same site, same job bodies, same retry budget where the engines support it.
3. Reads ground truth from the engine's own state (Conductor's `tabConductor Job Run`, RQ's `Job` registries) plus a counter the harness installs in the job body.
4. Reports a single normalized number per engine.

KPI 5's throughput numbers come from a single-worker run on a macOS dev bench; the per-job sleep budget approximates real workloads at three sizes.

The harness lives in `tests/comparative/`; each KPI is a runnable script that emits a single number per engine.

---

## What this measurement cannot tell you

A KPI list with one honest "we couldn't prove this" entry is more credible than five wins. Surface what the numbers do **not** prove.

- **Throughput is macOS-only.** RQ workers `fork()` per job. Darwin's `fork` is expensive; Linux production servers will likely show a smaller gap. Re-run KPI 5 on your target OS before any throughput-based decision.
- **Single-worker numbers do not extrapolate to a fleet.** The dispatcher and Redis stay common; pool-mode workers and high-concurrency setups will hit other bottlenecks.
- **Crash-survival was tested and dropped.** A sixth KPI — "Crash-Survival Rate" under worker SIGKILL with a peer alive — was investigated and **dropped because RQ matched Conductor**. RQ's `clean_registries` mechanism (called by the surviving peer on heartbeat expiry) recovers started-registry orphans automatically. The original investigation is preserved at [`tests/comparative/_dropped_crash_survival.py`](../tests/comparative/_dropped_crash_survival.py); the file's module docstring captures the reasoning.
- **The KPIs do not measure ergonomics.** Workflow DAGs, edit-and-retry, and the dashboard are real Conductor advantages — but the KPI suite measures behavior under stress, not developer experience.

---

## Reproducing the suite

From the bench root:

```bash
cd apps/conductor
/path/to/bench/env/bin/python -m tests.comparative.run_kpis --kpi 1 --engine both
# repeat with --kpi 2..5
```

`--engine both` runs Conductor first, then RQ; pass `--engine conductor` or `--engine rq` to run only one side. Each KPI module also has its own pytest case under `tests/comparative/kpi_0X_*.py` for unit-level reproduction.

---

## See also

- [`explanation-architecture.md`](explanation-architecture.md) — how Conductor is built. Several KPI wins follow directly from architectural choices (idempotency in Lua, per-attempt rows, DLQ in SQL).
- [`explanation-reliability.md`](explanation-reliability.md) — what Conductor's reliability primitives do and do not protect against.
- [`reference-cli.md`](reference-cli.md) — the operational surface that KPI 3 measures.
