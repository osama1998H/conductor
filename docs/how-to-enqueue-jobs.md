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

Conductor ships a shim with `frappe.enqueue`'s exact call signature so existing code paths can switch over without changing every call site. Conductor's own `hooks.py` registers the HTTP override, so `/api/method/frappe.enqueue` calls already route through Conductor on every site that has the app installed — no client setup required.

To catch **in-process** Python calls (`frappe.enqueue(...)` from inside a controller, hook, or another callsite) too, opt in via the bench-wide flag:

1. Edit `sites/common_site_config.json` (top-level — **not** nested under `conductor.*`):

    ```json
    {
      "conductor_intercept_frappe_enqueue": true
    }
    ```

2. Restart bench (`bench restart` or `Ctrl-C` and `bench start`). The flag is read at module load; an existing process will not pick it up.

3. From a Python callsite, dispatch through `frappe.enqueue` and confirm the job lands on a Conductor queue:

    ```python
    import frappe
    frappe.enqueue("frappe.utils.now")
    ```

The patched function checks per call whether the current site has conductor installed; sites without conductor fall back to the original `frappe.enqueue` and stay on RQ. The `[7/9]` `bench conductor doctor` check verifies the patch installed correctly.

This flag does **not** catch Frappe's `Scheduled Job Type` rows — those are dispatched by Frappe's scheduler from a code path that imports `enqueue` directly, bypassing the patched binding. To route those rows, see [`how-to-route-frappe-scheduled-jobs.md`](how-to-route-frappe-scheduled-jobs.md).

---

## If something went wrong

- **`ImportError: No module named 'conductor'` from the worker** — Conductor is not installed on the site you are dispatching to. Run `bench --site SITE install-app conductor` and restart the worker.
- **`enqueue` returns a `job_id` but the job never runs** — no worker is consuming the queue. Run `bench --site SITE conductor worker --queue <name>` and check `bench --site SITE conductor depth` for the queue's stream length.
- **Two `enqueue` calls with the same `idempotency_key` return different ids** — the keys are not byte-identical (whitespace, case), or the TTL elapsed between calls. Print the keys before dispatch and confirm they match exactly.
- **`frappe.ValidationError: Queue 'default' is disabled`** — open `Conductor Queue` in the Desk and re-enable the row, or pass an enabled `queue=` argument.
- **Override added but old code still goes to RQ** — those code paths are in-process, and `conductor_intercept_frappe_enqueue` is not set in `common_site_config.json`. See Procedure 3.
- **`Scheduled Job Type` rows still hit RQ even with the intercept flag set** — those bypass `frappe.enqueue`. Use `conductor_take_over_frappe_scheduler` instead — see [`how-to-route-frappe-scheduled-jobs.md`](how-to-route-frappe-scheduled-jobs.md).
