# Define workflows

This page covers Conductor's DAG workflows: defining one as a Python class, adding compensations, triggering and inspecting runs, and understanding the partial-rollback rule.

You succeed when `conductor.run_workflow(name, ...)` returns a `run_id`, every forward step runs in topological order, and a failure mid-run drives compensations in reverse-topological order.

---

## Procedure 1 — Define a DAG

A workflow is a class decorated with `@workflow(...)`. Each `Step` is a class attribute; the step name must equal a method name on the class.

1. Pick a place that loads at app startup. The Conductor worker imports your client app on boot, so a module imported by your `hooks.py` is reliable. Avoid putting workflows in lazy-loaded modules.

2. Define the class:

    ```python
    import conductor
    from conductor.workflow import workflow, Step

    @workflow(name="OrderFulfillment", queue="default")
    class OrderFulfillment:
        reserve_step = Step("reserve",  compensation="release")
        charge_step  = Step("charge",   depends_on=("reserve",), compensation="refund")
        notify_step  = Step("notify",   depends_on=("reserve",))
        receipt_step = Step("receipt",  depends_on=("charge", "notify"))

        def reserve(self, *, order_id):
            ...

        def release(self, *, order_id):
            ...

        def charge(self, *, order_id):
            ...

        def refund(self, *, order_id):
            ...

        def notify(self, *, order_id):
            ...

        def receipt(self, *, order_id):
            ...
    ```

3. Confirm the workflow registered:

    ```bash
    bench --site frappe.localhost conductor workflow list
    ```

    `OrderFulfillment` appears with `V=1`. The `@workflow` decorator validates the topology at decoration time — see [`reference-python-api.md`](reference-python-api.md#conductorworkflowworkflow) for the full validation list.

The decorator also bumps the row's `version` whenever the topology changes (for example, you add a step), so a long-running workflow run keeps the topology it started with even after a redeploy.

---

## Procedure 2 — Add a compensation

A compensation is a method that undoes a forward step. It runs only when the run later fails and Conductor walks back through completed steps.

1. Pick a step that has an externally-visible side effect (booking a slot, charging a card, calling a partner API).

2. Add the inverse method to the class. Same kwargs as the forward step. Make it idempotent — compensations can run twice under at-least-once delivery.

3. Reference the compensation method by name on the `Step`:

    ```python
    charge_step = Step("charge", depends_on=("reserve",), compensation="refund")
    ```

4. A step without a `compensation=` argument gets a no-op `COMPENSATED` row when the run fails after it completes. This is the right choice for read-only steps.

The advancer dispatches compensations in **reverse-topological order**, so a downstream step's compensation runs before an upstream step's. A compensation runs as a normal Conductor Job — it inherits retry, timeout, idempotency, and DLQ semantics from the step's queue defaults.

---

## Procedure 3 — Trigger a run, check status, cancel

Trigger from Python:

```python
import conductor

run_id = conductor.run_workflow(
    "OrderFulfillment",
    order_id=42,
    idempotency_key="ord-42",
)
```

Or from the CLI:

```bash
bench --site SITE conductor workflow run OrderFulfillment \
  --kwargs '{"order_id": 42}' --idempotency-key ord-42
```

Check status:

```bash
bench --site SITE conductor workflow status <run_id>
```

The output prints the run-level status (`PENDING`, `RUNNING`, `COMPENSATING`, `SUCCEEDED`, `FAILED`, `CANCELLED`) plus a per-step table with each step's status and the `Conductor Job` id that ran it.

Cancel:

```bash
bench --site SITE conductor workflow cancel <run_id>
```

Cancel sets the run to `CANCELLED`, marks not-yet-started steps `SKIPPED`, and soft-cancels in-flight step jobs. **It does not run compensations.** If you need rollback for steps that already completed, let the run fail naturally (so the failure path triggers compensations) or run compensation logic from operator tooling.

The dashboard's **Workflows** tab shows the same data with a Mermaid DAG visualization and per-step color-coded status.

---

## Procedure 4 — Read partial-rollback semantics

The compensation path is best-effort. When a compensation step itself terminally fails, Conductor stops the rollback and lands the run `FAILED`. **Earlier completed steps are not compensated.**

This is intentional — cascading rollbacks across distributed services can leave inconsistent partial state, and Conductor would rather hand the situation to an operator than make it worse.

When this happens:

1. The dashboard's run detail shows the failed compensation in red.
2. The `Conductor Workflow Run.last_error` field names the failed compensation step.
3. Operators decide whether to retry the compensation manually (re-enqueue the relevant `Conductor Job`) or accept the partial state.

If a step's side effect is irreversible (sending an email, posting to a partner API), prefer making the forward step itself idempotent at the side-effect boundary so that re-running it on retry is safe. Compensations are best for reversible side effects (database writes, internal state).

The full rule and rationale live in [`explanation-reliability.md`](explanation-reliability.md#workflow-compensations).

---

## If something went wrong

- **`WorkflowNotFoundError: workflow not registered`** — the module that defines the class is not imported by the worker process. Add an explicit import to your client app's `hooks.py` or to a module that `hooks.py` imports.
- **`WorkflowDefinitionError: workflow ... has a dependency cycle`** — a `depends_on` chain forms a cycle. The error message names the cycle path. Remove the offending edge.
- **`WorkflowDefinitionError: step 'X' has no method named 'X'`** — the `Step` name does not match a method on the class. The first arg to `Step(...)` is **both** the step name and the method name; they cannot differ.
- **`WorkflowDefinitionError: compensation method 'Y' for step 'X' not found`** — the `compensation=` arg names a method that does not exist. Check spelling and class membership.
- **A compensation never ran** — that step had not yet completed when the failure occurred. The advancer only compensates **completed** steps; pending and ready steps go to `SKIPPED`.
- **A compensation ran twice** — at-least-once delivery applies to compensations too. Make compensations idempotent.
- **Run sits in `PENDING` forever** — the worker is not consuming the workflow's queue. Check `bench --site SITE conductor depth` and start a worker for that queue.
