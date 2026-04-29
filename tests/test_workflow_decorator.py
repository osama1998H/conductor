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
