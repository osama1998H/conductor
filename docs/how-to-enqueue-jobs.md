# Enqueue jobs

This page covers the three ways an app developer puts work onto a Conductor queue: enqueue from inside a Frappe app, deduplicate concurrent enqueues with an idempotency key, and route every existing `frappe.enqueue` call to Conductor at once.

You succeed when `conductor.enqueue(...)` returns a `job_id` and the worker logs that job running on the matching queue.

---

## Procedure 1 — Enqueue a job from a Frappe app

1. From any Python module that runs inside a Frappe context (a controller, hook, request handler, scheduled method, or another job), import Conductor and call `enqueue`:

    ```python
    import conductor

    job_id = conductor.enqueue(
        "myapp.tasks.send_email",
        queue="default",
        invoice="INV-001",
    )
    ```

2. Confirm the function on the dotted path is importable from the worker's environment. The dispatcher resolves it via `frappe.get_attr("myapp.tasks.send_email")` at enqueue time so it can read the `@conductor.job` decorator if any.

3. Verify the queue exists and is enabled. The dispatcher rejects enqueues to a disabled `Conductor Queue` row.

4. Watch the dispatch land:

    ```bash
    bench --site frappe.localhost console
    ```

    ```python
    import conductor
    job_id = conductor.enqueue("frappe.utils.now")
    print(job_id)
    ```

    The printed string is a UUID. The corresponding row appears in `Conductor Job` with `status="QUEUED"` and a `redis_msg_id` set.

The full signature lives at [`reference-python-api.md`](reference-python-api.md#conductorenqueue).

---

## Procedure 2 — Make an enqueue idempotent

Use `idempotency_key=` whenever two callers might race on the same logical operation (concurrent webhooks, retried HTTP requests, schedule re-fires).

1. Pick a stable key that uniquely names the logical operation. Include the version of the operation if you change behavior over time:

    ```python
    job_id = conductor.enqueue(
        "myapp.tasks.send_email",
        queue="default",
        idempotency_key="invoice:INV-001:reminder:1",
        invoice="INV-001",
    )
    ```

2. Call `enqueue` from every producer with that same key string. The first call wins the Redis slot and runs the job; later calls within the TTL return the same `job_id` without enqueuing.

3. Configure the TTL if 24 h does not match your business window. Set `conductor.idempotency_ttl_seconds` in `site_config.json`. Keep it at least as long as the longest expected duplicate-dispatch gap.

4. Make the **job body** idempotent at the side-effect boundary too. The key dedupes dispatches; it cannot un-send an email. See [`explanation-reliability.md`](explanation-reliability.md#idempotency-keys) for what this protects and what it does not.

---

## Procedure 3 — Override `frappe.enqueue` app-wide

Conductor ships a shim with `frappe.enqueue`'s exact call signature so existing code paths can switch over without changing every call site.

1. In a **client** app's `hooks.py` (not Conductor's), add the override:

    ```python
    override_whitelisted_methods = {
        "frappe.enqueue": "conductor.frappe_compat.enqueue",
    }
    ```

2. Run `bench --site SITE clear-cache` so Frappe picks up the new override map.

3. Hit a `frappe.enqueue` HTTP endpoint and confirm the job lands on a Conductor queue, not RQ.

**Caveat — read carefully.** `override_whitelisted_methods` rewrites HTTP `/api/method/frappe.enqueue` calls only. Intra-process Python calls (`frappe.enqueue(...)` from inside a controller, hook, or other background task) **bypass** the override and still go to Frappe RQ. To route every enqueue path, change those call sites to `conductor.enqueue(...)` directly, or migrate them in a follow-up pass after the HTTP override has shaken out.

---

## If something went wrong

- **`ImportError: No module named 'conductor'` from the worker** — Conductor is not installed on the site you are dispatching to. Run `bench --site SITE install-app conductor` and restart the worker.
- **`enqueue` returns a `job_id` but the job never runs** — no worker is consuming the queue. Run `bench --site SITE conductor worker --queue <name>` and check `bench --site SITE conductor depth` for the queue's stream length.
- **Two `enqueue` calls with the same `idempotency_key` return different ids** — the keys are not byte-identical (whitespace, case), or the TTL elapsed between calls. Print the keys before dispatch and confirm they match exactly.
- **`frappe.ValidationError: Queue 'default' is disabled`** — open `Conductor Queue` in the Desk and re-enable the row, or pass an enabled `queue=` argument.
- **Override added but old code still goes to RQ** — those code paths are intra-process, not HTTP. See the caveat above.
