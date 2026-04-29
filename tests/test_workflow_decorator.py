"""Pure-Python tests for @conductor.workflow + Step dataclass (no Frappe required)."""

import pytest

from conductor.workflow import Step, WorkflowDefinitionError, workflow
from conductor.workflow.decorator import _REGISTRY


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


def _clear_registry():
    _REGISTRY.clear()


def test_decorator_registers_class_under_name():
    _clear_registry()

    @workflow(name="W1", queue="default")
    class W1:
        _a = Step("step_a")

        def step_a(self):
            pass

    assert _REGISTRY["W1"] is W1
    assert W1.__conductor_workflow_name__ == "W1"
    assert W1.__conductor_workflow_queue__ == "default"


def test_decorator_raises_on_step_without_method():
    _clear_registry()
    with pytest.raises(WorkflowDefinitionError, match="step_a"):

        @workflow(name="W2", queue="default")
        class W2:
            _a = Step("step_a")
            # no step_a method


def test_decorator_raises_on_unknown_compensation_method():
    _clear_registry()
    with pytest.raises(WorkflowDefinitionError, match="undo_a"):

        @workflow(name="W3", queue="default")
        class W3:
            _a = Step("step_a", compensation="undo_a")

            def step_a(self):
                pass


def test_decorator_raises_on_unknown_dependency():
    _clear_registry()
    with pytest.raises(WorkflowDefinitionError, match="depends_on.*missing"):

        @workflow(name="W4", queue="default")
        class W4:
            _a = Step("step_a", depends_on=("missing",))

            def step_a(self):
                pass


def test_decorator_raises_on_duplicate_step_name():
    _clear_registry()
    with pytest.raises(WorkflowDefinitionError, match="duplicate"):

        @workflow(name="W5", queue="default")
        class W5:
            _a = Step("step_x")
            _b = Step("step_x")

            def step_x(self):
                pass


def test_decorator_raises_on_redefining_workflow_name():
    _clear_registry()

    @workflow(name="W6", queue="default")
    class W6a:
        _a = Step("a")

        def a(self):
            pass

    with pytest.raises(WorkflowDefinitionError, match="already registered"):

        @workflow(name="W6", queue="default")
        class W6b:
            _a = Step("a")

            def a(self):
                pass


def test_decorator_exposes_steps_in_declaration_order():
    _clear_registry()

    @workflow(name="W7", queue="default")
    class W7:
        _a = Step("a")
        _b = Step("b", depends_on=("a",))

        def a(self):
            pass

        def b(self):
            pass

    steps = W7.__conductor_workflow_steps__
    # Sorted by step name for determinism — see snapshot.py rationale.
    assert [s.name for s in steps] == ["a", "b"]
