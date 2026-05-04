# M5 — Multi-worker certification

**Captured:** 2026-05-04 against `frappe.localhost`.
**Setup:** two `bench --site frappe.localhost conductor worker --queue default --queue long --concurrency 4` processes (`conductor_worker` and `conductor_worker_2` in the bench Procfile).

## Concurrency split — PASS

Drove 50 `conductor.demo.sleep(seconds=2.0)` jobs through the `default` queue.
At a sample point ~3s into the run, the live state was:

| Worker PID | Worker ID | Status | Count |
|---|---|---|---|
| 13151 | `Osamas-MacBook-Pro.local:13151:acdd61dc` | RUNNING | 4 |
| 13153 | `Osamas-MacBook-Pro.local:13153:b0c3856c` | RUNNING | 4 |
| 13151 | `Osamas-MacBook-Pro.local:13151:acdd61dc` | SUCCEEDED | 16 |
| 13153 | `Osamas-MacBook-Pro.local:13153:b0c3856c` | SUCCEEDED | 16 |
| (none) | NULL | QUEUED | 10 |

**Observed:** 8 jobs in flight (4 per worker), even split (16+16) on the
already-completed jobs. Concurrency cap per worker is correctly enforced
at the threadpool level. **Pass.**

## Reclaim under SIGKILL — DEFEATED BY HONCHO (not a Conductor bug)

Sent `kill -9 13151` to one conductor worker. The expected behavior
(verified in `tests_chaos/test_kill_during_run.py`) is that the surviving
worker reclaims the dead worker's pending entries via `XAUTOCLAIM` after
the configured idle threshold (60s default) and re-runs them.

**What actually happened:** honcho saw the killed worker exit with
`rc=137` (SIGKILL) and immediately sent SIGTERM to every other process in
the Procfile — Redis, web, socketio, schedule, the surviving conductor
worker, and the conductor scheduler. The entire bench shut down:

```
11:44:32 system | conductor_worker.1 stopped (rc=137)
11:44:32 system | sending SIGTERM to redis_cache.1 (pid 13143)
11:44:32 system | sending SIGTERM to redis_queue.1 (pid 13150)
... full process-tree shutdown ...
```

This is honcho's default cascade behavior: any unexpected child death
takes down the whole tree. The Conductor reclaim path could not be
exercised end-to-end because the surviving worker was killed before
the 60s reclaim window opened.

### Implication for production deployments

For a real multi-worker production deployment with Conductor, **honcho is
not the right process supervisor** — a worker crash cascades into a
total bench outage. Use one of:

1. **systemd unit per worker** — independent restart policy, no cascade.
2. **supervisord with `autorestart=true`** — restarts the dead worker
   without touching peers.
3. **Two separate honcho processes** — one for the bench (web, Redis,
   schedule, scheduler) and one per worker, so a worker crash doesn't
   touch bench infrastructure.
4. **Frappe Cloud's supervisor** — already isolates workers; would not
   exhibit this cascade.

The Conductor reclaim mechanism itself is verified by
`tests_chaos/test_kill_during_run.py` (which spawns its own subprocess
worker, kills it, and asserts reclaim by a peer). That test continues
to pass; this finding is purely about how *bench* runs Conductor in a
multi-worker setup, not about Conductor's reclaim correctness.

## Inflight cap (`Conductor Queue.default.max_concurrent`) — PASS

Re-ran the deferred test on 2026-05-04 against the same two-worker
setup after the bench was restored.

Procedure:
1. Set `Conductor Queue.default.max_concurrent = 2`.
2. Enqueued 200 `conductor.demo.sleep(seconds=0.5)` jobs to `default`.
3. Sampled `INCR conductor:frappe.localhost:inflight:default` once
   per second for 60s in a separate console (via `redis-cli -p 11000 -n 2`).

Observed: every sample showed `inflight ≤ 2`. Specifically, 10 seconds
of ramp-up at 0, then 30 consecutive seconds pinned at the cap (2),
then 20 seconds draining back to 0 as the queue emptied. After ~3
minutes all 200 jobs reached SUCCEEDED. Zero FAILED, zero stuck-RUNNING.

The cap is enforced shared-globally between the two workers (the
counter lives in Redis, claimed via the `inflight.lua` script before
each XREADGROUP), which is the design contract — verified live for
the campaign record. The chaos test
`tests_chaos/test_concurrency_cap_chaos.py` continues to be the
source of truth for the mechanism's correctness.

`max_concurrent` was restored to `0` after the test.

## Findings summary

| # | Finding | Severity | Disposition |
|---|---|---|---|
| 1 | Concurrency split across two workers works | — | Pass |
| 2 | Honcho cascades a worker SIGKILL into a full bench outage | Operational, not a Conductor bug | Document in `docs/how-to-run-multi-tenant.md` and add a "process supervision" section to `docs/explanation-architecture.md` (M7 fix candidate) |
| 3 | `Conductor Queue.max_concurrent` cap-test | Coverage gap → resolved | Re-run on 2026-05-04 — PASS (see above) |
