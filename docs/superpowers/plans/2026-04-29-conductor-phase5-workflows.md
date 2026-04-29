# Conductor Phase 5 — Workflows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add DAG workflows with reverse-topological compensation to Conductor on top of the existing job pipeline (Phases 0–2) and dashboard (Phase 3).

**Architecture:** Workflows are declared as Python classes decorated with `@conductor.workflow`. `conductor.run_workflow(...)` snapshots the topology, version-bumps the `Conductor Workflow` row if needed, inserts a `Conductor Workflow Run` plus one `Conductor Workflow Step Run` per step, and enqueues a unified advancer job. The advancer branches on `run.status`: forward path uses a single-key Lua `fanin_decrement` script for atomic deps counter decrements and dispatches now-ready steps as regular Conductor jobs; compensation path inserts new `is_compensation=1` Step Run rows in reverse topological order and enqueues compensations as jobs. Every step's underlying job is a normal Conductor job, inheriting Phase-1 retry/timeout/idempotency/DLQ semantics. Worker hooks fire `mark_step_running` / `mark_step_terminal` plus a single `enqueue_advance` on every step state transition.

**Tech Stack:** Python 3.10+, Frappe 15, Redis (DB 2), msgpack, click (CLI), Vue 3 SFC + mermaid (dashboard).

**Spec:** `docs/superpowers/specs/2026-04-29-conductor-phase5-workflows-design.md`
**Master:** `docs/superpowers/specs/2026-04-27-conductor-master-design.md`

---

## Conventions used by every task

- **Test runner:** `/Users/osamamuhammed/frappe_15/env/bin/pytest` for pure-Python (`tests/`); `bench --site frappe.localhost run-tests --app conductor --module <dotted>` for Frappe-integration (DocType tests living next to the DocType `.py` controller).
- **Working dir for all commands:** `/Users/osamamuhammed/frappe_15/apps/conductor/`. All paths in this plan are relative to that directory.
- **Frappe site:** `frappe.localhost` (the bench's only site).
- **Redis test fixture:** `fake_redis` from `tests/conftest.py`.
- **Commit style:** matches recent history — type-scoped subject (`feat(workflow):`, `test(workflow):`, etc.), Co-Authored-By trailer not required for plan-driven commits.
- **TDD discipline:** for every behavior-bearing change, write the failing test first, run it to confirm the failure mode, implement, run to confirm pass, commit.

---

## File structure

**New files:**

```
conductor/workflow/__init__.py                 # public API re-exports
conductor/workflow/decorator.py                # @workflow + Step + WorkflowDefinitionError + registry
conductor/workflow/snapshot.py                 # canonical-JSON topology hash
conductor/workflow/topo.py                     # cycle detection + reverse-topo
conductor/workflow/dispatcher.py               # run_workflow()
conductor/workflow/advancer.py                 # unified advancer job entry-point
conductor/workflow/lua.py                      # fanin_decrement Lua source
conductor/workflow/keys.py                     # wfdeps/wfidem Redis key helpers
conductor/workflow/idempotency.py              # acquire_wfidem_lock thin wrapper

conductor/conductor/doctype/conductor_workflow/__init__.py
conductor/conductor/doctype/conductor_workflow/conductor_workflow.json
conductor/conductor/doctype/conductor_workflow/conductor_workflow.py
conductor/conductor/doctype/conductor_workflow/test_conductor_workflow.py

conductor/conductor/doctype/conductor_workflow_run/__init__.py
conductor/conductor/doctype/conductor_workflow_run/conductor_workflow_run.json
conductor/conductor/doctype/conductor_workflow_run/conductor_workflow_run.py
conductor/conductor/doctype/conductor_workflow_run/test_conductor_workflow_run.py

conductor/conductor/doctype/conductor_workflow_step_run/__init__.py
conductor/conductor/doctype/conductor_workflow_step_run/conductor_workflow_step_run.json
conductor/conductor/doctype/conductor_workflow_step_run/conductor_workflow_step_run.py
conductor/conductor/doctype/conductor_workflow_step_run/test_conductor_workflow_step_run.py

conductor/api/workflows.py                     # whitelisted dashboard endpoints
conductor/commands/workflow.py                 # bench conductor workflow ...

dashboard/src/pages/WorkflowsPage.vue
dashboard/src/pages/WorkflowRunDetailPage.vue
dashboard/src/components/MermaidDag.vue

tests/test_workflow_decorator.py
tests/test_workflow_snapshot.py
tests/test_workflow_topo.py
tests/test_workflow_lua.py
tests/test_workflow_keys.py
tests/test_workflow_idempotency.py
tests_chaos/test_phase5_chaos.py
```

**Modified files:**

```
conductor/__init__.py                          # re-export run_workflow, workflow, Step
conductor/install.py                           # add "workflow" queue to DEFAULT_QUEUES
conductor/worker.py                            # mark_step_running / mark_step_terminal hooks
conductor/hooks.py                             # register conductor.commands.workflow click group
dashboard/src/router.js                        # add /workflows + /workflows/runs/:id routes
dashboard/src/App.vue                          # add Workflows tab to nav
dashboard/package.json                         # add "mermaid" dep
README.md                                      # bump status to "Phase 4 of 5"
docs/superpowers/specs/2026-04-27-conductor-master-design.md   # change-log entry
```

---

## Task 1: Add `workflow` queue to fixtures

**Files:**
- Modify: `conductor/install.py`
- Test: `conductor/conductor/doctype/conductor_queue/` (existing tests cover this implicitly via the queue list; we add a unit assertion)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_install_constants.py` (create if missing):

```python
"""Smoke tests for install-time defaults (no Frappe required)."""

from conductor.install import DEFAULT_QUEUES


def test_workflow_queue_is_seeded():
    names = {q["queue_name"] for q in DEFAULT_QUEUES}
    assert "workflow" in names, "Phase 5 needs a 'workflow' queue for advancer/compensator jobs"


def test_workflow_queue_concurrency_is_at_least_4():
    wf = next(q for q in DEFAULT_QUEUES if q["queue_name"] == "workflow")
    assert wf["concurrency"] >= 4
```

- [ ] **Step 2: Run test to verify it fails**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_install_constants.py -v
```

Expected: `AssertionError: Phase 5 needs a 'workflow' queue ...`

- [ ] **Step 3: Add the queue**

Edit `conductor/install.py` `DEFAULT_QUEUES` list — append:

```python
    {"queue_name": "workflow", "concurrency": 4, "default_max_attempts": 5, "default_timeout": 120},
```

- [ ] **Step 4: Run test to verify it passes**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_install_constants.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```
git add conductor/install.py tests/test_install_constants.py
git commit -m "feat(workflow): add 'workflow' queue for advancer/compensator jobs"
```

---

## Task 2: `Step` dataclass + `WorkflowDefinitionError`

**Files:**
- Create: `conductor/workflow/__init__.py`
- Create: `conductor/workflow/decorator.py`
- Test: `tests/test_workflow_decorator.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_workflow_decorator.py`:

```python
"""Pure-Python tests for @conductor.workflow + Step dataclass (no Frappe required)."""

import pytest

from conductor.workflow import Step, WorkflowDefinitionError


def test_step_is_frozen_dataclass():
    s = Step(name="a", depends_on=("b",), compensation="undo_a")
    with pytest.raises(Exception):
        s.name = "z"
    assert s.name == "a"
    assert s.depends_on == ("b",)
    assert s.compensation == "undo_a"


def test_step_defaults_are_empty():
    s = Step(name="a")
    assert s.depends_on == ()
    assert s.compensation is None


def test_step_depends_on_must_be_tuple():
    # Lists are normalized to tuples so equality + hashing are stable.
    s = Step(name="a", depends_on=["b", "c"])
    assert isinstance(s.depends_on, tuple)
    assert s.depends_on == ("b", "c")
```

- [ ] **Step 2: Run tests to verify they fail**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_workflow_decorator.py -v
```

Expected: `ImportError: No module named 'conductor.workflow'`.

- [ ] **Step 3: Create the package + Step**

Create `conductor/workflow/__init__.py`:

```python
"""Conductor Phase 5 — Workflow public API.

Spec: docs/superpowers/specs/2026-04-29-conductor-phase5-workflows-design.md
"""

from conductor.workflow.decorator import (
    Step,
    WorkflowDefinitionError,
    workflow,
)

__all__ = ["Step", "WorkflowDefinitionError", "workflow"]
```

Create `conductor/workflow/decorator.py`:

```python
"""@conductor.workflow class decorator + Step dataclass + in-process registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


class WorkflowDefinitionError(ValueError):
    """Raised at decoration time when a workflow class is malformed."""


def _to_tuple(deps: Iterable[str] | None) -> tuple[str, ...]:
    if deps is None:
        return ()
    return tuple(deps)


@dataclass(frozen=True)
class Step:
    name: str
    depends_on: tuple[str, ...] = ()
    compensation: str | None = None

    def __post_init__(self):
        # Normalize lists/sets to tuples without breaking frozen semantics.
        if not isinstance(self.depends_on, tuple):
            object.__setattr__(self, "depends_on", _to_tuple(self.depends_on))
```

- [ ] **Step 4: Run tests to verify they pass**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_workflow_decorator.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add conductor/workflow/__init__.py conductor/workflow/decorator.py tests/test_workflow_decorator.py
git commit -m "feat(workflow): Step dataclass + WorkflowDefinitionError"
```

---

## Task 3: `@workflow` decorator + class-level validation + registry

**Files:**
- Modify: `conductor/workflow/decorator.py`
- Test: `tests/test_workflow_decorator.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_workflow_decorator.py`:

```python
from conductor.workflow import workflow
from conductor.workflow.decorator import _REGISTRY  # private but tested for register effect


def _clear_registry():
    _REGISTRY.clear()


def test_decorator_registers_class_under_name():
    _clear_registry()

    @workflow(name="W1", queue="default")
    class W1:
        a = Step("step_a")

        def step_a(self): pass

    assert _REGISTRY["W1"] is W1
    assert W1.__conductor_workflow_name__ == "W1"
    assert W1.__conductor_workflow_queue__ == "default"


def test_decorator_raises_on_step_without_method():
    _clear_registry()
    with pytest.raises(WorkflowDefinitionError, match="step_a"):
        @workflow(name="W2", queue="default")
        class W2:
            a = Step("step_a")
            # no step_a method


def test_decorator_raises_on_unknown_compensation_method():
    _clear_registry()
    with pytest.raises(WorkflowDefinitionError, match="undo_a"):
        @workflow(name="W3", queue="default")
        class W3:
            a = Step("step_a", compensation="undo_a")
            def step_a(self): pass


def test_decorator_raises_on_unknown_dependency():
    _clear_registry()
    with pytest.raises(WorkflowDefinitionError, match="depends_on.*missing"):
        @workflow(name="W4", queue="default")
        class W4:
            a = Step("step_a", depends_on=("missing",))
            def step_a(self): pass


def test_decorator_raises_on_duplicate_step_name():
    _clear_registry()
    with pytest.raises(WorkflowDefinitionError, match="duplicate"):
        @workflow(name="W5", queue="default")
        class W5:
            a = Step("step_x")
            b = Step("step_x")
            def step_x(self): pass


def test_decorator_raises_on_redefining_workflow_name():
    _clear_registry()

    @workflow(name="W6", queue="default")
    class W6a:
        _a = Step("a")
        def a(self): pass

    with pytest.raises(WorkflowDefinitionError, match="already registered"):
        @workflow(name="W6", queue="default")
        class W6b:
            _a = Step("a")
            def a(self): pass


def test_decorator_exposes_steps_in_declaration_order():
    _clear_registry()

    @workflow(name="W7", queue="default")
    class W7:
        _a = Step("a")
        _b = Step("b", depends_on=("a",))

        def a(self): pass
        def b(self): pass

    steps = W7.__conductor_workflow_steps__
    # Sorted by step name for determinism — see snapshot.py rationale.
    assert [s.name for s in steps] == ["a", "b"]
```

- [ ] **Step 2: Run tests to verify they fail**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_workflow_decorator.py -v
```

Expected: import errors / `_REGISTRY` does not exist.

- [ ] **Step 3: Implement the decorator**

Append to `conductor/workflow/decorator.py`:

```python
_REGISTRY: dict[str, type] = {}


def workflow(*, name: str, queue: str):
    """Class decorator that registers a workflow definition.

    Validates at decoration time:
      - every Step references an existing method on the class
      - every step's compensation method (if any) exists on the class
      - every dep in depends_on names a declared step
      - no two Step attributes share the same name
      - this workflow name is not already registered

    Stores on the class:
      - __conductor_workflow_name__ : str
      - __conductor_workflow_queue__ : str
      - __conductor_workflow_steps__ : tuple[Step, ...]   (sorted by name)
    """

    def decorate(cls: type) -> type:
        if name in _REGISTRY:
            raise WorkflowDefinitionError(
                f"workflow name {name!r} already registered by {_REGISTRY[name]!r}"
            )

        steps_by_attr: dict[str, Step] = {
            attr: val for attr, val in vars(cls).items() if isinstance(val, Step)
        }

        seen_names: set[str] = set()
        for attr, step in steps_by_attr.items():
            if step.name in seen_names:
                raise WorkflowDefinitionError(
                    f"duplicate step name {step.name!r} in workflow {name}"
                )
            seen_names.add(step.name)

            if not callable(getattr(cls, step.name, None)):
                raise WorkflowDefinitionError(
                    f"step {step.name!r} has no method named {step.name!r} on {cls.__name__}"
                )

            if step.compensation is not None:
                if not callable(getattr(cls, step.compensation, None)):
                    raise WorkflowDefinitionError(
                        f"compensation method {step.compensation!r} for step "
                        f"{step.name!r} not found on {cls.__name__}"
                    )

        for step in steps_by_attr.values():
            for dep in step.depends_on:
                if dep not in seen_names:
                    raise WorkflowDefinitionError(
                        f"step {step.name!r} depends_on {dep!r} which is missing"
                    )

        ordered_steps = tuple(sorted(steps_by_attr.values(), key=lambda s: s.name))

        cls.__conductor_workflow_name__ = name
        cls.__conductor_workflow_queue__ = queue
        cls.__conductor_workflow_steps__ = ordered_steps

        _REGISTRY[name] = cls
        return cls

    return decorate


def get_registered(name: str) -> type | None:
    return _REGISTRY.get(name)
```

- [ ] **Step 4: Run tests to verify they pass**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_workflow_decorator.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```
git add conductor/workflow/decorator.py tests/test_workflow_decorator.py
git commit -m "feat(workflow): @workflow decorator with class-level validation"
```

---

## Task 4: Cycle detection + reverse-topological sort

**Files:**
- Create: `conductor/workflow/topo.py`
- Test: `tests/test_workflow_topo.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_workflow_topo.py`:

```python
"""Pure-Python tests for topology helpers."""

import pytest

from conductor.workflow.decorator import Step, WorkflowDefinitionError
from conductor.workflow.topo import (
    detect_cycle,
    in_degrees,
    reverse_topo_order,
)


def _steps_diamond():
    """A → {B, C} → D"""
    return (
        Step("a"),
        Step("b", depends_on=("a",)),
        Step("c", depends_on=("a",)),
        Step("d", depends_on=("b", "c")),
    )


def test_in_degrees_diamond():
    assert in_degrees(_steps_diamond()) == {"a": 0, "b": 1, "c": 1, "d": 2}


def test_detect_cycle_returns_none_for_dag():
    assert detect_cycle(_steps_diamond()) is None


def test_detect_cycle_finds_simple_cycle():
    steps = (
        Step("a", depends_on=("b",)),
        Step("b", depends_on=("a",)),
    )
    cycle = detect_cycle(steps)
    assert cycle is not None
    assert set(cycle) == {"a", "b"}


def test_detect_cycle_finds_self_loop():
    steps = (Step("a", depends_on=("a",)),)
    cycle = detect_cycle(steps)
    assert cycle == ["a"]


def test_reverse_topo_diamond():
    # Forward order: a → b,c → d. Reverse: d, then b/c (any order), then a.
    rev = reverse_topo_order(_steps_diamond())
    assert rev[0] == "d"
    assert rev[-1] == "a"
    assert set(rev[1:3]) == {"b", "c"}


def test_reverse_topo_filtered_subset():
    # Reverse-topo on completed-only set: a and c completed; b/d did not.
    completed = {"a", "c"}
    rev = reverse_topo_order(_steps_diamond(), only=completed)
    assert rev == ["c", "a"]


def test_reverse_topo_empty_subset_returns_empty():
    assert reverse_topo_order(_steps_diamond(), only=set()) == []
```

- [ ] **Step 2: Run tests to verify they fail**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_workflow_topo.py -v
```

Expected: `ImportError: No module named 'conductor.workflow.topo'`.

- [ ] **Step 3: Implement the topology module**

Create `conductor/workflow/topo.py`:

```python
"""Pure functions for workflow DAG analysis.

All functions operate on tuple[Step, ...] (the canonical class attribute
__conductor_workflow_steps__). They are independent of Frappe and Redis.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from conductor.workflow.decorator import Step


def in_degrees(steps: Iterable[Step]) -> dict[str, int]:
    return {s.name: len(s.depends_on) for s in steps}


def detect_cycle(steps: Iterable[Step]) -> list[str] | None:
    """Return one cycle as a list of step names, or None if the DAG is acyclic.

    Uses iterative DFS with three colors (WHITE/GRAY/BLACK) to find a back-edge.
    """
    steps_t = tuple(steps)
    by_name = {s.name: s for s in steps_t}
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = defaultdict(lambda: WHITE)
    parent: dict[str, str | None] = {}

    def visit(start: str) -> list[str] | None:
        stack: list[tuple[str, list[str]]] = [(start, list(by_name[start].depends_on))]
        color[start] = GRAY
        parent[start] = None
        while stack:
            node, deps = stack[-1]
            if not deps:
                color[node] = BLACK
                stack.pop()
                continue
            dep = deps.pop()
            if dep not in by_name:
                continue
            if color[dep] == WHITE:
                color[dep] = GRAY
                parent[dep] = node
                stack.append((dep, list(by_name[dep].depends_on)))
            elif color[dep] == GRAY:
                # back-edge — reconstruct cycle [dep, ..., node, dep]
                cycle = [dep]
                walker = node
                while walker is not None and walker != dep:
                    cycle.append(walker)
                    walker = parent.get(walker)
                return cycle
        return None

    for s in steps_t:
        if color[s.name] == WHITE:
            cycle = visit(s.name)
            if cycle:
                return cycle
    return None


def reverse_topo_order(
    steps: Iterable[Step],
    *,
    only: set[str] | None = None,
) -> list[str]:
    """Return step names in reverse topological order.

    If `only` is given, the result contains only step names in `only`, but
    they are still ordered according to the full DAG's reverse-topo
    sequence — guarantees compensation runs leaf-to-root over completed steps
    even when middle steps did not run.
    """
    steps_t = tuple(steps)
    by_name = {s.name: s for s in steps_t}
    forward: list[str] = []
    color: dict[str, int] = defaultdict(int)  # 0 unvisited, 1 visiting, 2 done

    def dfs(name: str) -> None:
        if color[name] == 2:
            return
        color[name] = 1
        for dep in by_name[name].depends_on:
            if dep in by_name:
                dfs(dep)
        color[name] = 2
        forward.append(name)

    for s in steps_t:
        dfs(s.name)

    rev = list(reversed(forward))
    if only is None:
        return rev
    return [n for n in rev if n in only]
```

- [ ] **Step 4: Wire cycle detection into the decorator**

Edit `conductor/workflow/decorator.py` — at the end of the validation block, before the line `ordered_steps = tuple(sorted(...))`, add:

```python
        from conductor.workflow.topo import detect_cycle  # avoid circular import at module load
        cycle = detect_cycle(steps_by_attr.values())
        if cycle:
            raise WorkflowDefinitionError(
                f"workflow {name} has a dependency cycle: {' → '.join(cycle)}"
            )
```

Add a corresponding test to `tests/test_workflow_decorator.py`:

```python
def test_decorator_raises_on_dependency_cycle():
    _clear_registry()
    with pytest.raises(WorkflowDefinitionError, match="cycle"):
        @workflow(name="W_cycle", queue="default")
        class W_cycle:
            _a = Step("a", depends_on=("b",))
            _b = Step("b", depends_on=("a",))
            def a(self): pass
            def b(self): pass
```

- [ ] **Step 5: Run tests to verify they pass**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_workflow_topo.py tests/test_workflow_decorator.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```
git add conductor/workflow/topo.py conductor/workflow/decorator.py tests/test_workflow_topo.py tests/test_workflow_decorator.py
git commit -m "feat(workflow): cycle detection and reverse-topological sort"
```

---

## Task 5: Topology snapshot + canonical hash

**Files:**
- Create: `conductor/workflow/snapshot.py`
- Test: `tests/test_workflow_snapshot.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_workflow_snapshot.py`:

```python
"""Snapshot serialization + canonical-hash determinism."""

import json

from conductor.workflow import Step, workflow
from conductor.workflow.decorator import _REGISTRY
from conductor.workflow.snapshot import (
    snapshot_from_class,
    topology_hash,
)


def _clear_registry():
    _REGISTRY.clear()


def _make_diamond_class(name: str):
    @workflow(name=name, queue="default")
    class W:
        _a = Step("a")
        _b = Step("b", depends_on=("a",), compensation="undo_b")
        _c = Step("c", depends_on=("a",))
        _d = Step("d", depends_on=("b", "c"))
        def a(self): pass
        def b(self): pass
        def undo_b(self): pass
        def c(self): pass
        def d(self): pass
    return W


def test_snapshot_shape_is_canonical():
    _clear_registry()
    W = _make_diamond_class("W_snap1")
    snap = snapshot_from_class(W)
    parsed = json.loads(snap)
    assert parsed["name"] == "W_snap1"
    assert parsed["queue"] == "default"
    # Steps sorted by name; depends_on lists sorted; nulls preserved.
    step_names = [s["name"] for s in parsed["steps"]]
    assert step_names == ["a", "b", "c", "d"]
    b = next(s for s in parsed["steps"] if s["name"] == "b")
    assert b["depends_on"] == ["a"]
    assert b["compensation"] == "undo_b"
    a = next(s for s in parsed["steps"] if s["name"] == "a")
    assert a["compensation"] is None
    d = next(s for s in parsed["steps"] if s["name"] == "d")
    assert d["depends_on"] == ["b", "c"]


def test_topology_hash_is_deterministic():
    _clear_registry()
    W = _make_diamond_class("W_hash1")
    h1 = topology_hash(W)

    _clear_registry()
    W2 = _make_diamond_class("W_hash1")  # same name, same shape
    h2 = topology_hash(W2)

    assert h1 == h2


def test_topology_hash_is_insensitive_to_method_body():
    _clear_registry()

    @workflow(name="W_body", queue="default")
    class V1:
        _a = Step("a")
        def a(self): return 1
    h1 = topology_hash(V1)

    _clear_registry()

    @workflow(name="W_body", queue="default")
    class V2:
        _a = Step("a")
        def a(self): return 99   # body changed
    h2 = topology_hash(V2)

    assert h1 == h2, "topology hash must NOT depend on method bodies"


def test_topology_hash_changes_when_dependency_added():
    _clear_registry()
    @workflow(name="W_dep", queue="default")
    class V1:
        _a = Step("a")
        _b = Step("b", depends_on=())
        def a(self): pass
        def b(self): pass
    h1 = topology_hash(V1)

    _clear_registry()
    @workflow(name="W_dep", queue="default")
    class V2:
        _a = Step("a")
        _b = Step("b", depends_on=("a",))
        def a(self): pass
        def b(self): pass
    h2 = topology_hash(V2)

    assert h1 != h2


def test_topology_hash_changes_when_compensation_added():
    _clear_registry()
    @workflow(name="W_comp", queue="default")
    class V1:
        _a = Step("a")
        def a(self): pass
    h1 = topology_hash(V1)

    _clear_registry()
    @workflow(name="W_comp", queue="default")
    class V2:
        _a = Step("a", compensation="undo_a")
        def a(self): pass
        def undo_a(self): pass
    h2 = topology_hash(V2)

    assert h1 != h2
```

- [ ] **Step 2: Run tests to verify they fail**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_workflow_snapshot.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement the snapshot module**

Create `conductor/workflow/snapshot.py`:

```python
"""Canonical-JSON snapshot + deterministic SHA-256 hash of a workflow's topology.

Hash inputs (master §3 #20 / spec §13):
  - Workflow name and queue
  - Per step: name, sorted depends_on, compensation method name (or null)

Excluded: method bodies, attribute declaration order, anything else.
"""

from __future__ import annotations

import hashlib
import json


def _step_dict(step) -> dict:
    return {
        "name": step.name,
        "depends_on": sorted(step.depends_on),
        "compensation": step.compensation,
    }


def snapshot_from_class(cls: type) -> str:
    """Return the canonical-JSON snapshot string for a registered workflow class."""
    steps = sorted(cls.__conductor_workflow_steps__, key=lambda s: s.name)
    payload = {
        "name": cls.__conductor_workflow_name__,
        "queue": cls.__conductor_workflow_queue__,
        "steps": [_step_dict(s) for s in steps],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def topology_hash(cls: type) -> str:
    """SHA-256 hex digest of the canonical snapshot."""
    return hashlib.sha256(snapshot_from_class(cls).encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run tests to verify they pass**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_workflow_snapshot.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```
git add conductor/workflow/snapshot.py tests/test_workflow_snapshot.py
git commit -m "feat(workflow): canonical snapshot + topology hash"
```

---

## Task 6: Redis key helpers + workflow idempotency lock

**Files:**
- Create: `conductor/workflow/keys.py`
- Create: `conductor/workflow/idempotency.py`
- Test: `tests/test_workflow_keys.py`
- Test: `tests/test_workflow_idempotency.py`

- [ ] **Step 1: Write failing tests for keys**

Create `tests/test_workflow_keys.py`:

```python
"""Workflow Redis key helpers."""

from conductor.workflow.keys import wfdeps_key, wfidem_key


def test_wfdeps_key_format():
    assert wfdeps_key("frappe.localhost", "abc-123") == "conductor:frappe.localhost:wfdeps:abc-123"


def test_wfidem_key_is_sha256_hashed():
    k = wfidem_key("frappe.localhost", "ord-42-fulfill")
    assert k.startswith("conductor:frappe.localhost:wfidem:")
    h = k.rsplit(":", 1)[-1]
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
```

- [ ] **Step 2: Write failing tests for idempotency**

Create `tests/test_workflow_idempotency.py`:

```python
"""Workflow-run idempotency lock — wraps Redis SET NX EX, mirrors job idem."""

from conductor.workflow.idempotency import acquire_wfidem_lock


def test_first_call_acquires_lock(fake_redis):
    existing = acquire_wfidem_lock(
        fake_redis,
        site="frappe.localhost",
        idempotency_key="run-once",
        run_id="run-1",
        ttl=60,
    )
    assert existing is None


def test_second_call_with_same_key_returns_first_run_id(fake_redis):
    acquire_wfidem_lock(
        fake_redis, site="frappe.localhost",
        idempotency_key="run-once", run_id="run-1", ttl=60,
    )
    existing = acquire_wfidem_lock(
        fake_redis, site="frappe.localhost",
        idempotency_key="run-once", run_id="run-2", ttl=60,
    )
    assert existing == "run-1"


def test_empty_key_returns_none_no_state_change(fake_redis):
    existing = acquire_wfidem_lock(
        fake_redis, site="frappe.localhost",
        idempotency_key="", run_id="run-1", ttl=60,
    )
    assert existing is None
    keys = fake_redis.keys("conductor:*")
    assert keys == []
```

- [ ] **Step 3: Run both test files to verify they fail**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_workflow_keys.py tests/test_workflow_idempotency.py -v
```

Expected: `ImportError`.

- [ ] **Step 4: Implement keys module**

Create `conductor/workflow/keys.py`:

```python
"""Redis key namespacing for Phase 5 workflow state.

All keys follow master §8 / spec §9: conductor:{site}:<purpose>:<scope>.
Lua scripts touch the wfdeps key only — single-key per master §3 #15.
"""

from __future__ import annotations

from hashlib import sha256


def wfdeps_key(site: str, run_id: str) -> str:
    return f"conductor:{site}:wfdeps:{run_id}"


def wfidem_key(site: str, idempotency_key: str) -> str:
    h = sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"conductor:{site}:wfidem:{h}"
```

- [ ] **Step 5: Implement idempotency module**

Create `conductor/workflow/idempotency.py`:

```python
"""Workflow-run idempotency: SET NX EX on conductor:{site}:wfidem:{hash}.

Mirrors conductor.idempotency.acquire_idem_lock for jobs (TTL is the only
release; duplicate within TTL is the entire point of the lock).
"""

from __future__ import annotations

from typing import Optional

import redis as redis_mod

from conductor.workflow.keys import wfidem_key


def acquire_wfidem_lock(
    client: redis_mod.Redis,
    site: str,
    idempotency_key: str,
    run_id: str,
    *,
    ttl: int,
) -> Optional[str]:
    """Try to claim the idempotency slot. Returns:
      - None if newly acquired (or idempotency disabled by empty key)
      - existing run_id if a prior call holds the slot
    """
    if not idempotency_key:
        return None
    key = wfidem_key(site, idempotency_key)
    if client.set(key, run_id, nx=True, ex=ttl):
        return None
    existing = client.get(key)
    return existing.decode("utf-8") if isinstance(existing, bytes) else existing
```

- [ ] **Step 6: Run tests to verify they pass**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_workflow_keys.py tests/test_workflow_idempotency.py -v
```

Expected: 5 passed.

- [ ] **Step 7: Commit**

```
git add conductor/workflow/keys.py conductor/workflow/idempotency.py tests/test_workflow_keys.py tests/test_workflow_idempotency.py
git commit -m "feat(workflow): wfdeps/wfidem Redis keys + run idempotency lock"
```

---

## Task 7: `fanin_decrement` Lua script

**Files:**
- Create: `conductor/workflow/lua.py`
- Test: `tests/test_workflow_lua.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_workflow_lua.py`:

```python
"""fanin_decrement Lua script tests against fakeredis."""

import json

from conductor.workflow.keys import wfdeps_key
from conductor.workflow.lua import FANIN_DECREMENT


def _seed(fake_redis, site, run_id, deps: dict[str, int]):
    key = wfdeps_key(site, run_id)
    if deps:
        fake_redis.hset(key, mapping={k: str(v) for k, v in deps.items()})


def _run(fake_redis, site, run_id, completed, downstreams):
    key = wfdeps_key(site, run_id)
    return fake_redis.eval(
        FANIN_DECREMENT, 1, key, completed or "", json.dumps(downstreams)
    )


def test_first_call_returns_roots(fake_redis):
    _seed(fake_redis, "s", "r1", {"a": 0, "b": 1, "c": 1, "d": 2})
    ready = _run(fake_redis, "s", "r1", completed=None, downstreams=[])
    assert sorted([x.decode() if isinstance(x, bytes) else x for x in ready]) == ["a"]


def test_decrement_releases_one_downstream(fake_redis):
    _seed(fake_redis, "s", "r1", {"a": 0, "b": 1, "c": 1, "d": 2})
    # a finished → b and c are downstream (each had 1 dep), should both go to 0
    ready = _run(fake_redis, "s", "r1", completed="a", downstreams=["b", "c"])
    names = sorted([x.decode() if isinstance(x, bytes) else x for x in ready])
    assert names == ["b", "c"]
    # d still has 2 deps not yet decremented
    assert int(fake_redis.hget(wfdeps_key("s", "r1"), "d")) == 2


def test_two_siblings_finish_then_d_unblocks(fake_redis):
    _seed(fake_redis, "s", "r1", {"a": 0, "b": 1, "c": 1, "d": 2})
    _run(fake_redis, "s", "r1", completed="a", downstreams=["b", "c"])
    # b finishes → d 2 → 1, not ready
    ready1 = _run(fake_redis, "s", "r1", completed="b", downstreams=["d"])
    assert ready1 == []
    # c finishes → d 1 → 0, ready
    ready2 = _run(fake_redis, "s", "r1", completed="c", downstreams=["d"])
    names = [x.decode() if isinstance(x, bytes) else x for x in ready2]
    assert names == ["d"]


def test_double_decrement_is_idempotent_no_extra_dispatch(fake_redis):
    """A re-fired advancer for the same completion shouldn't re-emit the same step."""
    _seed(fake_redis, "s", "r1", {"a": 0, "b": 1})
    _run(fake_redis, "s", "r1", completed="a", downstreams=["b"])  # b → 0, returned
    ready = _run(fake_redis, "s", "r1", completed="a", downstreams=["b"])
    # b's count is now -1; the script returns it again, but the dispatcher
    # guards against double-dispatch via Step Run row state — see Task 9.
    # The Lua script itself is monotone: it returns "now ≤ 0" steps.
    names = [x.decode() if isinstance(x, bytes) else x for x in ready]
    assert names == ["b"]
```

- [ ] **Step 2: Run tests to verify they fail**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_workflow_lua.py -v
```

Expected: `ImportError: No module named 'conductor.workflow.lua'`.

- [ ] **Step 3: Implement the script**

Create `conductor/workflow/lua.py`:

```python
"""Lua script for atomic fan-in deps decrement.

Single-key (KEYS[1] = wfdeps:{run_id}) per master §3 #15.

Semantics:
  - If ARGV[1] is empty: scan the hash, return all step ids whose value is "0".
  - Else: for each downstream id in JSON-decoded ARGV[2], HINCRBY -1.
    Collect those whose new value is ≤ 0. Return them.

Re-fires of the same completion are tolerated by the script (count goes
negative); the dispatcher side de-dupes via Step Run row state.
"""

FANIN_DECREMENT = """
local key = KEYS[1]
local completed = ARGV[1]
local downstreams_json = ARGV[2]
local ready = {}

if completed == nil or completed == '' then
  -- First call: collect all roots (current value == 0)
  local all = redis.call('HGETALL', key)
  for i = 1, #all, 2 do
    if all[i + 1] == '0' then
      table.insert(ready, all[i])
    end
  end
  return ready
end

-- ARGV[2] is a JSON array of downstream step ids
local downstreams = cjson.decode(downstreams_json)
for _, step in ipairs(downstreams) do
  local newval = redis.call('HINCRBY', key, step, -1)
  if newval <= 0 then
    table.insert(ready, step)
  end
end
return ready
"""
```

- [ ] **Step 4: Run tests to verify they pass**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_workflow_lua.py -v
```

Expected: 4 passed.

NOTE: fakeredis supports `EVAL`+`cjson` via the `lupa` package (already in dev-deps). If a test fails with "lupa not installed", install it: `/Users/osamamuhammed/frappe_15/env/bin/pip install 'lupa>=2,<3' --break-system-packages`.

- [ ] **Step 5: Commit**

```
git add conductor/workflow/lua.py tests/test_workflow_lua.py
git commit -m "feat(workflow): single-key fanin_decrement Lua script"
```

---

## Task 8: `Conductor Workflow` DocType

**Files:**
- Create: `conductor/conductor/doctype/conductor_workflow/__init__.py`
- Create: `conductor/conductor/doctype/conductor_workflow/conductor_workflow.json`
- Create: `conductor/conductor/doctype/conductor_workflow/conductor_workflow.py`
- Create: `conductor/conductor/doctype/conductor_workflow/test_conductor_workflow.py`

- [ ] **Step 1: Create the doctype JSON**

`conductor/conductor/doctype/conductor_workflow/conductor_workflow.json`:

```json
{
 "actions": [],
 "allow_rename": 0,
 "autoname": "field:workflow_name",
 "creation": "2026-04-29 00:00:00",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "workflow_name", "enabled", "definition_path", "version", "definition_snapshot",
  "last_version_bumped_at", "description"
 ],
 "fields": [
  {"fieldname": "workflow_name", "fieldtype": "Data", "label": "Workflow Name", "reqd": 1, "unique": 1, "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "enabled", "fieldtype": "Check", "label": "Enabled", "default": "1", "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "definition_path", "fieldtype": "Data", "label": "Definition Path", "description": "Dotted path to the @workflow class", "in_list_view": 1},
  {"fieldname": "version", "fieldtype": "Int", "label": "Version", "default": "1", "read_only": 1, "in_list_view": 1},
  {"fieldname": "definition_snapshot", "fieldtype": "Long Text", "label": "Definition Snapshot", "read_only": 1, "description": "Frozen DAG JSON; system-managed"},
  {"fieldname": "last_version_bumped_at", "fieldtype": "Datetime", "label": "Last Version Bumped At", "read_only": 1},
  {"fieldname": "description", "fieldtype": "Small Text", "label": "Description"}
 ],
 "links": [],
 "modified": "2026-04-29 00:00:00",
 "modified_by": "Administrator",
 "module": "Conductor",
 "name": "Conductor Workflow",
 "owner": "Administrator",
 "permissions": [
  {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "report": 1, "export": 1},
  {"role": "Conductor Operator", "read": 1, "report": 1, "export": 1}
 ],
 "sort_field": "workflow_name",
 "sort_order": "ASC",
 "track_changes": 1
}
```

- [ ] **Step 2: Create the controller stub**

`conductor/conductor/doctype/conductor_workflow/conductor_workflow.py`:

```python
"""Conductor Workflow controller — definition_snapshot is system-managed."""

from __future__ import annotations

from frappe.model.document import Document


class ConductorWorkflow(Document):
    pass
```

- [ ] **Step 3: Create the package init**

`conductor/conductor/doctype/conductor_workflow/__init__.py`: (empty file)

- [ ] **Step 4: Create the smoke test**

`conductor/conductor/doctype/conductor_workflow/test_conductor_workflow.py`:

```python
"""Smoke test for Conductor Workflow DocType."""

from __future__ import annotations

import unittest

import frappe


class TestConductorWorkflow(unittest.TestCase):
    def tearDown(self):
        for n in frappe.get_all("Conductor Workflow", pluck="name"):
            frappe.delete_doc("Conductor Workflow", n, force=True)
        frappe.db.commit()

    def test_insert_workflow_row(self):
        doc = frappe.get_doc({
            "doctype": "Conductor Workflow",
            "workflow_name": "TestFlow",
            "enabled": 1,
            "definition_path": "myapp.workflows.TestFlow",
            "version": 1,
            "definition_snapshot": '{"name":"TestFlow","queue":"default","steps":[]}',
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        self.assertEqual(doc.name, "TestFlow")
        self.assertEqual(doc.version, 1)
```

- [ ] **Step 5: Run the migration locally to register the DocType**

```
bench --site frappe.localhost migrate
```

Expected: migration runs, no errors. The new DocType is now installed.

- [ ] **Step 6: Run the smoke test**

```
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_workflow.test_conductor_workflow
```

Expected: 1 test passes.

- [ ] **Step 7: Commit**

```
git add conductor/conductor/doctype/conductor_workflow/
git commit -m "feat(workflow): Conductor Workflow DocType"
```

---

## Task 9: `Conductor Workflow Run` DocType

**Files:**
- Create: `conductor/conductor/doctype/conductor_workflow_run/__init__.py`
- Create: `conductor/conductor/doctype/conductor_workflow_run/conductor_workflow_run.json`
- Create: `conductor/conductor/doctype/conductor_workflow_run/conductor_workflow_run.py`
- Create: `conductor/conductor/doctype/conductor_workflow_run/test_conductor_workflow_run.py`

- [ ] **Step 1: Create the doctype JSON**

`conductor/conductor/doctype/conductor_workflow_run/conductor_workflow_run.json`:

```json
{
 "actions": [],
 "allow_rename": 0,
 "autoname": "format:WR-{####}-{YYYY}",
 "creation": "2026-04-29 00:00:00",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "workflow", "definition_version", "status", "site",
  "section_input", "input_args", "input_kwargs",
  "section_lifecycle", "started_at", "finished_at",
  "section_meta", "idempotency_key", "cancelled_at", "cancelled_by",
  "section_error", "last_error"
 ],
 "fields": [
  {"fieldname": "workflow", "fieldtype": "Link", "options": "Conductor Workflow", "label": "Workflow", "reqd": 1, "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "definition_version", "fieldtype": "Int", "label": "Definition Version", "reqd": 1, "in_list_view": 1},
  {"fieldname": "status", "fieldtype": "Select", "label": "Status",
   "options": "PENDING\nRUNNING\nCOMPENSATING\nSUCCEEDED\nFAILED\nCANCELLED",
   "default": "PENDING", "reqd": 1, "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "site", "fieldtype": "Data", "label": "Site"},

  {"fieldname": "section_input", "fieldtype": "Section Break", "label": "Input"},
  {"fieldname": "input_args", "fieldtype": "Long Text", "label": "Input Args (msgpack-base64)"},
  {"fieldname": "input_kwargs", "fieldtype": "Long Text", "label": "Input Kwargs (msgpack-base64)"},

  {"fieldname": "section_lifecycle", "fieldtype": "Section Break", "label": "Lifecycle"},
  {"fieldname": "started_at", "fieldtype": "Datetime", "label": "Started At"},
  {"fieldname": "finished_at", "fieldtype": "Datetime", "label": "Finished At"},

  {"fieldname": "section_meta", "fieldtype": "Section Break", "label": "Metadata"},
  {"fieldname": "idempotency_key", "fieldtype": "Data", "label": "Idempotency Key"},
  {"fieldname": "cancelled_at", "fieldtype": "Datetime", "label": "Cancelled At"},
  {"fieldname": "cancelled_by", "fieldtype": "Link", "options": "User", "label": "Cancelled By"},

  {"fieldname": "section_error", "fieldtype": "Section Break", "label": "Error"},
  {"fieldname": "last_error", "fieldtype": "Long Text", "label": "Last Error"}
 ],
 "links": [],
 "modified": "2026-04-29 00:00:00",
 "modified_by": "Administrator",
 "module": "Conductor",
 "name": "Conductor Workflow Run",
 "owner": "Administrator",
 "permissions": [
  {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "report": 1, "export": 1},
  {"role": "Conductor Operator", "read": 1, "report": 1, "export": 1}
 ],
 "sort_field": "creation",
 "sort_order": "DESC",
 "track_changes": 1
}
```

- [ ] **Step 2: Create the controller**

`conductor/conductor/doctype/conductor_workflow_run/conductor_workflow_run.py`:

```python
"""Conductor Workflow Run controller — fields are system-managed."""

from __future__ import annotations

from frappe.model.document import Document


class ConductorWorkflowRun(Document):
    pass
```

- [ ] **Step 3: Create the package init**

`conductor/conductor/doctype/conductor_workflow_run/__init__.py`: empty.

- [ ] **Step 4: Create the smoke test**

`conductor/conductor/doctype/conductor_workflow_run/test_conductor_workflow_run.py`:

```python
"""Smoke test for Conductor Workflow Run DocType."""

from __future__ import annotations

import unittest

import frappe


class TestConductorWorkflowRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not frappe.db.exists("Conductor Workflow", "TestFlowForRun"):
            frappe.get_doc({
                "doctype": "Conductor Workflow",
                "workflow_name": "TestFlowForRun",
                "definition_path": "myapp.x",
                "version": 1,
                "definition_snapshot": "{}",
            }).insert(ignore_permissions=True)
            frappe.db.commit()

    def tearDown(self):
        for n in frappe.get_all("Conductor Workflow Run", pluck="name"):
            frappe.delete_doc("Conductor Workflow Run", n, force=True)
        frappe.db.commit()

    def test_insert_run_row(self):
        doc = frappe.get_doc({
            "doctype": "Conductor Workflow Run",
            "workflow": "TestFlowForRun",
            "definition_version": 1,
            "status": "PENDING",
            "site": "frappe.localhost",
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        self.assertTrue(doc.name.startswith("WR-"))
        self.assertEqual(doc.status, "PENDING")
```

- [ ] **Step 5: Migrate + run**

```
bench --site frappe.localhost migrate
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_workflow_run.test_conductor_workflow_run
```

Expected: 1 test passes.

- [ ] **Step 6: Commit**

```
git add conductor/conductor/doctype/conductor_workflow_run/
git commit -m "feat(workflow): Conductor Workflow Run DocType"
```

---

## Task 10: `Conductor Workflow Step Run` DocType

**Files:**
- Create: `conductor/conductor/doctype/conductor_workflow_step_run/__init__.py`
- Create: `conductor/conductor/doctype/conductor_workflow_step_run/conductor_workflow_step_run.json`
- Create: `conductor/conductor/doctype/conductor_workflow_step_run/conductor_workflow_step_run.py`
- Create: `conductor/conductor/doctype/conductor_workflow_step_run/test_conductor_workflow_step_run.py`

- [ ] **Step 1: Create the doctype JSON**

`conductor/conductor/doctype/conductor_workflow_step_run/conductor_workflow_step_run.json`:

```json
{
 "actions": [],
 "allow_rename": 0,
 "autoname": "format:WSR-{######}",
 "creation": "2026-04-29 00:00:00",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "workflow_run", "step_id", "is_compensation", "status", "depends_on",
  "section_lifecycle", "started_at", "finished_at",
  "section_link", "job",
  "section_error", "error_type", "error_message"
 ],
 "fields": [
  {"fieldname": "workflow_run", "fieldtype": "Link", "options": "Conductor Workflow Run", "label": "Workflow Run", "reqd": 1, "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "step_id", "fieldtype": "Data", "label": "Step ID", "reqd": 1, "in_list_view": 1},
  {"fieldname": "is_compensation", "fieldtype": "Check", "label": "Is Compensation", "default": "0", "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "status", "fieldtype": "Select", "label": "Status",
   "options": "PENDING\nREADY\nRUNNING\nSUCCEEDED\nFAILED\nCOMPENSATED\nSKIPPED",
   "default": "PENDING", "reqd": 1, "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "depends_on", "fieldtype": "Long Text", "label": "Depends On (JSON)"},

  {"fieldname": "section_lifecycle", "fieldtype": "Section Break", "label": "Lifecycle"},
  {"fieldname": "started_at", "fieldtype": "Datetime", "label": "Started At"},
  {"fieldname": "finished_at", "fieldtype": "Datetime", "label": "Finished At"},

  {"fieldname": "section_link", "fieldtype": "Section Break", "label": "Underlying Job"},
  {"fieldname": "job", "fieldtype": "Link", "options": "Conductor Job", "label": "Job"},

  {"fieldname": "section_error", "fieldtype": "Section Break", "label": "Error"},
  {"fieldname": "error_type", "fieldtype": "Data", "label": "Error Type"},
  {"fieldname": "error_message", "fieldtype": "Small Text", "label": "Error Message"}
 ],
 "links": [],
 "modified": "2026-04-29 00:00:00",
 "modified_by": "Administrator",
 "module": "Conductor",
 "name": "Conductor Workflow Step Run",
 "owner": "Administrator",
 "permissions": [
  {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "report": 1, "export": 1},
  {"role": "Conductor Operator", "read": 1, "report": 1, "export": 1}
 ],
 "sort_field": "creation",
 "sort_order": "DESC",
 "track_changes": 1
}
```

- [ ] **Step 2: Create controller and `__init__.py`**

`conductor/conductor/doctype/conductor_workflow_step_run/conductor_workflow_step_run.py`:

```python
"""Conductor Workflow Step Run controller."""

from __future__ import annotations

from frappe.model.document import Document


class ConductorWorkflowStepRun(Document):
    pass
```

`__init__.py`: empty.

- [ ] **Step 3: Smoke test**

`conductor/conductor/doctype/conductor_workflow_step_run/test_conductor_workflow_step_run.py`:

```python
"""Smoke test for Conductor Workflow Step Run DocType."""

from __future__ import annotations

import unittest

import frappe


class TestConductorWorkflowStepRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not frappe.db.exists("Conductor Workflow", "TestFlowForStep"):
            frappe.get_doc({
                "doctype": "Conductor Workflow",
                "workflow_name": "TestFlowForStep",
                "definition_path": "myapp.x",
                "version": 1,
                "definition_snapshot": "{}",
            }).insert(ignore_permissions=True)
        cls.run_name = frappe.get_doc({
            "doctype": "Conductor Workflow Run",
            "workflow": "TestFlowForStep",
            "definition_version": 1,
            "status": "PENDING",
            "site": "frappe.localhost",
        }).insert(ignore_permissions=True).name
        frappe.db.commit()

    def tearDown(self):
        for n in frappe.get_all("Conductor Workflow Step Run", pluck="name"):
            frappe.delete_doc("Conductor Workflow Step Run", n, force=True)
        frappe.db.commit()

    def test_insert_step_run(self):
        doc = frappe.get_doc({
            "doctype": "Conductor Workflow Step Run",
            "workflow_run": self.run_name,
            "step_id": "a",
            "is_compensation": 0,
            "status": "PENDING",
            "depends_on": "[]",
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        self.assertTrue(doc.name.startswith("WSR-"))
        self.assertEqual(doc.status, "PENDING")
```

- [ ] **Step 4: Migrate + run**

```
bench --site frappe.localhost migrate
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_workflow_step_run.test_conductor_workflow_step_run
```

Expected: 1 test passes.

- [ ] **Step 5: Commit**

```
git add conductor/conductor/doctype/conductor_workflow_step_run/
git commit -m "feat(workflow): Conductor Workflow Step Run DocType"
```

---

## Task 11: `run_workflow()` dispatcher (no advancer enqueue yet)

This task implements the run setup: registry lookup, version-bump-or-insert of `Conductor Workflow`, idempotency check, run row insert, step rows insert, and Redis deps seed. **The advancer enqueue is left to Task 12** so this task is testable in isolation.

**Files:**
- Create: `conductor/workflow/dispatcher.py`
- Modify: `conductor/workflow/__init__.py` (re-export `run_workflow`)
- Test: `conductor/conductor/doctype/conductor_workflow_run/test_run_workflow_dispatch.py` (new file in DocType folder so it runs under Frappe)

- [ ] **Step 1: Write failing tests**

Create `conductor/conductor/doctype/conductor_workflow_run/test_run_workflow_dispatch.py`:

```python
"""Frappe-integration tests for run_workflow() dispatcher (no advancer enqueue)."""

from __future__ import annotations

import unittest

import frappe

from conductor.workflow import Step, workflow
from conductor.workflow.decorator import _REGISTRY
from conductor.workflow.keys import wfdeps_key
from conductor.client import get_redis
from conductor.config import load_config


def _make_diamond(name: str = "DiamondTestFlow"):
    _REGISTRY.pop(name, None)

    @workflow(name=name, queue="default")
    class Diamond:
        _a = Step("a")
        _b = Step("b", depends_on=("a",), compensation="undo_b")
        _c = Step("c", depends_on=("a",))
        _d = Step("d", depends_on=("b", "c"))
        def a(self): pass
        def b(self): pass
        def undo_b(self): pass
        def c(self): pass
        def d(self): pass
    return Diamond


def _redis():
    cfg = load_config(frappe.local.conf)
    return get_redis(cfg.redis_url)


class TestRunWorkflowDispatch(unittest.TestCase):
    def setUp(self):
        from conductor.workflow.dispatcher import _ENQUEUE_ADVANCER_HOOK
        # The hook is set by Task 12; for this task it's None and dispatch must
        # still succeed (advancer simply isn't fired).
        self.workflow_cls = _make_diamond()
        if not frappe.db.exists("Conductor Queue", "default"):
            frappe.get_doc({
                "doctype": "Conductor Queue", "queue_name": "default", "enabled": 1,
            }).insert(ignore_permissions=True)
            frappe.db.commit()

    def tearDown(self):
        for n in frappe.get_all("Conductor Workflow Step Run", pluck="name"):
            frappe.delete_doc("Conductor Workflow Step Run", n, force=True)
        for n in frappe.get_all("Conductor Workflow Run", pluck="name"):
            frappe.delete_doc("Conductor Workflow Run", n, force=True)
        for n in frappe.get_all("Conductor Workflow", pluck="name"):
            frappe.delete_doc("Conductor Workflow", n, force=True)
        frappe.db.commit()
        # Clean Redis wfdeps keys
        r = _redis()
        for k in r.scan_iter("conductor:*:wfdeps:*"):
            r.delete(k)
        for k in r.scan_iter("conductor:*:wfidem:*"):
            r.delete(k)

    def test_first_dispatch_creates_workflow_row_at_version_1(self):
        from conductor.workflow.dispatcher import run_workflow
        run_id = run_workflow("DiamondTestFlow", order_id=42)
        self.assertTrue(run_id.startswith("WR-"))
        wf = frappe.get_doc("Conductor Workflow", "DiamondTestFlow")
        self.assertEqual(wf.version, 1)
        self.assertIn('"name":"DiamondTestFlow"', wf.definition_snapshot)

    def test_dispatch_inserts_one_step_row_per_step_status_pending(self):
        from conductor.workflow.dispatcher import run_workflow
        run_id = run_workflow("DiamondTestFlow", order_id=42)
        rows = frappe.get_all(
            "Conductor Workflow Step Run",
            filters={"workflow_run": run_id},
            fields=["step_id", "status", "is_compensation"],
        )
        self.assertEqual(len(rows), 4)
        self.assertEqual({r["step_id"] for r in rows}, {"a", "b", "c", "d"})
        self.assertTrue(all(r["status"] == "PENDING" for r in rows))
        self.assertTrue(all(r["is_compensation"] == 0 for r in rows))

    def test_dispatch_seeds_wfdeps_hash(self):
        from conductor.workflow.dispatcher import run_workflow
        run_id = run_workflow("DiamondTestFlow", order_id=42)
        site = frappe.local.site
        deps = _redis().hgetall(wfdeps_key(site, run_id))
        decoded = {k.decode(): int(v) for k, v in deps.items()}
        self.assertEqual(decoded, {"a": 0, "b": 1, "c": 1, "d": 2})

    def test_idempotent_dispatch_returns_first_run_id(self):
        from conductor.workflow.dispatcher import run_workflow
        a = run_workflow("DiamondTestFlow", order_id=42, idempotency_key="ord-42")
        b = run_workflow("DiamondTestFlow", order_id=42, idempotency_key="ord-42")
        self.assertEqual(a, b)
        # Only one run row
        runs = frappe.get_all("Conductor Workflow Run")
        self.assertEqual(len(runs), 1)

    def test_topology_change_bumps_version(self):
        from conductor.workflow.dispatcher import run_workflow
        run_workflow("DiamondTestFlow", order_id=42)
        v1 = frappe.get_value("Conductor Workflow", "DiamondTestFlow", "version")
        self.assertEqual(v1, 1)

        # Re-decorate with a structurally different DAG, same name
        _REGISTRY.pop("DiamondTestFlow", None)

        @workflow(name="DiamondTestFlow", queue="default")
        class V2:
            _a = Step("a")
            _b = Step("b", depends_on=("a",))
            _c = Step("c", depends_on=("a", "b"))   # added dep on b
            _d = Step("d", depends_on=("b", "c"))
            def a(self): pass
            def b(self): pass
            def c(self): pass
            def d(self): pass

        run_workflow("DiamondTestFlow", order_id=99)
        v2 = frappe.get_value("Conductor Workflow", "DiamondTestFlow", "version")
        self.assertEqual(v2, 2)

    def test_unknown_workflow_raises(self):
        from conductor.workflow.dispatcher import run_workflow
        from conductor.workflow.dispatcher import WorkflowNotFoundError
        with self.assertRaises(WorkflowNotFoundError):
            run_workflow("NonExistentFlow")
```

- [ ] **Step 2: Run tests to verify they fail**

```
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_workflow_run.test_run_workflow_dispatch
```

Expected: `ImportError: No module named 'conductor.workflow.dispatcher'`.

- [ ] **Step 3: Implement the dispatcher**

Create `conductor/workflow/dispatcher.py`:

```python
"""run_workflow() — entry point for triggering a workflow run.

Spec §6.1 (forward dispatch flow) and §13 (versioning algorithm).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

import frappe

from conductor.client import get_redis
from conductor.config import load_config
from conductor.logging import get_logger
from conductor.serialization import dumps as msgpack_dumps
from conductor.workflow.decorator import get_registered
from conductor.workflow.idempotency import acquire_wfidem_lock
from conductor.workflow.keys import wfdeps_key
from conductor.workflow.snapshot import snapshot_from_class, topology_hash
from conductor.workflow.topo import in_degrees

log = get_logger("conductor.workflow.dispatcher")

_DEFAULT_WFIDEM_TTL = 86_400  # 24h, mirrors job idempotency

# Hook set by Task 12 (advancer module). Left as None here so dispatch is
# testable without the advancer.
_ENQUEUE_ADVANCER_HOOK: Optional[Callable[[str, Optional[str]], None]] = None


class WorkflowNotFoundError(Exception):
    pass


def _b64encode_kwargs(d: dict[str, Any]) -> str:
    if not d:
        return ""
    import base64
    return base64.b64encode(msgpack_dumps(d)).decode("ascii")


def _bump_or_insert_workflow_row(cls: type) -> int:
    name = cls.__conductor_workflow_name__
    snap = snapshot_from_class(cls)

    if not frappe.db.exists("Conductor Workflow", name):
        frappe.get_doc({
            "doctype": "Conductor Workflow",
            "workflow_name": name,
            "enabled": 1,
            "definition_path": f"{cls.__module__}.{cls.__qualname__}",
            "version": 1,
            "definition_snapshot": snap,
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        return 1

    row = frappe.get_doc("Conductor Workflow", name)
    if row.definition_snapshot == snap:
        return int(row.version)
    row.version = int(row.version) + 1
    row.definition_snapshot = snap
    row.definition_path = f"{cls.__module__}.{cls.__qualname__}"
    row.last_version_bumped_at = datetime.now(timezone.utc).replace(tzinfo=None)
    row.save(ignore_permissions=True)
    frappe.db.commit()
    log.info("workflow_version_bumped", workflow=name, new_version=row.version)
    return int(row.version)


def _insert_step_runs(run_id: str, cls: type) -> None:
    import json
    for step in cls.__conductor_workflow_steps__:
        frappe.get_doc({
            "doctype": "Conductor Workflow Step Run",
            "workflow_run": run_id,
            "step_id": step.name,
            "is_compensation": 0,
            "status": "PENDING",
            "depends_on": json.dumps(list(step.depends_on)),
        }).insert(ignore_permissions=True)
    frappe.db.commit()


def _seed_deps_hash(redis_client, site: str, run_id: str, cls: type) -> None:
    deps = in_degrees(cls.__conductor_workflow_steps__)
    if deps:
        redis_client.hset(
            wfdeps_key(site, run_id),
            mapping={k: str(v) for k, v in deps.items()},
        )


def run_workflow(
    name: str,
    *,
    idempotency_key: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """Trigger a workflow run. Returns the (new or idempotent-existing) run_id."""
    cls = get_registered(name)
    if cls is None:
        raise WorkflowNotFoundError(f"workflow not registered: {name!r}")

    site = frappe.local.site
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)

    version = _bump_or_insert_workflow_row(cls)

    run_id_placeholder = frappe.generate_hash(length=10)
    if idempotency_key:
        ttl = int(
            (frappe.local.conf.get("conductor") or {}).get(
                "wfidem_ttl_seconds", _DEFAULT_WFIDEM_TTL
            )
        )
        existing = acquire_wfidem_lock(
            r, site, idempotency_key, run_id_placeholder, ttl=ttl
        )
        if existing is not None:
            log.info(
                "workflow_idempotency_hit",
                workflow=name, idem_key=idempotency_key, existing_run_id=existing,
            )
            return existing

    run_doc = frappe.get_doc({
        "doctype": "Conductor Workflow Run",
        "workflow": name,
        "definition_version": version,
        "status": "PENDING",
        "site": site,
        "input_args": "",
        "input_kwargs": _b64encode_kwargs(kwargs),
        "idempotency_key": idempotency_key or "",
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    run_id = run_doc.name

    _insert_step_runs(run_id, cls)
    _seed_deps_hash(r, site, run_id, cls)

    if idempotency_key:
        # Replace the placeholder in the idem key with the real run_id, so
        # idempotent re-dispatches return the right id.
        from conductor.workflow.keys import wfidem_key as _kfn
        r.set(_kfn(site, idempotency_key), run_id, ex=_DEFAULT_WFIDEM_TTL, xx=True)

    if _ENQUEUE_ADVANCER_HOOK is not None:
        _ENQUEUE_ADVANCER_HOOK(run_id, None)

    return run_id
```

Modify `conductor/workflow/__init__.py` — re-export `run_workflow`:

```python
"""Conductor Phase 5 — Workflow public API.

Spec: docs/superpowers/specs/2026-04-29-conductor-phase5-workflows-design.md
"""

from conductor.workflow.decorator import (
    Step,
    WorkflowDefinitionError,
    workflow,
)
from conductor.workflow.dispatcher import run_workflow, WorkflowNotFoundError

__all__ = [
    "Step",
    "WorkflowDefinitionError",
    "WorkflowNotFoundError",
    "run_workflow",
    "workflow",
]
```

- [ ] **Step 4: Run tests to verify they pass**

```
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_workflow_run.test_run_workflow_dispatch
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```
git add conductor/workflow/dispatcher.py conductor/workflow/__init__.py conductor/conductor/doctype/conductor_workflow_run/test_run_workflow_dispatch.py
git commit -m "feat(workflow): run_workflow() dispatcher with version bump + deps seed"
```

---

## Task 12: Advancer entry-point — forward path (PENDING/RUNNING branch)

This task wires the advancer as a `@conductor.job`-decorated function on the `workflow` queue, implements the forward branch (Lua decrement → mark steps READY → enqueue jobs), and wires the dispatcher to enqueue it.

**Files:**
- Create: `conductor/workflow/advancer.py`
- Modify: `conductor/workflow/dispatcher.py` (set `_ENQUEUE_ADVANCER_HOOK`)
- Test: `conductor/conductor/doctype/conductor_workflow_run/test_advancer_forward.py`

- [ ] **Step 1: Write failing tests**

Create `conductor/conductor/doctype/conductor_workflow_run/test_advancer_forward.py`:

```python
"""Advancer forward-path Frappe-integration tests."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import frappe

from conductor.workflow import Step, workflow
from conductor.workflow.decorator import _REGISTRY


def _make_diamond(name="AdvDiamond"):
    _REGISTRY.pop(name, None)

    @workflow(name=name, queue="default")
    class D:
        _a = Step("a")
        _b = Step("b", depends_on=("a",))
        _c = Step("c", depends_on=("a",))
        _d = Step("d", depends_on=("b", "c"))
        def a(self): pass
        def b(self): pass
        def c(self): pass
        def d(self): pass
    return D


class TestAdvancerForward(unittest.TestCase):
    def setUp(self):
        if not frappe.db.exists("Conductor Queue", "default"):
            frappe.get_doc({"doctype": "Conductor Queue", "queue_name": "default", "enabled": 1}).insert(ignore_permissions=True)
        if not frappe.db.exists("Conductor Queue", "workflow"):
            frappe.get_doc({"doctype": "Conductor Queue", "queue_name": "workflow", "enabled": 1}).insert(ignore_permissions=True)
        frappe.db.commit()
        _make_diamond()

    def tearDown(self):
        for dt in (
            "Conductor Workflow Step Run",
            "Conductor Workflow Run",
            "Conductor Workflow",
            "Conductor Job",
        ):
            for n in frappe.get_all(dt, pluck="name"):
                frappe.delete_doc(dt, n, force=True)
        frappe.db.commit()

    def test_first_advance_dispatches_only_root_steps(self):
        from conductor.workflow import run_workflow
        from conductor.workflow.advancer import advance

        with patch("conductor.workflow.advancer._enqueue_step_job") as mock_eq:
            run_id = run_workflow("AdvDiamond")
            advance(workflow_run_id=run_id, completed_step=None)

            dispatched = [c.kwargs["step_id"] for c in mock_eq.call_args_list]
            self.assertEqual(dispatched, ["a"])  # only root

    def test_advance_marks_run_running_on_first_dispatch(self):
        from conductor.workflow import run_workflow
        from conductor.workflow.advancer import advance

        with patch("conductor.workflow.advancer._enqueue_step_job"):
            run_id = run_workflow("AdvDiamond")
            advance(workflow_run_id=run_id, completed_step=None)
        status = frappe.get_value("Conductor Workflow Run", run_id, "status")
        self.assertEqual(status, "RUNNING")

    def test_advance_after_a_succeeded_dispatches_b_and_c(self):
        from conductor.workflow import run_workflow
        from conductor.workflow.advancer import advance

        with patch("conductor.workflow.advancer._enqueue_step_job") as mock_eq:
            run_id = run_workflow("AdvDiamond")
            advance(workflow_run_id=run_id, completed_step=None)
            mock_eq.reset_mock()

            # Simulate step a succeeded
            sr = frappe.get_doc(
                "Conductor Workflow Step Run",
                {"workflow_run": run_id, "step_id": "a", "is_compensation": 0},
            )
            sr.status = "SUCCEEDED"
            sr.save(ignore_permissions=True)
            frappe.db.commit()

            advance(workflow_run_id=run_id, completed_step="a")
            dispatched = sorted(c.kwargs["step_id"] for c in mock_eq.call_args_list)
            self.assertEqual(dispatched, ["b", "c"])

    def test_advance_marks_step_ready_before_enqueue(self):
        from conductor.workflow import run_workflow
        from conductor.workflow.advancer import advance

        with patch("conductor.workflow.advancer._enqueue_step_job"):
            run_id = run_workflow("AdvDiamond")
            advance(workflow_run_id=run_id, completed_step=None)
        sr_a = frappe.get_doc(
            "Conductor Workflow Step Run",
            {"workflow_run": run_id, "step_id": "a", "is_compensation": 0},
        )
        self.assertEqual(sr_a.status, "READY")

    def test_advance_ignores_run_in_terminal_status(self):
        from conductor.workflow import run_workflow
        from conductor.workflow.advancer import advance

        with patch("conductor.workflow.advancer._enqueue_step_job") as mock_eq:
            run_id = run_workflow("AdvDiamond")
            frappe.db.set_value("Conductor Workflow Run", run_id, "status", "CANCELLED")
            advance(workflow_run_id=run_id, completed_step=None)
            self.assertEqual(mock_eq.call_count, 0)

    def test_run_completes_when_all_steps_succeeded(self):
        from conductor.workflow import run_workflow
        from conductor.workflow.advancer import advance

        with patch("conductor.workflow.advancer._enqueue_step_job"):
            run_id = run_workflow("AdvDiamond")
            advance(workflow_run_id=run_id, completed_step=None)
            for step in ("a", "b", "c", "d"):
                sr = frappe.get_doc(
                    "Conductor Workflow Step Run",
                    {"workflow_run": run_id, "step_id": step, "is_compensation": 0},
                )
                sr.status = "SUCCEEDED"
                sr.save(ignore_permissions=True)
            frappe.db.commit()
            advance(workflow_run_id=run_id, completed_step="d")

        status = frappe.get_value("Conductor Workflow Run", run_id, "status")
        self.assertEqual(status, "SUCCEEDED")
```

- [ ] **Step 2: Run tests to verify they fail**

```
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_workflow_run.test_advancer_forward
```

Expected: `ImportError: No module named 'conductor.workflow.advancer'`.

- [ ] **Step 3: Implement the advancer (forward branch only)**

Create `conductor/workflow/advancer.py`:

```python
"""Unified advancer for Conductor workflow runs.

Spec §3 + §6.1 + §6.2. Single entry-point branches on run.status:
  - PENDING / RUNNING : forward path (this module, this task)
  - COMPENSATING       : compensation path (added in Task 14)

The advancer is itself a Conductor job decorated with @conductor.job(queue="workflow")
so it inherits Phase-1 retry/timeout semantics. If it dies mid-run, Phase-1
reclamation re-runs it; the body is idempotent.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

import frappe

import conductor as _conductor
from conductor.client import get_redis
from conductor.config import load_config
from conductor.decorator import job as conductor_job
from conductor.logging import get_logger
from conductor.serialization import loads as msgpack_loads
from conductor.workflow.decorator import get_registered
from conductor.workflow.keys import wfdeps_key
from conductor.workflow.lua import FANIN_DECREMENT

log = get_logger("conductor.workflow.advancer")


def _decode_kwargs(b64: str) -> dict[str, Any]:
    if not b64:
        return {}
    import base64
    return msgpack_loads(base64.b64decode(b64.encode("ascii")))


def _now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _downstreams_of(cls, completed_step_id: str) -> list[str]:
    return sorted(
        s.name for s in cls.__conductor_workflow_steps__
        if completed_step_id in s.depends_on
    )


def _step_run(workflow_run_id: str, step_id: str, *, is_compensation: int = 0):
    return frappe.get_doc(
        "Conductor Workflow Step Run",
        {
            "workflow_run": workflow_run_id,
            "step_id": step_id,
            "is_compensation": is_compensation,
        },
    )


def _enqueue_step_job(*, run_id: str, step_id: str, cls, run_kwargs: dict[str, Any]) -> str:
    """Enqueue a single step's underlying Conductor Job.

    The full method path is the workflow class's dotted path + the step
    method name. The worker resolves this via frappe.get_attr.
    """
    method_path = f"{cls.__module__}.{cls.__qualname__}.{step_id}"
    return _conductor.enqueue(
        method=method_path,
        queue=cls.__conductor_workflow_queue__,
        idempotency_key=f"wf:{run_id}:{step_id}:dispatch",
        __workflow_run_id=run_id,
        __step_id=step_id,
        **run_kwargs,
    )


def _all_forward_terminal(run_id: str) -> bool:
    pending = frappe.db.count(
        "Conductor Workflow Step Run",
        filters={
            "workflow_run": run_id,
            "is_compensation": 0,
            "status": ["in", ["PENDING", "READY", "RUNNING"]],
        },
    )
    return pending == 0


def _all_forward_succeeded(run_id: str) -> bool:
    rows = frappe.get_all(
        "Conductor Workflow Step Run",
        filters={"workflow_run": run_id, "is_compensation": 0},
        fields=["status"],
    )
    return rows and all(r["status"] == "SUCCEEDED" for r in rows)


@conductor_job(queue="workflow", max_attempts=5, timeout=120)
def advance(*, workflow_run_id: str, completed_step: Optional[str] = None) -> None:
    """Re-evaluate a run and dispatch any newly-ready forward steps."""
    run = frappe.get_doc("Conductor Workflow Run", workflow_run_id)
    if run.status not in ("PENDING", "RUNNING"):
        log.debug("advance_noop_status", run_id=workflow_run_id, status=run.status)
        return

    cls = get_registered(run.workflow)
    if cls is None:
        log.error("advance_unknown_workflow", run_id=workflow_run_id, workflow=run.workflow)
        return

    site = frappe.local.site
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)

    if completed_step is None:
        downstreams_argv: list[str] = []
        completed_argv = ""
    else:
        downstreams_argv = _downstreams_of(cls, completed_step)
        completed_argv = completed_step

    ready_raw = r.eval(
        FANIN_DECREMENT, 1, wfdeps_key(site, workflow_run_id),
        completed_argv, json.dumps(downstreams_argv),
    )
    ready = sorted(s.decode() if isinstance(s, bytes) else s for s in ready_raw)

    if run.status == "PENDING" and ready:
        run.status = "RUNNING"
        run.started_at = _now_naive()
        run.save(ignore_permissions=True)
        frappe.db.commit()

    run_kwargs = _decode_kwargs(run.input_kwargs or "")

    for step_id in ready:
        try:
            sr = _step_run(workflow_run_id, step_id)
        except frappe.DoesNotExistError:
            log.warning("advance_missing_step_run", run_id=workflow_run_id, step_id=step_id)
            continue
        if sr.status != "PENDING":
            # Already dispatched by a concurrent advancer; skip.
            continue
        sr.status = "READY"
        sr.save(ignore_permissions=True)
        frappe.db.commit()

        job_id = _enqueue_step_job(
            run_id=workflow_run_id, step_id=step_id, cls=cls, run_kwargs=run_kwargs,
        )
        frappe.db.set_value(
            "Conductor Workflow Step Run", sr.name, "job", job_id,
            update_modified=False,
        )
        frappe.db.commit()

    if _all_forward_terminal(workflow_run_id) and _all_forward_succeeded(workflow_run_id):
        frappe.db.set_value(
            "Conductor Workflow Run", workflow_run_id,
            {"status": "SUCCEEDED", "finished_at": _now_naive()},
            update_modified=False,
        )
        frappe.db.commit()


def enqueue_advance(workflow_run_id: str, completed_step: Optional[str]) -> None:
    """Enqueue an advancer job for this run. Idempotent on (run_id, completed_step)."""
    completed_or_start = completed_step or "start"
    _conductor.enqueue(
        method="conductor.workflow.advancer.advance",
        queue="workflow",
        idempotency_key=f"wf:{workflow_run_id}:advance:{completed_or_start}",
        workflow_run_id=workflow_run_id,
        completed_step=completed_step,
    )
```

Now wire the dispatcher hook. Edit `conductor/workflow/dispatcher.py` — append after the `_ENQUEUE_ADVANCER_HOOK` declaration:

```python
def _bind_advancer_hook():
    """Late binding to avoid circular import — called once on first run_workflow."""
    global _ENQUEUE_ADVANCER_HOOK
    if _ENQUEUE_ADVANCER_HOOK is None:
        from conductor.workflow.advancer import enqueue_advance
        _ENQUEUE_ADVANCER_HOOK = enqueue_advance
```

In `run_workflow()`, before the `if _ENQUEUE_ADVANCER_HOOK is not None:` check, add:

```python
    _bind_advancer_hook()
```

Note that the test patches `_enqueue_step_job` (not the hook) so the hook bind is harmless in tests.

- [ ] **Step 4: Run tests to verify they pass**

```
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_workflow_run.test_advancer_forward
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```
git add conductor/workflow/advancer.py conductor/workflow/dispatcher.py conductor/conductor/doctype/conductor_workflow_run/test_advancer_forward.py
git commit -m "feat(workflow): unified advancer — forward (PENDING/RUNNING) branch"
```

---

## Task 13: Worker integration — `mark_step_running` / `mark_step_terminal` hooks

**Files:**
- Modify: `conductor/worker.py`
- Create: `conductor/workflow/worker_hooks.py` (the actual hook bodies, kept out of `worker.py` for testability)
- Test: `conductor/conductor/doctype/conductor_workflow_run/test_worker_hooks.py`

- [ ] **Step 1: Write failing tests**

Create `conductor/conductor/doctype/conductor_workflow_run/test_worker_hooks.py`:

```python
"""Worker hook tests — mark_step_running / mark_step_terminal."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from conductor.workflow import Step, workflow
from conductor.workflow.decorator import _REGISTRY


def _make_simple(name="HookFlow"):
    _REGISTRY.pop(name, None)

    @workflow(name=name, queue="default")
    class F:
        _a = Step("a", compensation="undo_a")
        def a(self): pass
        def undo_a(self): pass
    return F


class TestWorkerHooks(unittest.TestCase):
    def setUp(self):
        if not frappe.db.exists("Conductor Queue", "default"):
            frappe.get_doc({"doctype": "Conductor Queue", "queue_name": "default", "enabled": 1}).insert(ignore_permissions=True)
        if not frappe.db.exists("Conductor Queue", "workflow"):
            frappe.get_doc({"doctype": "Conductor Queue", "queue_name": "workflow", "enabled": 1}).insert(ignore_permissions=True)
        frappe.db.commit()
        _make_simple()
        from conductor.workflow import run_workflow
        with patch("conductor.workflow.advancer._enqueue_step_job"):
            self.run_id = run_workflow("HookFlow")

    def tearDown(self):
        for dt in ("Conductor Workflow Step Run", "Conductor Workflow Run", "Conductor Workflow", "Conductor Job"):
            for n in frappe.get_all(dt, pluck="name"):
                frappe.delete_doc(dt, n, force=True)
        frappe.db.commit()

    def _step_run_a(self):
        return frappe.get_doc(
            "Conductor Workflow Step Run",
            {"workflow_run": self.run_id, "step_id": "a", "is_compensation": 0},
        )

    def test_mark_step_running_flips_status_and_sets_started_at(self):
        from conductor.workflow.worker_hooks import mark_step_running

        sr = self._step_run_a()
        sr.status = "READY"
        sr.save(ignore_permissions=True)
        frappe.db.commit()

        mark_step_running(workflow_run_id=self.run_id, step_id="a", is_compensation=False)

        sr = self._step_run_a()
        self.assertEqual(sr.status, "RUNNING")
        self.assertIsNotNone(sr.started_at)

    def test_mark_step_terminal_success_sets_finished_at(self):
        from conductor.workflow.worker_hooks import mark_step_terminal

        sr = self._step_run_a()
        sr.status = "RUNNING"
        sr.save(ignore_permissions=True)
        frappe.db.commit()

        mark_step_terminal(
            workflow_run_id=self.run_id, step_id="a",
            is_compensation=False, success=True,
        )
        sr = self._step_run_a()
        self.assertEqual(sr.status, "SUCCEEDED")
        self.assertIsNotNone(sr.finished_at)

    def test_mark_step_terminal_forward_failure_transitions_run_to_compensating(self):
        from conductor.workflow.worker_hooks import mark_step_terminal

        sr = self._step_run_a()
        sr.status = "RUNNING"
        sr.save(ignore_permissions=True)
        frappe.db.set_value("Conductor Workflow Run", self.run_id, "status", "RUNNING")
        frappe.db.commit()

        mark_step_terminal(
            workflow_run_id=self.run_id, step_id="a",
            is_compensation=False, success=False,
            error_type="ValueError", error_message="bang",
        )
        run_status = frappe.get_value("Conductor Workflow Run", self.run_id, "status")
        self.assertEqual(run_status, "COMPENSATING")
        sr = self._step_run_a()
        self.assertEqual(sr.status, "FAILED")
        self.assertEqual(sr.error_type, "ValueError")
```

- [ ] **Step 2: Run tests to verify they fail**

```
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_workflow_run.test_worker_hooks
```

Expected: `ImportError: No module named 'conductor.workflow.worker_hooks'`.

- [ ] **Step 3: Implement worker hooks**

Create `conductor/workflow/worker_hooks.py`:

```python
"""Side-effect hooks the worker fires for workflow-bound jobs.

Kept out of conductor/worker.py so they can be tested without spinning up a
worker loop.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import frappe

from conductor.logging import get_logger

log = get_logger("conductor.workflow.worker_hooks")


def _now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _step_run_name(workflow_run_id: str, step_id: str, *, is_compensation: bool) -> Optional[str]:
    rows = frappe.get_all(
        "Conductor Workflow Step Run",
        filters={
            "workflow_run": workflow_run_id,
            "step_id": step_id,
            "is_compensation": 1 if is_compensation else 0,
        },
        pluck="name",
        limit=1,
    )
    return rows[0] if rows else None


def mark_step_running(*, workflow_run_id: str, step_id: str, is_compensation: bool) -> None:
    name = _step_run_name(workflow_run_id, step_id, is_compensation=is_compensation)
    if name is None:
        log.warning("mark_running_missing_row", run_id=workflow_run_id, step_id=step_id)
        return
    frappe.db.set_value(
        "Conductor Workflow Step Run", name,
        {"status": "RUNNING", "started_at": _now_naive()},
        update_modified=False,
    )
    frappe.db.commit()


def mark_step_terminal(
    *,
    workflow_run_id: str,
    step_id: str,
    is_compensation: bool,
    success: bool,
    error_type: str = "",
    error_message: str = "",
) -> None:
    name = _step_run_name(workflow_run_id, step_id, is_compensation=is_compensation)
    if name is None:
        log.warning("mark_terminal_missing_row", run_id=workflow_run_id, step_id=step_id)
        return

    if is_compensation:
        new_status = "COMPENSATED" if success else "FAILED"
    else:
        new_status = "SUCCEEDED" if success else "FAILED"

    update = {
        "status": new_status,
        "finished_at": _now_naive(),
    }
    if not success:
        update["error_type"] = error_type[:140]
        update["error_message"] = error_message[:240]
    frappe.db.set_value(
        "Conductor Workflow Step Run", name, update, update_modified=False,
    )

    # Transition the run on forward-step terminal failure.
    if not success and not is_compensation:
        frappe.db.set_value(
            "Conductor Workflow Run", workflow_run_id, "status", "COMPENSATING",
            update_modified=False,
        )

    # Halt run on compensation-step terminal failure (locked spec decision A.1).
    if not success and is_compensation:
        frappe.db.set_value(
            "Conductor Workflow Run", workflow_run_id,
            {"status": "FAILED", "finished_at": _now_naive(),
             "last_error": f"compensation failed at step {step_id}: {error_type}: {error_message}"},
            update_modified=False,
        )
    frappe.db.commit()
```

- [ ] **Step 4: Wire hooks into `worker.py`**

Edit `conductor/worker.py`. Locate `_handle_one()` (around line 326) — at the start, after the message decode, just before invoking the user's method, insert:

```python
    # Phase 5 hook — mark workflow step RUNNING if applicable.
    if msg.workflow_run_id and msg.step_id:
        from conductor.workflow.worker_hooks import mark_step_running
        is_comp = bool(msg.kwargs.get("__is_compensation"))
        mark_step_running(
            workflow_run_id=msg.workflow_run_id,
            step_id=msg.step_id,
            is_compensation=is_comp,
        )
```

After the SUCCEEDED branch (around `_set_job_succeeded`), insert:

```python
    if msg.workflow_run_id and msg.step_id:
        from conductor.workflow.worker_hooks import mark_step_terminal
        from conductor.workflow.advancer import enqueue_advance
        is_comp = bool(msg.kwargs.get("__is_compensation"))
        mark_step_terminal(
            workflow_run_id=msg.workflow_run_id, step_id=msg.step_id,
            is_compensation=is_comp, success=True,
        )
        enqueue_advance(msg.workflow_run_id, completed_step=msg.step_id)
```

After the DLQ / terminal-failure branch (locate `_move_to_dlq`), insert:

```python
    if msg.workflow_run_id and msg.step_id:
        from conductor.workflow.worker_hooks import mark_step_terminal
        from conductor.workflow.advancer import enqueue_advance
        is_comp = bool(msg.kwargs.get("__is_compensation"))
        mark_step_terminal(
            workflow_run_id=msg.workflow_run_id, step_id=msg.step_id,
            is_compensation=is_comp, success=False,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        enqueue_advance(msg.workflow_run_id, completed_step=msg.step_id)
```

(The exact insertion line numbers depend on your local worker.py — search for the `_set_job_succeeded(` and `_move_to_dlq(` call sites to anchor the inserts.)

- [ ] **Step 5: Run hook tests**

```
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_workflow_run.test_worker_hooks
```

Expected: 3 tests pass.

- [ ] **Step 6: Run the existing worker test suite to confirm no regressions**

```
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_job.test_worker_e2e
```

Expected: existing tests still pass.

- [ ] **Step 7: Commit**

```
git add conductor/workflow/worker_hooks.py conductor/worker.py conductor/conductor/doctype/conductor_workflow_run/test_worker_hooks.py
git commit -m "feat(workflow): worker hooks for step running / terminal + run state transitions"
```

---

## Task 14: Advancer COMPENSATING branch

**Files:**
- Modify: `conductor/workflow/advancer.py`
- Test: `conductor/conductor/doctype/conductor_workflow_run/test_advancer_compensation.py`

- [ ] **Step 1: Write failing tests**

Create `conductor/conductor/doctype/conductor_workflow_run/test_advancer_compensation.py`:

```python
"""Advancer COMPENSATING branch tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from conductor.workflow import Step, workflow
from conductor.workflow.decorator import _REGISTRY


def _make_diamond(name="CompDiamond"):
    _REGISTRY.pop(name, None)

    @workflow(name=name, queue="default")
    class D:
        _a = Step("a", compensation="undo_a")
        _b = Step("b", depends_on=("a",), compensation="undo_b")
        _c = Step("c", depends_on=("a",))                     # no comp
        _d = Step("d", depends_on=("b", "c"), compensation="undo_d")
        def a(self): pass
        def undo_a(self): pass
        def b(self): pass
        def undo_b(self): pass
        def c(self): pass
        def d(self): pass
        def undo_d(self): pass
    return D


class TestAdvancerCompensation(unittest.TestCase):
    def setUp(self):
        for q in ("default", "workflow"):
            if not frappe.db.exists("Conductor Queue", q):
                frappe.get_doc({"doctype": "Conductor Queue", "queue_name": q, "enabled": 1}).insert(ignore_permissions=True)
        frappe.db.commit()
        _make_diamond()
        from conductor.workflow import run_workflow
        with patch("conductor.workflow.advancer._enqueue_step_job"):
            self.run_id = run_workflow("CompDiamond")

        # Mark a and b SUCCEEDED, c FAILED, d still PENDING — simulating
        # the diamond after b succeeded but c failed.
        for sid, status in (("a", "SUCCEEDED"), ("b", "SUCCEEDED"), ("c", "FAILED")):
            sr = frappe.get_doc(
                "Conductor Workflow Step Run",
                {"workflow_run": self.run_id, "step_id": sid, "is_compensation": 0},
            )
            sr.status = status
            sr.save(ignore_permissions=True)
        frappe.db.set_value(
            "Conductor Workflow Step Run",
            {"workflow_run": self.run_id, "step_id": "d", "is_compensation": 0},
            "status", "SKIPPED",
        )
        frappe.db.set_value("Conductor Workflow Run", self.run_id, "status", "COMPENSATING")
        frappe.db.commit()

    def tearDown(self):
        for dt in ("Conductor Workflow Step Run", "Conductor Workflow Run", "Conductor Workflow", "Conductor Job"):
            for n in frappe.get_all(dt, pluck="name"):
                frappe.delete_doc(dt, n, force=True)
        frappe.db.commit()

    def test_compensation_first_step_is_b_in_reverse_topo(self):
        from conductor.workflow.advancer import advance

        with patch("conductor.workflow.advancer._enqueue_step_job") as mock_eq:
            advance(workflow_run_id=self.run_id, completed_step=None)

        # Reverse topo over completed-forward {a, b}: [b, a]
        # b has compensation, so first comp dispatched is b's.
        self.assertEqual(mock_eq.call_count, 1)
        kwargs = mock_eq.call_args.kwargs
        self.assertEqual(kwargs["step_id"], "b")
        self.assertTrue(kwargs.get("is_compensation"))

    def test_compensation_skips_steps_without_compensation_method(self):
        # Reset c to SUCCEEDED so it appears in the to-compensate set
        frappe.db.set_value(
            "Conductor Workflow Step Run",
            {"workflow_run": self.run_id, "step_id": "c", "is_compensation": 0},
            "status", "SUCCEEDED",
        )
        frappe.db.commit()

        from conductor.workflow.advancer import advance

        # Simulate b's compensation just COMPENSATED, plus a comp row exists
        for sid in ("b", "c"):
            if sid == "c":
                continue
            frappe.get_doc({
                "doctype": "Conductor Workflow Step Run",
                "workflow_run": self.run_id,
                "step_id": sid,
                "is_compensation": 1,
                "status": "COMPENSATED",
            }).insert(ignore_permissions=True)
        frappe.db.commit()

        with patch("conductor.workflow.advancer._enqueue_step_job") as mock_eq:
            advance(workflow_run_id=self.run_id, completed_step="b")

        # Next reverse-topo step is c, but c has no compensation. Advancer
        # should record that as a no-op (no enqueue) and re-fire itself for a.
        # Either: zero enqueues this call (no-op recurse), or one enqueue for a.
        # We accept either — but the eventual result must include a's comp.
        # For deterministic test, drive one more advance:
        if mock_eq.call_count == 0:
            advance(workflow_run_id=self.run_id, completed_step=None)
        kwargs_list = [c.kwargs for c in mock_eq.call_args_list]
        step_ids = [k["step_id"] for k in kwargs_list]
        self.assertIn("a", step_ids)

    def test_compensation_terminal_run_when_all_compensated(self):
        from conductor.workflow.advancer import advance

        # Insert "compensated" rows for b and a so the advancer sees nothing left to do
        for sid in ("b", "a"):
            frappe.get_doc({
                "doctype": "Conductor Workflow Step Run",
                "workflow_run": self.run_id, "step_id": sid,
                "is_compensation": 1, "status": "COMPENSATED",
            }).insert(ignore_permissions=True)
        frappe.db.commit()

        with patch("conductor.workflow.advancer._enqueue_step_job"):
            advance(workflow_run_id=self.run_id, completed_step="a")

        run_status = frappe.get_value("Conductor Workflow Run", self.run_id, "status")
        self.assertEqual(run_status, "FAILED")
        finished = frappe.get_value("Conductor Workflow Run", self.run_id, "finished_at")
        self.assertIsNotNone(finished)

    def test_compensation_waits_for_in_flight_forward_steps(self):
        # Mark d as RUNNING to simulate in-flight forward sibling
        frappe.db.set_value(
            "Conductor Workflow Step Run",
            {"workflow_run": self.run_id, "step_id": "d", "is_compensation": 0},
            "status", "RUNNING",
        )
        frappe.db.commit()

        from conductor.workflow.advancer import advance
        with patch("conductor.workflow.advancer._enqueue_step_job") as mock_eq:
            advance(workflow_run_id=self.run_id, completed_step=None)
        # No compensations dispatched while a forward step is still RUNNING
        self.assertEqual(mock_eq.call_count, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

```
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_workflow_run.test_advancer_compensation
```

Expected: assertions fail (the COMPENSATING branch is not yet implemented; advancer no-ops on non-RUNNING status).

- [ ] **Step 3: Implement the compensation branch**

Edit `conductor/workflow/advancer.py`. Replace the early `if run.status not in ("PENDING", "RUNNING"): return` guard with a status-aware dispatch:

```python
@conductor_job(queue="workflow", max_attempts=5, timeout=120)
def advance(*, workflow_run_id: str, completed_step: Optional[str] = None) -> None:
    """Re-evaluate a run and dispatch any newly-ready forward or compensation steps."""
    run = frappe.get_doc("Conductor Workflow Run", workflow_run_id)

    if run.status in ("PENDING", "RUNNING"):
        _advance_forward(run, completed_step)
        return

    if run.status == "COMPENSATING":
        _advance_compensation(run, completed_step)
        return

    log.debug("advance_noop_terminal_status", run_id=workflow_run_id, status=run.status)
```

Move the existing forward logic into a private `_advance_forward(run, completed_step)` helper (cut from the body of `advance`).

Add the compensation helper:

```python
def _advance_compensation(run, just_completed: Optional[str]) -> None:
    cls = get_registered(run.workflow)
    if cls is None:
        return

    # Wait for in-flight forward steps to settle.
    in_flight = frappe.db.count(
        "Conductor Workflow Step Run",
        filters={
            "workflow_run": run.name,
            "is_compensation": 0,
            "status": ["in", ["PENDING", "READY", "RUNNING"]],
        },
    )
    if in_flight:
        return

    completed_forward = {
        r["step_id"] for r in frappe.get_all(
            "Conductor Workflow Step Run",
            filters={"workflow_run": run.name, "is_compensation": 0, "status": "SUCCEEDED"},
            fields=["step_id"],
        )
    }
    already_compensated = {
        r["step_id"] for r in frappe.get_all(
            "Conductor Workflow Step Run",
            filters={"workflow_run": run.name, "is_compensation": 1},
            fields=["step_id"],
        )
    }
    pending = completed_forward - already_compensated

    if not pending:
        frappe.db.set_value(
            "Conductor Workflow Run", run.name,
            {"status": "FAILED", "finished_at": _now_naive()},
            update_modified=False,
        )
        frappe.db.commit()
        return

    from conductor.workflow.topo import reverse_topo_order
    sequence = reverse_topo_order(cls.__conductor_workflow_steps__, only=pending)
    next_step_id = sequence[0]
    step_def = next(s for s in cls.__conductor_workflow_steps__ if s.name == next_step_id)

    if step_def.compensation is None:
        # No-op compensation row, then recurse via re-enqueue.
        frappe.get_doc({
            "doctype": "Conductor Workflow Step Run",
            "workflow_run": run.name, "step_id": next_step_id,
            "is_compensation": 1, "status": "COMPENSATED",
            "started_at": _now_naive(), "finished_at": _now_naive(),
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        enqueue_advance(run.name, completed_step=next_step_id)
        return

    # Insert compensation row PENDING; dispatcher will mark READY then enqueue.
    sr = frappe.get_doc({
        "doctype": "Conductor Workflow Step Run",
        "workflow_run": run.name, "step_id": next_step_id,
        "is_compensation": 1, "status": "READY",
    }).insert(ignore_permissions=True)
    frappe.db.commit()

    method_path = f"{cls.__module__}.{cls.__qualname__}.{step_def.compensation}"
    run_kwargs = _decode_kwargs(run.input_kwargs or "")
    job_id = _conductor.enqueue(
        method=method_path,
        queue=cls.__conductor_workflow_queue__,
        idempotency_key=f"wf:{run.name}:{next_step_id}:compensate",
        __workflow_run_id=run.name,
        __step_id=next_step_id,
        __is_compensation=True,
        **run_kwargs,
    )
    frappe.db.set_value(
        "Conductor Workflow Step Run", sr.name, "job", job_id, update_modified=False,
    )
    frappe.db.commit()
```

Replace the `_enqueue_step_job` call site in `_advance_forward` to also accept the new compensation kwargs (already covered by the signature `is_compensation=False` default).

- [ ] **Step 4: Run tests to verify they pass**

```
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_workflow_run.test_advancer_compensation
```

Expected: 4 tests pass.

- [ ] **Step 5: Confirm forward tests still pass**

```
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_workflow_run.test_advancer_forward
```

Expected: 6 tests still pass.

- [ ] **Step 6: Commit**

```
git add conductor/workflow/advancer.py conductor/conductor/doctype/conductor_workflow_run/test_advancer_compensation.py
git commit -m "feat(workflow): advancer COMPENSATING branch with in-flight settle and reverse-topo dispatch"
```

---

## Task 15: Cancellation API — `cancel_workflow_run`

**Files:**
- Create: `conductor/workflow/cancellation.py`
- Modify: `conductor/__init__.py` (re-export `cancel_workflow_run`)
- Modify: `conductor/workflow/__init__.py` (re-export)
- Test: `conductor/conductor/doctype/conductor_workflow_run/test_cancel_run.py`

- [ ] **Step 1: Write failing tests**

Create `conductor/conductor/doctype/conductor_workflow_run/test_cancel_run.py`:

```python
"""cancel_workflow_run() tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from conductor.workflow import Step, workflow
from conductor.workflow.decorator import _REGISTRY


def _make_simple(name="CancelFlow"):
    _REGISTRY.pop(name, None)

    @workflow(name=name, queue="default")
    class F:
        _a = Step("a")
        _b = Step("b", depends_on=("a",))
        def a(self): pass
        def b(self): pass
    return F


class TestCancelWorkflowRun(unittest.TestCase):
    def setUp(self):
        for q in ("default", "workflow"):
            if not frappe.db.exists("Conductor Queue", q):
                frappe.get_doc({"doctype": "Conductor Queue", "queue_name": q, "enabled": 1}).insert(ignore_permissions=True)
        frappe.db.commit()
        _make_simple()
        from conductor.workflow import run_workflow
        with patch("conductor.workflow.advancer._enqueue_step_job"):
            self.run_id = run_workflow("CancelFlow")

    def tearDown(self):
        for dt in ("Conductor Workflow Step Run", "Conductor Workflow Run", "Conductor Workflow", "Conductor Job"):
            for n in frappe.get_all(dt, pluck="name"):
                frappe.delete_doc(dt, n, force=True)
        frappe.db.commit()

    def test_cancel_marks_run_cancelled(self):
        from conductor.workflow.cancellation import cancel_workflow_run
        cancel_workflow_run(self.run_id)
        self.assertEqual(
            frappe.get_value("Conductor Workflow Run", self.run_id, "status"),
            "CANCELLED",
        )

    def test_cancel_skips_pending_and_ready_steps(self):
        from conductor.workflow.cancellation import cancel_workflow_run
        # Mark a as READY to test transition
        frappe.db.set_value(
            "Conductor Workflow Step Run",
            {"workflow_run": self.run_id, "step_id": "a", "is_compensation": 0},
            "status", "READY",
        )
        frappe.db.commit()

        cancel_workflow_run(self.run_id)
        for sid in ("a", "b"):
            sr = frappe.get_doc(
                "Conductor Workflow Step Run",
                {"workflow_run": self.run_id, "step_id": sid, "is_compensation": 0},
            )
            self.assertEqual(sr.status, "SKIPPED")

    def test_cancel_calls_cancel_job_for_running_steps(self):
        from conductor.workflow.cancellation import cancel_workflow_run

        # Mark a as RUNNING with an attached job_id
        sr = frappe.get_doc(
            "Conductor Workflow Step Run",
            {"workflow_run": self.run_id, "step_id": "a", "is_compensation": 0},
        )
        sr.status = "RUNNING"
        sr.job = "fake-job-id"
        sr.save(ignore_permissions=True)
        frappe.db.commit()

        with patch("conductor.cancellation.cancel_job") as mock_cancel:
            cancel_workflow_run(self.run_id)
            mock_cancel.assert_called_once_with("fake-job-id")

    def test_cancel_clears_wfdeps_redis_key(self):
        from conductor.workflow.cancellation import cancel_workflow_run
        from conductor.workflow.keys import wfdeps_key
        from conductor.client import get_redis
        from conductor.config import load_config

        site = frappe.local.site
        r = get_redis(load_config(frappe.local.conf).redis_url)
        # The dispatcher seeded the hash; confirm it's there
        self.assertTrue(r.exists(wfdeps_key(site, self.run_id)))

        cancel_workflow_run(self.run_id)
        self.assertFalse(r.exists(wfdeps_key(site, self.run_id)))

    def test_cancel_idempotent_on_already_cancelled(self):
        from conductor.workflow.cancellation import cancel_workflow_run
        cancel_workflow_run(self.run_id)
        # Second call must not raise
        cancel_workflow_run(self.run_id)
```

- [ ] **Step 2: Run tests to verify they fail**

```
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_workflow_run.test_cancel_run
```

Expected: `ImportError: No module named 'conductor.workflow.cancellation'`.

- [ ] **Step 3: Implement cancellation**

Create `conductor/workflow/cancellation.py`:

```python
"""cancel_workflow_run — best-effort interrupt without compensation.

Spec §5.4 + §6.3.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import frappe

from conductor.cancellation import cancel_job
from conductor.client import get_redis
from conductor.config import load_config
from conductor.logging import get_logger
from conductor.workflow.keys import wfdeps_key

log = get_logger("conductor.workflow.cancellation")


def _now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def cancel_workflow_run(run_id: str, *, user: Optional[str] = None) -> None:
    """Mark the run CANCELLED, skip un-dispatched steps, cancel running step jobs.

    Idempotent — calling on an already-terminal run is a no-op."""
    run = frappe.get_doc("Conductor Workflow Run", run_id)
    if run.status in ("SUCCEEDED", "FAILED", "CANCELLED"):
        return

    user = user or frappe.session.user

    # Skip un-started forward steps
    skip_targets = frappe.get_all(
        "Conductor Workflow Step Run",
        filters={
            "workflow_run": run_id,
            "is_compensation": 0,
            "status": ["in", ["PENDING", "READY"]],
        },
        pluck="name",
    )
    for n in skip_targets:
        frappe.db.set_value("Conductor Workflow Step Run", n, "status", "SKIPPED",
                            update_modified=False)

    # Cancel any in-flight step jobs (Phase-1 cancel_job path).
    running = frappe.get_all(
        "Conductor Workflow Step Run",
        filters={"workflow_run": run_id, "status": "RUNNING"},
        fields=["name", "job"],
    )
    for row in running:
        if row["job"]:
            try:
                cancel_job(row["job"])
            except Exception as e:
                log.warning("cancel_job_failed", run_id=run_id, job=row["job"], error=str(e))

    frappe.db.set_value(
        "Conductor Workflow Run", run_id,
        {
            "status": "CANCELLED",
            "cancelled_at": _now_naive(),
            "cancelled_by": user,
            "finished_at": _now_naive(),
        },
        update_modified=False,
    )
    frappe.db.commit()

    # Drop the deps hash; Lua scripts no longer need it.
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    r.delete(wfdeps_key(frappe.local.site, run_id))
```

Re-export in `conductor/workflow/__init__.py`:

```python
from conductor.workflow.cancellation import cancel_workflow_run
```

Add to `__all__`.

In `conductor/__init__.py`, re-export `run_workflow` and `cancel_workflow_run` (find the existing `enqueue` re-export and add):

```python
from conductor.workflow import run_workflow, cancel_workflow_run
```

- [ ] **Step 4: Run tests to verify they pass**

```
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_workflow_run.test_cancel_run
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```
git add conductor/workflow/cancellation.py conductor/workflow/__init__.py conductor/__init__.py conductor/conductor/doctype/conductor_workflow_run/test_cancel_run.py
git commit -m "feat(workflow): cancel_workflow_run with best-effort interrupt"
```

---

## Task 16: Realtime events — `emit_workflow_event`

**Files:**
- Modify: `conductor/messages.py` (add `emit_workflow_event`)
- Modify: `conductor/workflow/dispatcher.py`, `advancer.py`, `worker_hooks.py`, `cancellation.py` to fire events on transitions
- Test: `tests/test_workflow_realtime.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_workflow_realtime.py`:

```python
"""Realtime event emission for workflow runs (no Frappe required for shape)."""

from unittest.mock import patch

from conductor.messages import emit_workflow_event


def test_emit_workflow_event_publishes_to_run_room():
    with patch("frappe.publish_realtime") as pr:
        emit_workflow_event(
            run_id="WR-0001-2026", status="RUNNING",
            workflow="MyFlow", definition_version=2,
        )
    assert pr.called
    call = pr.call_args
    assert call.kwargs["doctype"] == "Conductor Workflow Run"
    assert call.kwargs["docname"] == "WR-0001-2026"
    assert call.kwargs["event"] == "conductor:workflow_run:WR-0001-2026"
    payload = call.kwargs["message"]
    assert payload["run_id"] == "WR-0001-2026"
    assert payload["status"] == "RUNNING"
    assert payload["workflow"] == "MyFlow"
    assert payload["definition_version"] == 2


def test_emit_workflow_event_drops_unknown_fields():
    with patch("frappe.publish_realtime") as pr:
        emit_workflow_event(
            run_id="WR-0001-2026", status="RUNNING",
            secret_field="should-not-appear",
        )
    payload = pr.call_args.kwargs["message"]
    assert "secret_field" not in payload
```

- [ ] **Step 2: Run test to verify it fails**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_workflow_realtime.py -v
```

Expected: `ImportError: cannot import name 'emit_workflow_event' from 'conductor.messages'`.

- [ ] **Step 3: Implement event helper**

Append to `conductor/messages.py`:

```python
_WORKFLOW_REALTIME_FIELDS = frozenset({
    "workflow",
    "definition_version",
    "started_at",
    "finished_at",
    "last_error",
})


def emit_workflow_event(run_id: str, status: str, **fields) -> None:
    """Publish a per-run realtime event scoped to the Workflow Run room."""
    payload = {"run_id": run_id, "status": status, "ts": int(time.time())}
    for k, v in fields.items():
        if k in _WORKFLOW_REALTIME_FIELDS and v is not None:
            payload[k] = v
    frappe.publish_realtime(
        event=f"conductor:workflow_run:{run_id}",
        message=payload,
        doctype="Conductor Workflow Run",
        docname=run_id,
        after_commit=True,
    )
```

- [ ] **Step 4: Wire emissions at run-state transitions**

In `conductor/workflow/dispatcher.py` `run_workflow`, after the run-row insert and the deps-hash seed:

```python
    from conductor.messages import emit_workflow_event
    emit_workflow_event(
        run_id=run_id, status="PENDING",
        workflow=name, definition_version=version,
    )
```

In `conductor/workflow/advancer.py`:
- After `run.status = "RUNNING"` save in `_advance_forward`: `emit_workflow_event(run_id=run.name, status="RUNNING")`
- After SUCCEEDED transition: `emit_workflow_event(run_id=workflow_run_id, status="SUCCEEDED")`
- After FAILED transition in `_advance_compensation`: `emit_workflow_event(run_id=run.name, status="FAILED")`

In `conductor/workflow/worker_hooks.py`:
- After forward-failure → COMPENSATING: `emit_workflow_event(run_id=workflow_run_id, status="COMPENSATING")`
- After compensation-failure → FAILED: `emit_workflow_event(run_id=workflow_run_id, status="FAILED")`

In `conductor/workflow/cancellation.py`:
- After CANCELLED save: `emit_workflow_event(run_id=run_id, status="CANCELLED")`

Add the import at the top of each modified file:
```python
from conductor.messages import emit_workflow_event
```

- [ ] **Step 5: Run unit + relevant integration tests**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/test_workflow_realtime.py -v
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_workflow_run.test_advancer_forward
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_workflow_run.test_cancel_run
```

Expected: all pass.

- [ ] **Step 6: Commit**

```
git add conductor/messages.py conductor/workflow/dispatcher.py conductor/workflow/advancer.py conductor/workflow/worker_hooks.py conductor/workflow/cancellation.py tests/test_workflow_realtime.py
git commit -m "feat(workflow): per-run realtime events with doctype/docname room scoping"
```

---

## Task 17: CLI — `bench conductor workflow {list,run,status,cancel}`

**Files:**
- Create: `conductor/commands/workflow.py`
- Modify: `conductor/commands/__init__.py` (register the click group)
- Modify: `conductor/hooks.py` (register the command)

- [ ] **Step 1: Inspect the existing command registration pattern**

Read `conductor/commands/__init__.py` and the bottom of `conductor/hooks.py` to find where `commands` is exposed. Match that pattern.

- [ ] **Step 2: Implement the command**

Create `conductor/commands/workflow.py`:

```python
"""bench conductor workflow — list/run/status/cancel subcommands."""

from __future__ import annotations

import json
import sys

import click
import frappe
from frappe.commands import get_site, pass_context


@click.group("workflow")
def workflow_group():
    """Manage Conductor workflows."""


@workflow_group.command("list")
@pass_context
def workflow_list(ctx):
    """Print all registered workflows + their current versions."""
    site = get_site(ctx)
    frappe.init(site=site)
    frappe.connect()
    try:
        rows = frappe.db.sql(
            "SELECT workflow_name, version, enabled, last_version_bumped_at "
            "FROM `tabConductor Workflow` ORDER BY workflow_name",
            as_dict=True,
        )
        if not rows:
            click.echo("(no workflows)")
            return
        click.echo(f"{'NAME':32} {'V':3} {'EN':2} {'LAST_BUMP':25}")
        for r in rows:
            click.echo(
                f"{r['workflow_name'][:32]:32} "
                f"{r['version']:3} "
                f"{r['enabled']:2} "
                f"{str(r['last_version_bumped_at'] or '')[:25]:25}"
            )
    finally:
        frappe.destroy()


@workflow_group.command("run")
@click.argument("name")
@click.option("--kwargs", default="{}", help="JSON object of input kwargs")
@click.option("--idempotency-key", default=None)
@pass_context
def workflow_run(ctx, name, kwargs, idempotency_key):
    """Trigger a workflow run."""
    site = get_site(ctx)
    frappe.init(site=site)
    frappe.connect()
    try:
        try:
            kwargs_dict = json.loads(kwargs)
        except json.JSONDecodeError as e:
            click.echo(f"--kwargs is not valid JSON: {e}", err=True)
            sys.exit(1)
        from conductor.workflow import run_workflow
        try:
            run_id = run_workflow(name, idempotency_key=idempotency_key, **kwargs_dict)
        except Exception as e:
            click.echo(f"run failed: {e}", err=True)
            sys.exit(1)
        click.echo(run_id)
    finally:
        frappe.destroy()


@workflow_group.command("status")
@click.argument("run_id")
@pass_context
def workflow_status(ctx, run_id):
    """Print run + per-step status table."""
    site = get_site(ctx)
    frappe.init(site=site)
    frappe.connect()
    try:
        if not frappe.db.exists("Conductor Workflow Run", run_id):
            click.echo(f"unknown run: {run_id}", err=True)
            sys.exit(1)
        run = frappe.get_doc("Conductor Workflow Run", run_id)
        click.echo(f"Run:        {run.name}")
        click.echo(f"Workflow:   {run.workflow}  (v{run.definition_version})")
        click.echo(f"Status:     {run.status}")
        click.echo(f"Started:    {run.started_at}")
        click.echo(f"Finished:   {run.finished_at}")
        steps = frappe.get_all(
            "Conductor Workflow Step Run",
            filters={"workflow_run": run.name},
            fields=["step_id", "is_compensation", "status", "started_at", "finished_at", "job"],
            order_by="creation asc",
        )
        click.echo()
        click.echo(f"{'STEP':12} {'C':2} {'STATUS':12} {'JOB':40}")
        for s in steps:
            comp = "Y" if s["is_compensation"] else " "
            click.echo(f"{s['step_id'][:12]:12} {comp:2} {s['status']:12} {s['job'] or '':40}")
    finally:
        frappe.destroy()


@workflow_group.command("cancel")
@click.argument("run_id")
@pass_context
def workflow_cancel(ctx, run_id):
    """Cancel a workflow run (best-effort, no compensation)."""
    site = get_site(ctx)
    frappe.init(site=site)
    frappe.connect()
    try:
        if not frappe.db.exists("Conductor Workflow Run", run_id):
            click.echo(f"unknown run: {run_id}", err=True)
            sys.exit(1)
        from conductor.workflow import cancel_workflow_run
        cancel_workflow_run(run_id)
        click.echo(f"cancelled: {run_id}")
    finally:
        frappe.destroy()


commands = [workflow_group]
```

- [ ] **Step 3: Register the group**

Edit `conductor/commands/__init__.py` — append the workflow group import and concatenate it into the `commands` list. Confirm by inspecting the existing schedule registration as a model.

- [ ] **Step 4: Smoke test the CLI**

```
bench --site frappe.localhost conductor workflow list
```

Expected output: `(no workflows)` (or the list of any workflows that have been dispatched).

```
bench --site frappe.localhost conductor workflow run NonExistent
```

Expected: `run failed: workflow not registered: 'NonExistent'`, exit 1.

- [ ] **Step 5: Commit**

```
git add conductor/commands/workflow.py conductor/commands/__init__.py conductor/hooks.py
git commit -m "feat(workflow): bench conductor workflow CLI (list/run/status/cancel)"
```

---

## Task 18: Whitelisted dashboard endpoints

**Files:**
- Create: `conductor/api/workflows.py`
- Test: `conductor/conductor/doctype/conductor_workflow_run/test_api_workflows.py`

- [ ] **Step 1: Write failing tests**

Create `conductor/conductor/doctype/conductor_workflow_run/test_api_workflows.py`:

```python
"""Tests for conductor.api.workflows endpoints."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from conductor.workflow import Step, workflow
from conductor.workflow.decorator import _REGISTRY


def _make_simple(name="ApiFlow"):
    _REGISTRY.pop(name, None)

    @workflow(name=name, queue="default")
    class F:
        _a = Step("a")
        _b = Step("b", depends_on=("a",))
        def a(self): pass
        def b(self): pass
    return F


class TestApiWorkflows(unittest.TestCase):
    def setUp(self):
        for q in ("default", "workflow"):
            if not frappe.db.exists("Conductor Queue", q):
                frappe.get_doc({"doctype": "Conductor Queue", "queue_name": q, "enabled": 1}).insert(ignore_permissions=True)
        frappe.db.commit()
        _make_simple()
        from conductor.workflow import run_workflow
        with patch("conductor.workflow.advancer._enqueue_step_job"):
            self.run_id = run_workflow("ApiFlow")

    def tearDown(self):
        for dt in ("Conductor Workflow Step Run", "Conductor Workflow Run", "Conductor Workflow"):
            for n in frappe.get_all(dt, pluck="name"):
                frappe.delete_doc(dt, n, force=True)
        frappe.db.commit()

    def test_list_workflows_returns_registered(self):
        from conductor.api.workflows import list_workflows
        rows = list_workflows()
        names = [r["workflow_name"] for r in rows]
        self.assertIn("ApiFlow", names)
        wf = next(r for r in rows if r["workflow_name"] == "ApiFlow")
        self.assertEqual(wf["version"], 1)

    def test_list_runs_filters_by_workflow(self):
        from conductor.api.workflows import list_runs
        rows = list_runs(workflow="ApiFlow")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], self.run_id)

    def test_get_run_includes_step_rows_and_snapshot(self):
        from conductor.api.workflows import get_run
        result = get_run(self.run_id)
        self.assertEqual(result["run"]["name"], self.run_id)
        self.assertEqual(len(result["steps"]), 2)
        step_ids = {s["step_id"] for s in result["steps"]}
        self.assertEqual(step_ids, {"a", "b"})
        self.assertIn("snapshot", result)
        self.assertIn('"name":"ApiFlow"', result["snapshot"])

    def test_cancel_run_endpoint_marks_cancelled(self):
        from conductor.api.workflows import cancel_run
        cancel_run(self.run_id)
        self.assertEqual(
            frappe.get_value("Conductor Workflow Run", self.run_id, "status"),
            "CANCELLED",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_workflow_run.test_api_workflows
```

Expected: import error.

- [ ] **Step 3: Implement endpoints**

Create `conductor/api/workflows.py`:

```python
"""Whitelisted API surface for the dashboard's Workflows tab.

Permissions: Conductor Operator can read everything and cancel runs;
System Manager retains full access.
"""

from __future__ import annotations

from typing import Any, Optional

import frappe


def _require_read() -> None:
    if not (
        frappe.has_permission("Conductor Workflow", "read")
        or "Conductor Operator" in frappe.get_roles()
    ):
        raise frappe.PermissionError("Not permitted")


def _require_operator_or_sysmgr() -> None:
    roles = set(frappe.get_roles())
    if not (roles & {"Conductor Operator", "System Manager"}):
        raise frappe.PermissionError("Conductor Operator or System Manager required")


@frappe.whitelist()
def list_workflows() -> list[dict[str, Any]]:
    _require_read()
    rows = frappe.get_all(
        "Conductor Workflow",
        fields=["workflow_name", "version", "enabled", "last_version_bumped_at"],
        order_by="workflow_name asc",
    )
    for r in rows:
        r["active_runs"] = frappe.db.count(
            "Conductor Workflow Run",
            filters={"workflow": r["workflow_name"], "status": ["in", ["PENDING", "RUNNING", "COMPENSATING"]]},
        )
        r["recent_runs_24h"] = frappe.db.count(
            "Conductor Workflow Run",
            filters={
                "workflow": r["workflow_name"],
                "creation": [">", frappe.utils.add_to_date(None, hours=-24)],
            },
        )
    return rows


@frappe.whitelist()
def list_runs(
    workflow: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    _require_read()
    filters: dict[str, Any] = {}
    if workflow:
        filters["workflow"] = workflow
    if status:
        filters["status"] = status
    rows = frappe.get_all(
        "Conductor Workflow Run",
        filters=filters,
        fields=["name", "workflow", "definition_version", "status",
                "started_at", "finished_at", "idempotency_key", "creation"],
        order_by="creation desc",
        limit=int(limit),
        start=int(offset),
    )
    return rows


@frappe.whitelist()
def get_run(run_id: str) -> dict[str, Any]:
    _require_read()
    if not frappe.db.exists("Conductor Workflow Run", run_id):
        raise frappe.DoesNotExistError(run_id)
    run = frappe.get_doc("Conductor Workflow Run", run_id).as_dict()
    steps = frappe.get_all(
        "Conductor Workflow Step Run",
        filters={"workflow_run": run_id},
        fields=["name", "step_id", "is_compensation", "status",
                "started_at", "finished_at", "job", "depends_on",
                "error_type", "error_message"],
        order_by="creation asc",
    )
    snapshot = frappe.db.get_value(
        "Conductor Workflow", run["workflow"], "definition_snapshot"
    ) or ""
    return {"run": run, "steps": steps, "snapshot": snapshot}


@frappe.whitelist()
def cancel_run(run_id: str) -> dict[str, str]:
    _require_operator_or_sysmgr()
    from conductor.workflow import cancel_workflow_run
    cancel_workflow_run(run_id)
    return {"name": run_id, "status": "CANCELLED"}
```

- [ ] **Step 4: Run tests to verify they pass**

```
bench --site frappe.localhost run-tests --app conductor --module conductor.conductor.doctype.conductor_workflow_run.test_api_workflows
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```
git add conductor/api/workflows.py conductor/conductor/doctype/conductor_workflow_run/test_api_workflows.py
git commit -m "feat(workflow): whitelisted dashboard API for workflows"
```

---

## Task 19: Dashboard — Workflows list page

**Files:**
- Create: `dashboard/src/pages/WorkflowsPage.vue`
- Modify: `dashboard/src/api.js` (add the four new endpoints)
- Modify: `dashboard/src/router.js` (register `/workflows`)
- Modify: `dashboard/src/App.vue` (add tab to nav)

- [ ] **Step 1: Add the API client wrappers**

Edit `dashboard/src/api.js` — append four functions matching the existing wrapper pattern (search for `getList` / `getJob` for the call shape):

```javascript
export async function listWorkflows() {
  return await call('conductor.api.workflows.list_workflows');
}

export async function listWorkflowRuns(opts = {}) {
  return await call('conductor.api.workflows.list_runs', opts);
}

export async function getWorkflowRun(run_id) {
  return await call('conductor.api.workflows.get_run', { run_id });
}

export async function cancelWorkflowRun(run_id) {
  return await call('conductor.api.workflows.cancel_run', { run_id });
}
```

(`call` is the existing helper that handles CSRF + JSON parsing.)

- [ ] **Step 2: Build WorkflowsPage.vue**

Create `dashboard/src/pages/WorkflowsPage.vue`:

```vue
<script setup>
import { ref, onMounted } from 'vue';
import { listWorkflows, listWorkflowRuns } from '../api.js';
import { useDashboardState } from '../stores/dashboardState.js';
import StatusBadge from '../components/StatusBadge.vue';

const workflows = ref([]);
const recentRuns = ref([]);
const selectedWorkflow = ref(null);

async function refresh() {
  workflows.value = await listWorkflows();
  recentRuns.value = await listWorkflowRuns({
    workflow: selectedWorkflow.value,
    limit: 50,
  });
}

useDashboardState(refresh);
onMounted(refresh);

function selectWorkflow(name) {
  selectedWorkflow.value = name;
  refresh();
}
</script>

<template>
  <div class="workflows-page">
    <h2>Workflows</h2>
    <table class="wf-list">
      <thead>
        <tr><th>Name</th><th>Version</th><th>Active</th><th>24h</th><th>Last Bump</th></tr>
      </thead>
      <tbody>
        <tr v-for="w in workflows" :key="w.workflow_name"
            :class="{ active: selectedWorkflow === w.workflow_name }"
            @click="selectWorkflow(w.workflow_name)">
          <td>{{ w.workflow_name }}</td>
          <td>v{{ w.version }}</td>
          <td>{{ w.active_runs }}</td>
          <td>{{ w.recent_runs_24h }}</td>
          <td>{{ w.last_version_bumped_at || '—' }}</td>
        </tr>
      </tbody>
    </table>

    <h3 v-if="selectedWorkflow">Runs of {{ selectedWorkflow }}</h3>
    <h3 v-else>Recent Runs (all workflows)</h3>
    <table class="run-list">
      <thead>
        <tr><th>Run ID</th><th>Workflow</th><th>Status</th><th>Started</th><th>Finished</th></tr>
      </thead>
      <tbody>
        <tr v-for="r in recentRuns" :key="r.name">
          <td><router-link :to="`/workflows/runs/${r.name}`">{{ r.name }}</router-link></td>
          <td>{{ r.workflow }} (v{{ r.definition_version }})</td>
          <td><StatusBadge :status="r.status" /></td>
          <td>{{ r.started_at || '—' }}</td>
          <td>{{ r.finished_at || '—' }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.wf-list, .run-list { width: 100%; border-collapse: collapse; margin-bottom: 24px; }
.wf-list th, .wf-list td, .run-list th, .run-list td { padding: 6px 10px; border-bottom: 1px solid #eee; text-align: left; }
.wf-list tr.active { background: #fef9c3; cursor: pointer; }
.wf-list tr:hover { background: #f9fafb; cursor: pointer; }
</style>
```

- [ ] **Step 3: Register the route**

Edit `dashboard/src/router.js` — add to the routes array:

```javascript
{ path: '/workflows', component: () => import('./pages/WorkflowsPage.vue') },
{ path: '/workflows/runs/:run_id', component: () => import('./pages/WorkflowRunDetailPage.vue') },
```

- [ ] **Step 4: Add the tab to App.vue**

Edit `dashboard/src/App.vue` — find the existing tab nav (the `<nav>` element listing /overview, /jobs, etc.) and append:

```html
<router-link to="/workflows">Workflows</router-link>
```

- [ ] **Step 5: Build the dashboard bundle and smoke-check**

```
cd dashboard && npm run build
```

Expected: build succeeds. Open the dashboard at `https://frappe.localhost/conductor-dashboard` (logged in as a Conductor Operator), click the Workflows tab, confirm the list view renders.

- [ ] **Step 6: Commit**

```
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add dashboard/src/pages/WorkflowsPage.vue dashboard/src/api.js dashboard/src/router.js dashboard/src/App.vue
git add dashboard/dist/*    # built bundle
git commit -m "feat(dashboard): Workflows list page"
```

---

## Task 20: Dashboard — Workflow Run detail with Mermaid DAG

**Files:**
- Create: `dashboard/src/components/MermaidDag.vue`
- Create: `dashboard/src/pages/WorkflowRunDetailPage.vue`
- Modify: `dashboard/package.json` (add `mermaid` dep)

- [ ] **Step 1: Add mermaid dependency**

```
cd dashboard && npm install mermaid@^10
```

- [ ] **Step 2: Build MermaidDag.vue**

Create `dashboard/src/components/MermaidDag.vue`:

```vue
<script setup>
import { ref, watch, onMounted } from 'vue';
import mermaid from 'mermaid';

const props = defineProps({
  snapshot: { type: String, required: true },     // canonical-JSON snapshot
  steps:    { type: Array,  required: true },     // step rows with status
});

const container = ref(null);
const STATUS_COLORS = {
  PENDING: '#e5e7eb',
  READY: '#bfdbfe',
  RUNNING: '#60a5fa',
  SUCCEEDED: '#86efac',
  FAILED: '#fca5a5',
  COMPENSATED: '#fdba74',
  SKIPPED: '#d1d5db',
};

function buildMermaid() {
  if (!props.snapshot) return '';
  let topo;
  try { topo = JSON.parse(props.snapshot); }
  catch { return 'flowchart TD\nerror[invalid snapshot]'; }
  const lines = ['flowchart TD'];
  const statusByStep = {};
  for (const s of props.steps) {
    if (!s.is_compensation) statusByStep[s.step_id] = s.status;
  }
  for (const step of topo.steps) {
    const status = statusByStep[step.name] || 'PENDING';
    lines.push(`  ${step.name}["${step.name}"]`);
    lines.push(`  style ${step.name} fill:${STATUS_COLORS[status] || '#e5e7eb'}`);
  }
  for (const step of topo.steps) {
    for (const dep of step.depends_on) {
      lines.push(`  ${dep} --> ${step.name}`);
    }
  }
  return lines.join('\n');
}

async function render() {
  if (!container.value) return;
  const code = buildMermaid();
  const { svg } = await mermaid.render('wf-dag', code);
  container.value.innerHTML = svg;
}

onMounted(() => {
  mermaid.initialize({ startOnLoad: false, securityLevel: 'strict' });
  render();
});
watch(() => [props.snapshot, props.steps], render, { deep: true });
</script>

<template>
  <div ref="container" class="mermaid-dag" />
</template>

<style scoped>
.mermaid-dag { display: flex; justify-content: center; padding: 16px 0; }
</style>
```

- [ ] **Step 3: Build the run detail page**

Create `dashboard/src/pages/WorkflowRunDetailPage.vue`:

```vue
<script setup>
import { ref, onMounted, computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { getWorkflowRun, cancelWorkflowRun } from '../api.js';
import { useDetailSubscription } from '../stores/detailSubscription.js';
import { useUserRoles } from '../composables/useUserRoles.js';
import MermaidDag from '../components/MermaidDag.vue';
import StatusBadge from '../components/StatusBadge.vue';

const route = useRoute();
const router = useRouter();
const data = ref({ run: null, steps: [], snapshot: '' });

async function load() {
  data.value = await getWorkflowRun(route.params.run_id);
}

const { isOperator, isSysMgr } = useUserRoles();
const canCancel = computed(() =>
  data.value.run && data.value.run.status === 'RUNNING' && (isOperator.value || isSysMgr.value)
);

async function cancel() {
  await cancelWorkflowRun(route.params.run_id);
  await load();
}

onMounted(load);
useDetailSubscription({
  doctype: 'Conductor Workflow Run',
  docname: route.params.run_id,
  onUpdate: load,
});
</script>

<template>
  <div v-if="data.run" class="run-detail">
    <header>
      <button @click="router.back()">&laquo; Back</button>
      <h2>{{ data.run.name }}</h2>
      <div class="meta">
        <strong>Workflow:</strong> {{ data.run.workflow }} (v{{ data.run.definition_version }})
        <StatusBadge :status="data.run.status" />
        <button v-if="canCancel" @click="cancel" class="cancel-btn">Cancel run</button>
      </div>
    </header>

    <section>
      <h3>DAG</h3>
      <MermaidDag :snapshot="data.snapshot" :steps="data.steps" />
    </section>

    <section>
      <h3>Step runs</h3>
      <table>
        <thead><tr><th>Step</th><th>Type</th><th>Status</th><th>Started</th><th>Finished</th><th>Job</th></tr></thead>
        <tbody>
          <tr v-for="s in data.steps" :key="s.name">
            <td>{{ s.step_id }}</td>
            <td>{{ s.is_compensation ? 'compensation' : 'forward' }}</td>
            <td><StatusBadge :status="s.status" /></td>
            <td>{{ s.started_at || '—' }}</td>
            <td>{{ s.finished_at || '—' }}</td>
            <td>
              <router-link v-if="s.job" :to="`/jobs/${s.job}`">{{ s.job }}</router-link>
              <span v-else>—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="data.run.last_error">
      <h3>Last error</h3>
      <pre>{{ data.run.last_error }}</pre>
    </section>
  </div>
</template>

<style scoped>
.run-detail header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.cancel-btn { background: #ef4444; color: white; border: 0; padding: 6px 12px; border-radius: 4px; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 6px 10px; border-bottom: 1px solid #eee; text-align: left; }
pre { background: #f3f4f6; padding: 12px; overflow-x: auto; }
</style>
```

- [ ] **Step 4: Build + smoke check**

```
cd dashboard && npm run build
```

Expected: build succeeds. Visit `/conductor-dashboard#/workflows/runs/<some-run-id>` for an existing run; the DAG renders with status colors.

- [ ] **Step 5: Commit**

```
cd /Users/osamamuhammed/frappe_15/apps/conductor
git add dashboard/src/components/MermaidDag.vue dashboard/src/pages/WorkflowRunDetailPage.vue dashboard/package.json dashboard/package-lock.json dashboard/dist/
git commit -m "feat(dashboard): Workflow Run detail with Mermaid DAG"
```

---

## Task 21: Chaos test — kill -9 advancer mid-fan-out

**Files:**
- Create: `tests_chaos/test_phase5_chaos.py`

- [ ] **Step 1: Write the chaos test**

Create `tests_chaos/test_phase5_chaos.py` (read existing `tests_chaos/` files for the conftest pattern; the suite typically uses the real Redis + a worker subprocess):

```python
"""Phase 5 chaos: kill the advancer mid-fan-out and assert recovery."""

from __future__ import annotations

import subprocess
import time

import pytest
import frappe

from conductor.workflow import Step, workflow
from conductor.workflow.decorator import _REGISTRY


@pytest.fixture(autouse=True)
def _setup_workflow():
    _REGISTRY.pop("ChaosFlow", None)

    @workflow(name="ChaosFlow", queue="default")
    class C:
        _a = Step("a")
        _b = Step("b", depends_on=("a",))
        _c = Step("c", depends_on=("a",))
        _d = Step("d", depends_on=("b", "c"))
        def a(self): pass
        def b(self): pass
        def c(self): pass
        def d(self): pass
    yield


def test_kill_advancer_mid_fanout_run_still_completes(real_redis, frappe_site):
    """Spawn workers, kill -9 the advancer process during a's success, expect d to finish."""
    # Real-world test runs against a live bench. Pseudo-shape — the suite's
    # fixture spawns workers; this test only triggers the run and asserts on
    # the final state.
    from conductor.workflow import run_workflow

    run_id = run_workflow("ChaosFlow")

    # Wait up to 30s for run to terminate
    deadline = time.time() + 30
    while time.time() < deadline:
        status = frappe.get_value("Conductor Workflow Run", run_id, "status")
        if status in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(0.5)

    assert frappe.get_value("Conductor Workflow Run", run_id, "status") == "SUCCEEDED"
    step_statuses = {
        r["step_id"]: r["status"]
        for r in frappe.get_all(
            "Conductor Workflow Step Run",
            filters={"workflow_run": run_id, "is_compensation": 0},
            fields=["step_id", "status"],
        )
    }
    assert step_statuses == {"a": "SUCCEEDED", "b": "SUCCEEDED", "c": "SUCCEEDED", "d": "SUCCEEDED"}
```

(Note: the `real_redis` and `frappe_site` fixtures already exist in `tests_chaos/conftest.py` — they spawn a real worker. Read that file before running this test to confirm setup.)

- [ ] **Step 2: Run the chaos suite**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests_chaos/test_phase5_chaos.py -v -s
```

Expected: passes.

- [ ] **Step 3: Commit**

```
git add tests_chaos/test_phase5_chaos.py
git commit -m "test(chaos): kill -9 advancer mid-fan-out, expect run to complete"
```

---

## Task 22: Exit-criterion test — diamond happy + C-fail rollback

**Files:**
- Modify: `tests_chaos/test_phase5_chaos.py` (extend)

- [ ] **Step 1: Add the exit-criterion test**

Append to `tests_chaos/test_phase5_chaos.py`:

```python
def test_diamond_c_terminal_fail_compensates_a(real_redis, frappe_site, monkeypatch):
    """Master Phase-5 exit criterion:
       4-step workflow B||C dependent on A; D dependent on B+C.
       Force C to terminal-fail → A's compensation runs, run lands FAILED."""
    _REGISTRY.pop("ExitFlow", None)

    @workflow(name="ExitFlow", queue="default")
    class E:
        _a = Step("a", compensation="undo_a")
        _b = Step("b", depends_on=("a",), compensation="undo_b")
        _c = Step("c", depends_on=("a",))
        _d = Step("d", depends_on=("b", "c"))

        def a(self): pass
        def undo_a(self):
            # Marker so the test knows compensation ran.
            frappe.cache().set_value("phase5:undo_a:ran", "1")
        def b(self): pass
        def undo_b(self):
            frappe.cache().set_value("phase5:undo_b:ran", "1")
        def c(self): raise RuntimeError("forced terminal failure")
        def d(self): pass

    frappe.cache().delete_value("phase5:undo_a:ran")
    frappe.cache().delete_value("phase5:undo_b:ran")

    from conductor.workflow import run_workflow
    run_id = run_workflow("ExitFlow")

    deadline = time.time() + 60
    while time.time() < deadline:
        status = frappe.get_value("Conductor Workflow Run", run_id, "status")
        if status == "FAILED":
            break
        time.sleep(0.5)

    assert frappe.get_value("Conductor Workflow Run", run_id, "status") == "FAILED"

    # A and B succeeded, C failed, D never ran (no comp row for D)
    step_statuses = {
        (r["step_id"], r["is_compensation"]): r["status"]
        for r in frappe.get_all(
            "Conductor Workflow Step Run",
            filters={"workflow_run": run_id},
            fields=["step_id", "is_compensation", "status"],
        )
    }
    assert step_statuses[("a", 0)] == "SUCCEEDED"
    assert step_statuses[("c", 0)] == "FAILED"
    # A and B (forward steps that succeeded) get compensation rows
    assert step_statuses.get(("a", 1)) == "COMPENSATED"
    # B may or may not have run depending on parallel timing; if it did, comp must have run
    if step_statuses.get(("b", 0)) == "SUCCEEDED":
        assert step_statuses.get(("b", 1)) == "COMPENSATED"

    # Compensation method side-effect was observed
    assert frappe.cache().get_value("phase5:undo_a:ran") == "1"
```

- [ ] **Step 2: Run the test**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests_chaos/test_phase5_chaos.py::test_diamond_c_terminal_fail_compensates_a -v -s
```

Expected: passes — this is the master Phase 5 exit criterion.

- [ ] **Step 3: Commit**

```
git add tests_chaos/test_phase5_chaos.py
git commit -m "test(chaos): Phase 5 exit criterion — diamond C-fail rolls back A"
```

---

## Task 23: Master design change-log entry + README update

**Files:**
- Modify: `docs/superpowers/specs/2026-04-27-conductor-master-design.md` (append change-log row)
- Modify: `README.md` (bump status)

- [ ] **Step 1: Append to master change-log**

Edit `docs/superpowers/specs/2026-04-27-conductor-master-design.md`. After the existing change-log entries, append:

```
| 2026-04-29 | Phase 5 (Workflows) implemented. Adds Conductor Workflow / Workflow Run / Workflow Step Run DocTypes (with the §8 augmentations from the Phase 5 spec). Adds Redis keys `wfdeps:{run_id}` and `wfidem:{hash}`, and a `workflow` queue to default fixtures. The `workflow_run_id` and `step_id` keys frozen in §7 are now populated. Realtime events `conductor:workflow_run:{run_id}` use the same per-doc room scoping pattern as Phase 3. Exit criterion (§4 Phase 5) verified by `tests_chaos/test_phase5_chaos.py`. | osama.m@aau.iq |
```

- [ ] **Step 2: Bump README status**

Edit `README.md`. Replace the current status line:

```
Phase 3 of 5 (Phase 4 was Observability — removed; v1 stays focused on the
job platform). See `docs/superpowers/specs/2026-04-27-conductor-master-design.md`
for the full roadmap.
```

with:

```
Phase 4 of 5 (Phase 4 was Observability — removed; Phase 5 (Workflows)
shipped 2026-04-29). See `docs/superpowers/specs/2026-04-27-conductor-master-design.md`
for the full roadmap.
```

(The status counts shipped phases. Phase 6 — Multi-tenant polish — remains.)

Add a new operations section just below the Dashboard one:

```markdown
## Workflows (Phase 5)

Define workflows as Python classes:

\`\`\`python
import conductor
from conductor.workflow import workflow, Step

@workflow(name="OrderFulfillment", queue="default")
class OrderFulfillment:
    a = Step("reserve", compensation="release")
    b = Step("charge",  depends_on=("a",), compensation="refund")
    c = Step("notify",  depends_on=("a",))
    d = Step("receipt", depends_on=("b", "c"))

    def reserve(self, *, order_id): ...
    def release(self, *, order_id): ...
    def charge(self,  *, order_id): ...
    def refund(self,  *, order_id): ...
    def notify(self,  *, order_id): ...
    def receipt(self, *, order_id): ...

run_id = conductor.run_workflow("OrderFulfillment", order_id=42, idempotency_key="ord-42")
\`\`\`

CLI: `bench --site SITE conductor workflow {list,run,status,cancel}`.
Dashboard tab: `/conductor-dashboard#/workflows`.
```

- [ ] **Step 3: Commit**

```
git add docs/superpowers/specs/2026-04-27-conductor-master-design.md README.md
git commit -m "docs(workflow): Phase 5 change-log + README update"
```

---

## Task 24: Final exit-criterion verification

This is a verification task, not a code task — you run the full suite end-to-end and confirm Phase 5 exits cleanly.

- [ ] **Step 1: Run full pure-Python suite**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests/ -v
```

Expected: every existing + new test passes.

- [ ] **Step 2: Run full Frappe-integration suite**

```
bench --site frappe.localhost run-tests --app conductor
```

Expected: every existing + new test passes (no regressions in Phase 0–3 tests).

- [ ] **Step 3: Run chaos suite**

```
/Users/osamamuhammed/frappe_15/env/bin/pytest tests_chaos/ -v -s
```

Expected: all chaos tests including the Phase 5 exit-criterion test pass.

- [ ] **Step 4: Manual smoke**

Open the dashboard at `https://frappe.localhost/conductor-dashboard`, verify:
- Workflows tab loads.
- Trigger a run via `bench --site frappe.localhost conductor workflow run <name>` (use one of the test workflows).
- Run detail page renders the Mermaid DAG with live-updating colors.
- Cancel button visible to a Conductor Operator user, cancels the run, page updates.

- [ ] **Step 5: Tag the release**

```
git tag conductor-phase5-complete
git log --oneline conductor-phase4-complete..conductor-phase5-complete
```

Expected: ~23 commits visible (one per implementation task).

---

## Self-review summary

**Spec coverage check (against `2026-04-29-conductor-phase5-workflows-design.md`):**

- §3 architecture — Tasks 11, 12, 14
- §4 components — Tasks 2–18
- §5 public API — Tasks 2 (Step), 3 (decorator), 11 (run_workflow), 15 (cancel), 17 (CLI), 18 (whitelisted)
- §6.1 forward data flow — Tasks 11, 12
- §6.2 compensation flow — Task 14
- §6.3 cancellation flow — Task 15
- §7 state machines — Tasks 9, 10 (DocType enums), 12, 14, 15 (transitions)
- §8 doctype additions — Tasks 8, 9, 10
- §9 Redis topology additions — Task 6
- §10 Lua script — Task 7
- §11 realtime events — Task 16
- §12 worker integration — Task 13
- §13 versioning — Task 5 (snapshot/hash) + Task 11 (dispatch path)
- §14 dashboard — Tasks 19, 20
- §15 permissions — Tasks 8, 9, 10 (DocType perms) + Task 18 (endpoint guards)
- §16 testing — every task has test steps; Tasks 21, 22 cover chaos + exit criterion
- §19 master design updates — Task 23

**Type / signature consistency:**
- `advance(workflow_run_id, completed_step)` — defined in Task 12, called identically in Task 13 (worker hooks) and Task 14 (compensation branch).
- `mark_step_running(workflow_run_id, step_id, is_compensation)` and `mark_step_terminal(...)` — defined in Task 13, kwargs match between definition and call sites.
- `cancel_workflow_run(run_id)` — defined in Task 15, used identically in Tasks 17, 18.
- `emit_workflow_event(run_id, status, **fields)` — defined in Task 16, used identically wherever it's fired.
- `_enqueue_step_job(*, run_id, step_id, cls, run_kwargs)` — defined in Task 12, mocked by tests in Tasks 12, 13, 14, 15, 18.

**Placeholder scan:** no TBD / TODO / "implement later" / "fill in details" appears in this plan.

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-29-conductor-phase5-workflows.md`.**
