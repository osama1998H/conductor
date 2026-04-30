# Migrate from RQ to Conductor

This page covers the one-shot RQ-to-Conductor migration: previewing what will move, committing the move, and re-running on a previously-migrated site.

You succeed when every pending RQ job for the target site has been re-enqueued onto Conductor and removed from its RQ pending registry, the Redis marker is set, and your worker is now consuming Conductor streams instead of RQ queues.

The migration is intentionally **narrow**. It only handles RQ's **pending** registry — started, failed, and scheduled registries are out of scope. Stop the producers that still call `frappe.enqueue` (or that route through `conductor.frappe_compat.enqueue`'s HTTP shim) before you commit, so the pending registry is a stable target.

---

## Procedure 1 — Dry-run

Always start with a dry-run. The default invocation runs no commits.

```bash
bench conductor migrate-from-rq --site SITE
```

Note: `migrate-from-rq` takes `--site` as its own option (not bench's `--site`). See [`reference-cli.md`](reference-cli.md#migrate-from-rq) for the full surface.

The output reports:

- `plan rows` — total candidate jobs.
- `skipped (other site)` — RQ jobs whose `kwargs.site` does not match `--site`. The migration only moves jobs that target this site, so multi-tenant benches can run the migration per tenant safely.
- `skipped (callable)` — RQ jobs whose `method` is a callable object rather than a dotted path. Conductor only accepts dotted paths.
- `failed` — always 0 in a dry-run.
- `unmapped queues seen` — RQ queues with no `--queue-map` entry. These will fall back to the Conductor `default` queue at commit time.
- The first 5 plan rows in detail.

If `unmapped queues seen` lists queues you care about, supply a `--queue-map`:

```bash
bench conductor migrate-from-rq --site SITE \
  --queue-map 'short=short,default=default,long=long,custom=urgent'
```

The default map is identity for the standard `short`, `default`, and `long` queues.

---

## Procedure 2 — Commit

Once the dry-run looks right, commit:

```bash
bench conductor migrate-from-rq --site SITE --commit
```

Conductor prints a warning, then prompts for confirmation. Type `y` to proceed (or run with `yes |` piped in if you are scripting it). The command is **not** automatically dangerous — it is idempotent via the marker — but `--commit` deserves an explicit click in interactive use.

For each candidate job, the commit:

1. Calls `conductor.enqueue(method, queue=target_queue, **kwargs)`.
2. On success, calls `job.delete()` on the RQ side.
3. Increments `moved` for the report.

If the RQ delete fails after a successful enqueue, the job is counted in `failed` — Conductor enqueued it, but the RQ registry still contains the original. Operator cleanup is required before re-running.

After a commit pass that moved at least one job (or skipped/found unmapped queues), Conductor writes a marker key:

```
conductor:{site}:rq_migrated_at = <ISO8601 timestamp>
```

The marker makes re-runs idempotent — a second invocation skips immediately and prints "Site SITE already has an RQ migration marker."

---

## Procedure 3 — Re-run after the marker

You will rarely need this. Use it when:

- The first commit hit `failed > 0` and you have manually cleaned up the RQ side.
- You stopped producers, ran the migration, restarted producers prematurely, and a new batch of pending jobs appeared.

```bash
bench conductor migrate-from-rq --site SITE --commit --force
```

`--force` ignores the marker. **Do not** combine `--force` with active producers still publishing to RQ — at-least-once delivery becomes "as many times as you re-ran the migration."

---

## What is moved and what is not

| Source | Destination | Behavior |
|---|---|---|
| RQ **pending** registry, dotted-path method, matching site | Conductor stream `conductor:{site}:stream:<target_queue>` | Re-enqueued via `conductor.enqueue`. RQ row deleted on success. |
| RQ **pending** registry, callable method | — | Skipped (counted in `skipped_callable_method`). Conductor only accepts dotted paths. |
| RQ **pending** registry, `kwargs.site` ≠ target site | — | Skipped (counted in `skipped_other_site`). |
| RQ **started** registry | — | Out of scope. Let the existing RQ worker finish them, then run the migration. |
| RQ **failed** registry | — | Out of scope. Triage in RQ before migrating. |
| RQ **scheduled** registry | — | Out of scope. Re-create as `Conductor Schedule` rows after the migration. |

The migration also does **not** delete RQ keys outside the pending jobs themselves. Old registries, queue metadata, and worker entries remain — they are harmless once your producers and workers no longer touch RQ.

---

## If something went wrong

- **"already has an RQ migration marker"** — a previous commit succeeded. Use `--force` only if you know why you are re-running.
- **`failed` > 0 after commit** — Conductor enqueued the job, but `job.delete()` on the RQ side failed. The RQ registry still has the original. Inspect those `rq_job_id`s in the report, delete them by hand, and decide whether to `--force` re-run.
- **Some RQ queues not in the report** — they had zero pending jobs at the moment the dry-run ran. Either there are none to migrate, or producers are still publishing to those queues; stop the producers and re-run the dry-run.
- **`unmapped queues seen` non-empty** — those queues are not named in your `--queue-map` and fell back to `default`. Add an explicit map entry or accept the fallback.
- **Conductor worker idle after commit** — no worker is consuming the Conductor target queue. Start one with `bench --site SITE conductor worker --queue <name>`.
- **Producers still write to RQ** — the `frappe.enqueue` HTTP override only intercepts HTTP calls. Migrate intra-process call sites to `conductor.enqueue(...)` directly. See [`how-to-enqueue-jobs.md`](how-to-enqueue-jobs.md#procedure-3--override-frappeenqueue-app-wide).

---

## See also

- [`reference-cli.md`](reference-cli.md#migrate-from-rq) — full flag table.
- [`how-to-enqueue-jobs.md`](how-to-enqueue-jobs.md) — once migrated, the steady-state enqueue path.
- [`explanation-architecture.md`](explanation-architecture.md) — why the marker is per-(site) and what `conductor:{site}:rq_migrated_at` actually stores.
