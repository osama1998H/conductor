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
    """Return one cycle as a list of step names, or None if the DAG is acyclic."""
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
    """Return step names in reverse topological order. If `only` is given, return only those."""
    steps_t = tuple(steps)
    by_name = {s.name: s for s in steps_t}
    forward: list[str] = []
    color: dict[str, int] = defaultdict(int)

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
