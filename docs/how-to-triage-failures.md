# Triage failures

This page covers DLQ triage: finding a failed job, deciding what to do with it, and acting on that decision via the dashboard or the CLI.

You succeed when every `PENDING_REVIEW` DLQ entry has been turned into either `RETRIED` or `DISCARDED`, and you understand why each call went the way it did.

If the DLQ keeps refilling immediately after retries, the underlying bug is not transient — pause your operator triage and read [`explanation-reliability.md`](explanation-reliability.md#the-dlq) before continuing.

---

## Procedure 1 — Find a failed job

Two paths, depending on whether you are at the dashboard or in a terminal.

**Dashboard path:**

1. Open `https://<site>/conductor-dashboard` and click the **DLQ** tab.
2. Filter by queue, status, or error type using the column filters at the top of the table.
3. Click any row to see the full traceback, the original args/kwargs, and the action buttons.

**CLI path:**

```bash
bench conductor dlq list --site SITE                # all queues
bench conductor dlq list --site SITE --queue default
bench conductor dlq list --site SITE --status PENDING_REVIEW --limit 100
```

Note: `dlq` takes `--site` as its own option (not bench's `--site`). See [`reference-cli.md`](reference-cli.md#dlq) for the full surface.

The CLI output shows: entry `name`, `job` id, `queue`, `moved_at`, `last_error_type`, `last_error_message`. Newest first; capped at `--limit` (default 50).

---

## Procedure 2 — Retry one or many

Retry re-enqueues the original payload via `conductor.enqueue` and marks the DLQ entry `RETRIED`.

**One job at a time:**

```bash
bench conductor dlq retry --site SITE --job <job_id>
```

**Bulk by queue:**

```bash
bench conductor dlq retry --site SITE --queue default --limit 50
```

**From the dashboard:**

1. In the DLQ tab, multi-select rows with the row checkboxes.
2. Click **Retry**. The action runs every selected entry through `dlq_retry`.

Retry is reversible — the new job runs and either succeeds or returns to the DLQ. Retry is available to **Conductor Operator** and **System Manager**.

### Edit-and-retry

If the original payload is wrong (a typo in `invoice="INV-001"`, the wrong queue), use **Edit & Retry** instead:

1. Open a single DLQ entry from the dashboard.
2. Click **Edit & Retry**. The form lets you modify args/kwargs as JSON.
3. Save. Conductor enqueues a new job with the modified payload and marks the DLQ entry `RETRIED`.

Edit-and-retry is **System Manager only**. The CLI does not expose it — destructive payload changes happen in the audited dashboard form.

---

## Procedure 3 — Discard

Discard marks a DLQ entry `DISCARDED` without re-enqueuing. The job will not run again.

**CLI:**

```bash
bench conductor dlq discard --site SITE --job <job_id>
bench conductor dlq discard --site SITE --queue default --limit 20
```

**Dashboard:**

1. Multi-select rows.
2. Click **Discard**. Confirm the modal.

Discard is destructive — once an entry is `DISCARDED`, the original `Conductor Job` row remains for the audit trail, but no further automated action is taken. Discard is **System Manager only** in both surfaces.

Use discard when:

- You can verify the side effect already succeeded by another path.
- The work is no longer relevant (the user cancelled the order, the schedule fired again with a fresh payload).
- You decided the work is unrecoverable and the audit row is the documentation.

---

## Permissions at a glance

| Action | Conductor Operator | System Manager |
|---|---|---|
| `dlq list`, view DLQ tab | ✅ | ✅ |
| `dlq retry` (one or many) | ✅ | ✅ |
| `Edit & Retry` (modify payload) | ❌ | ✅ |
| `dlq discard` | ❌ | ✅ |

The full matrix lives at [`reference-configuration.md`](reference-configuration.md#roles-and-permissions). The dashboard hides actions a role cannot perform; the CLI runs as the bench user and inherits that user's roles.

---

## If something went wrong

- **`dlq list` prints "No DLQ entries match"** — your filter excluded everything. Drop `--queue` or `--status` to see the full set.
- **A retried job lands back in the DLQ immediately** — the failure is not transient. Read `last_traceback` on the new `Conductor Job` row, fix the underlying bug, and only then retry. Bulk-retrying a code-bug DLQ just amplifies noise.
- **`dlq discard` returns "not found"** — another operator already actioned that entry. Re-run `dlq list --status PENDING_REVIEW` to see the current state.
- **Edit & Retry button is missing** — your role is Conductor Operator, not System Manager. Ask a System Manager to do the edit.
- **DLQ growth alarm tripped** — the underlying error rate has spiked. Triage the **error type** (group by `last_error_type`) before deciding to bulk-retry; usually one bug is responsible for most entries.

---

## See also

- [`reference-cli.md`](reference-cli.md#dlq) — the full DLQ CLI surface.
- [`explanation-reliability.md`](explanation-reliability.md#the-dlq) — when the sweeper moves a job to the DLQ and what the DLQ is not (it is not auto-recovery).
- [`reference-configuration.md`](reference-configuration.md#conductor-dlq-entry) — the DocType fields, including `payload` (used by Edit & Retry) and the review audit columns.
