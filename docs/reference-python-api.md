# Python API reference

Reference for the Conductor public Python API. Import from `conductor` (top-level re-exports) or `conductor.workflow`. Internal modules (`conductor.dispatcher`, `conductor.streams`, `conductor.worker`, etc.) are not part of the public API; their signatures may change between releases.

All examples assume Conductor is installed on a Frappe site and code runs inside `bench --site SITE console` or inside a Frappe job/request context.

---

## Enqueue and cancel

### `conductor.enqueue`

```python
def enqueue(
    method: str,
    *,
    queue: str | None = None,
    timeout: int | None = None,
    max_attempts: int | None = None,
    idempotency_key: str | None = None,
    **kwargs,
) -> str
```

Enqueue a job onto a Conductor queue. Returns the new `job_id` (a UUID string), or — when `idempotency_key` is supplied and a job with that key is still in flight — the existing `job_id`.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `method` | `str` | required | Dotted path to the function to run (`"myapp.tasks.send_email"`). Resolved via `frappe.get_attr(...)`. |
| `queue` | `str` | from `@conductor.job` decorator, else `"default"` | Queue name. Must be an enabled `Conductor Queue` row. |
| `timeout` | `int` | from decorator, else queue default | Per-job timeout in seconds. |
| `max_attempts` | `int` | from decorator, else queue default | Cap on attempts. Overrides the decorator's `RetryPolicy.max_attempts` only. |
| `idempotency_key` | `str` | from decorator's `idempotency_key` callable, else `""` | Dedup key. Two `enqueue` calls with the same key, while the first job is still tracked, return the same `job_id`. |
| `**kwargs` | any | — | Passed to the job function. Must be msgpack-serializable. |

**Returns** — a UUID-shaped `job_id`.

**Raises** — `frappe.ValidationError` if the resolved queue is disabled. Re-raises any Redis exception encountered after the `Conductor Job` row is inserted; the row is marked `DISPATCH_FAILED` before the exception propagates.

```python
import conductor

job_id = conductor.enqueue(
    "myapp.tasks.send_email",
    queue="default",
    idempotency_key="invoice:INV-001:reminder:1",
    invoice="INV-001",
)
```

### `conductor.cancel`

```python
def cancel(job_id: str) -> bool
```

Soft-cancel a job. Returns `True` if the cancellation transitioned the job's status to `CANCELLED`, `False` if the job was already terminal or unknown.

Behavior depends on the job's current status:

- `QUEUED` — best-effort `XDEL` from the queue stream.
- `SCHEDULED_RETRY` — best-effort `ZREM` from the scheduled-retry set.
- `RUNNING` — the cancel-poller flips the worker's cancel flag within ~1 second; the running function observes via `conductor.context.should_cancel()`. The job may still finish if the body does not check.

```python
ok = conductor.cancel(job_id)
```

---

## Job decoration and context

### `conductor.job`

```python
def job(
    *,
    queue: str | None = None,
    timeout: int | None = None,
    max_attempts: int | None = None,
    backoff: str | None = None,           # "exponential" | "linear" | "fixed"
    base_delay_seconds: int | None = None,
    max_delay_seconds: int | None = None,
    jitter: str | None = None,            # "none" | "full" | "equal"
    idempotency_key: Callable[..., str] | None = None,
    retry_on: tuple[type[BaseException], ...] | None = None,
    no_retry_on: tuple[type[BaseException], ...] | None = None,
)
```

Decorator that attaches declarative defaults to a function. The dispatcher reads the metadata at `enqueue` time and stamps it into the job message. In-flight retries keep their dispatch-time policy across redeploys.

Per-call `enqueue` arguments override the decorator. The decorator overrides the queue's defaults.

```python
import conductor

def _idem_for_send_email(*, invoice, **_):
    return f"invoice:{invoice}:email"

@conductor.job(
    queue="default",
    timeout=60,
    max_attempts=5,
    backoff="exponential",
    idempotency_key=_idem_for_send_email,
)
def send_email(*, invoice, recipient):
    ...
```

### `conductor.RetryPolicy`

```python
@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    backoff: Literal["exponential", "linear", "fixed"] = "exponential"
    base_delay_seconds: int = 2
    max_delay_seconds: int = 600
    jitter: Literal["none", "full", "equal"] = "full"
    retry_on: tuple[type[BaseException], ...] = (Exception,)
    no_retry_on: tuple[type[BaseException], ...] = ()
```

Declarative retry configuration. Built indirectly by passing parameters to `@conductor.job`; rarely constructed by hand. The dispatcher stamps a `RetryPolicy` into every job message so retries stay pinned to their dispatch-time policy.

Two methods are useful from inside Conductor itself; user code does not normally call them:

- `compute_next_delay(attempt: int) -> float` — seconds to wait before retry `attempt + 1`.
- `should_retry(exc: BaseException, attempt: int) -> bool` — true if the exception matches `retry_on`, does not match `no_retry_on`, and `attempt < max_attempts`.

### `conductor.context`

```python
context.job_id: str | None
context.attempt: int | None
context.deadline: datetime | None
context.should_cancel() -> bool
```

Thread-local context exposed inside a job body. Lets a job inspect its own `job_id`, current attempt number, deadline, and whether a cancellation has been requested.

```python
import conductor

@conductor.job()
def long_running_export(*, report_id):
    for chunk in load_chunks(report_id):
        if conductor.context.should_cancel():
            return  # exit cleanly so cancel takes effect
        write(chunk)
```

The watchdog also flips `should_cancel()` automatically when the deadline elapses.

---

## Workflows

### `conductor.workflow.workflow`

```python
def workflow(*, name: str, queue: str)
```

Class decorator that registers a workflow definition. Validates at decoration time:

- every `Step` references an existing method on the class
- every step's `compensation` method (when set) exists on the class
- every entry in `depends_on` names a declared step
- no two `Step` attributes share the same name
- the workflow `name` is not already registered
- the dependency graph is acyclic

Stores `__conductor_workflow_name__`, `__conductor_workflow_queue__`, and `__conductor_workflow_steps__` on the class.

**Raises** — `WorkflowDefinitionError` for any of the conditions above.

### `conductor.workflow.Step`

```python
@dataclass(frozen=True)
class Step:
    name: str
    depends_on: tuple[str, ...] = ()
    compensation: str | None = None
```

A node in a workflow DAG.

| Field | Meaning |
|---|---|
| `name` | The step name **and** the name of the method on the class that runs it. |
| `depends_on` | Step names that must succeed before this step runs. Empty tuple = root step. |
| `compensation` | Method name to invoke when an in-flight failure rolls this step back. Optional. |

```python
from conductor.workflow import workflow, Step

@workflow(name="OrderFulfillment", queue="default")
class OrderFulfillment:
    reserve_step = Step("reserve", compensation="release")
    charge_step  = Step("charge",  depends_on=("reserve",), compensation="refund")
    notify_step  = Step("notify",  depends_on=("reserve",))
    receipt_step = Step("receipt", depends_on=("charge", "notify"))

    def reserve(self, *, order_id): ...
    def release(self, *, order_id): ...
    def charge(self,  *, order_id): ...
    def refund(self,  *, order_id): ...
    def notify(self,  *, order_id): ...
    def receipt(self, *, order_id): ...
```

### `conductor.run_workflow`

```python
def run_workflow(
    name: str,
    *,
    idempotency_key: str | None = None,
    **kwargs,
) -> str
```

Trigger a workflow run. Returns the new `run_id`, or — when `idempotency_key` is supplied and a previous run with that key still exists in Redis — the existing `run_id`.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `name` | `str` | required | Workflow name registered via `@workflow(name=...)`. |
| `idempotency_key` | `str` | `None` | Dedup key. TTL defaults to 24h, configurable via `conductor.wfidem_ttl_seconds`. |
| `**kwargs` | any | — | Passed to every step's method as keyword arguments. Must be msgpack-serializable. |

**Returns** — a `run_id` (10-char hash).

**Raises** — `WorkflowNotFoundError` if `name` is not in the in-process registry.

```python
import conductor

run_id = conductor.run_workflow(
    "OrderFulfillment",
    order_id=42,
    idempotency_key="ord-42",
)
```

### `conductor.cancel_workflow_run`

```python
def cancel_workflow_run(run_id: str, *, user: str | None = None) -> None
```

Best-effort cancel. Marks the run `CANCELLED`, sets pending and ready forward steps to `SKIPPED`, and calls `conductor.cancel(...)` for any running step jobs. Idempotent — calling on an already-terminal run is a no-op.

**Does not** run compensations for steps that already completed. To roll back a partial run, let it fail naturally (so the failure path triggers compensations), or run compensation logic by hand from operator tooling.

### `conductor.workflow.WorkflowDefinitionError`

Raised at decoration time when a `@workflow(...)` class is malformed (see the validation list above).

### `conductor.workflow.WorkflowNotFoundError`

Raised by `run_workflow(name)` when `name` is not in the registry. Typically means the module that defines the workflow class was not imported by the worker process — register the import in your app's `hooks.py`.

---

## Frappe compatibility shim

### `conductor.frappe_compat.enqueue`

```python
def enqueue(method: str, queue: str = "default", timeout: int | None = None, **kwargs) -> str
```

A `frappe.enqueue`-shaped wrapper around `conductor.enqueue`. Used as the override target in a client app's `hooks.py`:

```python
override_whitelisted_methods = {
    "frappe.enqueue": "conductor.frappe_compat.enqueue",
}
```

**Caveat — read carefully.** The override only intercepts HTTP calls to `/api/method/frappe.enqueue`. Intra-process Python calls (`frappe.enqueue(...)` from inside another job, hook, or background task) **bypass the override** and go to Frappe RQ. To route every enqueue path to Conductor, either call `conductor.enqueue(...)` directly in your code, or migrate intra-process call sites one by one.

---

## See also

- [`reference-cli.md`](reference-cli.md) — CLI equivalents for `enqueue`, `cancel`, `run_workflow`, `cancel_workflow_run`.
- [`explanation-reliability.md`](explanation-reliability.md) — what idempotency keys, retries, and cancellation actually protect against.
- [`how-to-enqueue-jobs.md`](how-to-enqueue-jobs.md) and [`how-to-define-workflows.md`](how-to-define-workflows.md) — task-oriented walkthroughs.
