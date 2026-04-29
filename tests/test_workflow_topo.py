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
    rev = reverse_topo_order(_steps_diamond())
    assert rev[0] == "d"
    assert rev[-1] == "a"
    assert set(rev[1:3]) == {"b", "c"}


def test_reverse_topo_filtered_subset():
    completed = {"a", "c"}
    rev = reverse_topo_order(_steps_diamond(), only=completed)
    assert rev == ["c", "a"]


def test_reverse_topo_empty_subset_returns_empty():
    assert reverse_topo_order(_steps_diamond(), only=set()) == []
