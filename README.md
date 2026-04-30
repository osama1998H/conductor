# Conductor

Reliability-first background job platform for Frappe / ERPNext.

![image](conductor.png)

## Why Conductor (vs Frappe RQ)

Measured on the same site, same workload:

- ⚡ **~4× faster throughput** at every job size (1 ms · 50 ms · 500 ms)
- 🔁 **50× fewer duplicate executions** under concurrent producers (1 vs 50)
- 📋 **4× more audit detail** when retries fire (100% vs 25% per-attempt records preserved)
- ♻️ **Recovers transient failures by default** — RQ does not retry non-DB exceptions at all
- 🔍 **DLQ in SQL, retry in one command** — RQ needs `bench console` + Python

Full KPI table, methodology, and limits at [`docs/explanation-why-conductor.md`](docs/explanation-why-conductor.md).

## Quickstart

```bash
# 1. Install on a site
bench --site <site> install-app conductor

# 2. Append worker + scheduler to the bench Procfile
echo "conductor_worker: bench --site <site> conductor worker --queue default --concurrency 4" >> Procfile
echo "conductor_scheduler: bench --site <site> conductor scheduler" >> Procfile
bench start

# 3. Verify end-to-end
bench --site <site> conductor doctor --demo
```

The full walkthrough lives at [`docs/tutorial-getting-started.md`](docs/tutorial-getting-started.md).

## Documentation

Start at [`docs/index.md`](docs/index.md). Most-trafficked pages:

- [Tutorial — Get started](docs/tutorial-getting-started.md)
- [How-to — Enqueue jobs](docs/how-to-enqueue-jobs.md)
- [How-to — Triage failures](docs/how-to-triage-failures.md)
- [Reference — CLI](docs/reference-cli.md)
- [Reference — Configuration](docs/reference-configuration.md)
- [Why Conductor (vs Frappe RQ)](docs/explanation-why-conductor.md)

## Status

Phase 6 of 6 — v1. The full roadmap lives at [`docs/superpowers/specs/2026-04-27-conductor-master-design.md`](docs/superpowers/specs/2026-04-27-conductor-master-design.md).

## Contributing

This app uses `pre-commit` for code formatting and linting. Install it once per clone:

```bash
cd apps/conductor
pre-commit install
```

Behavior change → docs PR in the same commit. The user-facing docs under `docs/` ship with the code.

## License

MIT
