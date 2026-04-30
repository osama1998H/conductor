# Run multi-tenant

This page covers Conductor's pool worker mode: serving multiple sites from one process, capping per-tenant throughput and concurrency, and inspecting depth across the fleet.

You succeed when one `bench conductor worker` process consumes streams from N sites in parallel, per-tenant caps throttle without failing jobs, and `depth --all-sites` shows the full picture.

---

## Procedure 1 — Switch a worker to pool mode

A pool worker reads `--sites` instead of relying on bench's `--site`.

1. Decide between auto-discovery and an explicit list:

    ```bash
    # Auto: walk sites/<dir>/site_config.json and serve any with conductor installed.
    bench conductor worker --sites=auto --queue default --concurrency 8

    # Explicit list:
    bench conductor worker --sites=alpha.test,beta.test --queue default --concurrency 8
    ```

2. Update your `Procfile` so `bench start` launches the pool worker. A typical pool entry alongside an existing single-site setup:

    ```
    conductor_worker_pool: bench conductor worker --sites=auto --queue default --concurrency 8
    ```

3. Run `bench start`. The pool process logs every site it picked up at boot.

The site list is resolved **once at boot**. Onboarding a new tenant requires restarting the pool worker so discovery runs again. There is no daemon and no re-scan.

`--sites=auto` errors out (exit 2) if discovery returns zero sites. Pass `--sites=site1,site2,...` explicitly if you mean to start with no installed-conductor sites.

---

## Procedure 2 — Set per-tenant rate limits and concurrency caps

Two fields on each `Conductor Queue` row enforce per-tenant throttling.

1. Open `Conductor Queue` in the Desk for the relevant site.
2. Set the cap fields:

    | Field | `0` (unlimited) | Meaning |
    |---|---|---|
    | `max_rps` | default | Tokens per second, enforced by an atomic Redis Lua bucket on `conductor:{site}:rate:{queue}`. |
    | `max_concurrent` | default | Cap on simultaneously RUNNING jobs across the worker fleet, enforced on `conductor:{site}:inflight:{queue}`. |

3. Save. The new caps apply to the next job dispatched for that queue. No worker restart needed.

A throttled job is **not a failure**. It lands in `SCHEDULED_RETRY` with `last_error_message="rate_limited"` or `"inflight_capped"`, rides the existing retry-delay loop, and rejoins the queue when capacity returns. The dashboard shows throttled-job counts alongside actual retries.

Caps are per pool process, not fleet-wide. Two pool workers each running `max_rps=10` will collectively burst to 20 RPS. Cluster-wide caps require a token broker outside Conductor.

---

## Procedure 3 — Inspect per-(site, queue) depth

`depth` is the operator's first tool when something feels stuck.

```bash
# One site:
bench --site=alpha.test conductor depth

# Every conductor-installed site:
bench conductor depth --all-sites
```

Columns: `queue`, `stream` (XLEN), `dlq` (XLEN), `scheduled` (per-site ZCARD), `inflight`, `max_rps`, `max_concurrent`.

Reading the table:

- A high `stream` with low `inflight` — workers are not consuming, or are blocked elsewhere. Check the worker process is alive and connected.
- `inflight` == `max_concurrent` and rising `scheduled` — the cap is the bottleneck. Either raise it or accept the throttle.
- `dlq` non-zero and growing — see [`how-to-triage-failures.md`](how-to-triage-failures.md).

---

## If something went wrong

- **`--sites=auto` matched zero sites (exit 2)** — discovery found no `site_config.json` files with `conductor` in `installed_apps`. Either install Conductor on at least one site, or pass `--sites=...` explicitly.
- **Pool worker doesn't pick up a newly-installed tenant** — discovery is one-shot at boot. Restart the pool worker.
- **Caps allow more throughput than `max_rps` suggests** — caps are per pool process, not cluster-wide. Add the per-process budgets across all workers; that is your effective fleet cap.
- **Jobs sit in `SCHEDULED_RETRY` forever** — `max_rps=1` or similar very-tight cap, plus a high inflow rate. Raise the cap (or add workers) until the drain rate matches inflow.
- **`depth --all-sites` skips a site with a warning** — discovery hit an error connecting to that site (corrupt `site_config.json`, MariaDB down). The log line names the site; the others still print.
- **One tenant's queue starves the others** — the pool worker `XREADGROUP`s every stream, but a thread-pool slot is occupied by whichever site claimed it first. Increase `--concurrency`, or run a dedicated worker for the loud tenant.

---

## See also

- [`reference-cli.md`](reference-cli.md#worker) — full `worker` and `depth` flag tables.
- [`reference-configuration.md`](reference-configuration.md#conductor-queue) — the `max_rps` and `max_concurrent` field semantics.
- [`explanation-architecture.md`](explanation-architecture.md#pool-worker-model) — how site discovery and per-stream routing work under the hood.
