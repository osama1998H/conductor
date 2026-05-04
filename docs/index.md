# Conductor — Documentation

Conductor is a reliability-first background job platform for Frappe / ERPNext. These docs are organized by what you are trying to do.

If you are new, start with the [tutorial](tutorial-getting-started.md). If you know Conductor and need a specific answer, jump to the right column below.

**v2.0.0 status:** empirically certified — four-day campaign on a real Frappe + HRMS bench produced 9300+ successful dispatches, 0 failed, every active `Scheduled Job Type` row caught by Conductor's takeover loop. Full certification: [`roadmap/v2-certification/`](roadmap/v2-certification/). v2 roadmap (M1–M9 + v2.1 backlog): [`roadmap/v2.md`](roadmap/v2.md).

---

## Operate Conductor

You install, run, and triage Conductor on a site.

- [Tutorial — Get started with Conductor](tutorial-getting-started.md)
- [How-to — Deploy on Frappe Cloud](how-to-deploy-on-frappe-cloud.md)
- [How-to — Schedule jobs](how-to-schedule-jobs.md)
- [How-to — Route Frappe `Scheduled Job Type` rows through Conductor](how-to-route-frappe-scheduled-jobs.md)
- [How-to — Triage failures](how-to-triage-failures.md)
- [How-to — Run multi-tenant](how-to-run-multi-tenant.md)
- [How-to — Migrate from RQ](how-to-migrate-from-rq.md)
- [Reference — CLI](reference-cli.md)
- [Reference — Configuration](reference-configuration.md)

## Use Conductor in your app

You write Frappe app code that puts work onto Conductor queues.

- [Tutorial — Get started with Conductor](tutorial-getting-started.md)
- [How-to — Enqueue jobs](how-to-enqueue-jobs.md)
- [How-to — Define workflows](how-to-define-workflows.md)
- [Reference — Python API](reference-python-api.md)

---

## Understand Conductor

The why and how. Read these when something surprises you.

- [Why Conductor (vs Frappe RQ)](explanation-why-conductor.md) — the KPI table, methodology, and limits.
- [Architecture](explanation-architecture.md) — components, Redis keyspace, a job's life, scheduler singleton, pool worker model.
- [Reliability](explanation-reliability.md) — at-least-once delivery, idempotency, retries, the DLQ, and workflow compensations.

---

Found a mistake? Open a PR — these docs live in the [Conductor repo](../README.md) and ship with the code.
