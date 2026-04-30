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
    W2 = _make_diamond_class("W_hash1")
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
        def a(self): return 99
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
