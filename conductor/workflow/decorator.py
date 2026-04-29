"""@conductor.workflow class decorator + Step dataclass + in-process registry."""

from __future__ import annotations

from dataclasses import dataclass
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

        from conductor.workflow.topo import detect_cycle  # avoid circular import at module load
        cycle = detect_cycle(steps_by_attr.values())
        if cycle:
            raise WorkflowDefinitionError(
                f"workflow {name} has a dependency cycle: {' → '.join(cycle)}"
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
