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
