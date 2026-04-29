"""@conductor.workflow class decorator + Step dataclass + in-process registry."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Iterable


class WorkflowDefinitionError(ValueError):
    """Raised at decoration time when a workflow class is malformed."""


def _to_tuple(deps: Iterable[str] | None) -> tuple[str, ...]:
    if deps is None:
        return ()
    return tuple(deps)


_PENDING_STEPS_BY_FRAME: dict[int, list["Step"]] = {}  # Frame ID -> list of Step objects created


@dataclass(frozen=True)
class Step:
    name: str
    depends_on: tuple[str, ...] = ()
    compensation: str | None = None

    def __post_init__(self) -> None:
        # Normalize lists/sets to tuples without breaking frozen semantics.
        if not isinstance(self.depends_on, tuple):
            object.__setattr__(self, "depends_on", _to_tuple(self.depends_on))

        # Track this step in the current frame for later class creation
        frame = sys._getframe(1)
        frame_id = id(frame)

        # Store pending steps by frame
        if frame_id not in _PENDING_STEPS_BY_FRAME:
            _PENDING_STEPS_BY_FRAME[frame_id] = []
        _PENDING_STEPS_BY_FRAME[frame_id].append(self)

    def __set_name__(self, owner: type, name: str) -> None:
        """Called when the Step is assigned as a class attribute.

        Store the Step in a registry so it can be recovered later
        even if a method with the same name shadows it.
        """
        # Use a module-level registry to avoid class dict issues
        _STEP_REGISTRY.setdefault(id(owner), {})[name] = self


# ============================================================================
# Task 3: @workflow decorator + class-level validation + registry
# ============================================================================

_REGISTRY: dict[str, type] = {}
_STEP_REGISTRY: dict[int, dict[str, Step]] = {}  # id(class) -> {attr_name: Step}


class _WorkflowBase:
    """Base class that enables Step tracking via __init_subclass__."""

    __conductor_workflow_steps_found__: dict[str, Step]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Scan the MRO for Step instances in bases and capture them
        steps_found: dict[str, Step] = {}

        # Walk through the class hierarchy to find all Step descriptors
        for base in reversed(cls.__mro__[:-1]):  # Skip object
            for attr_name, attr_value in vars(base).items():
                if isinstance(attr_value, Step):
                    steps_found[attr_name] = attr_value

        # Store found steps
        if steps_found:
            _STEP_REGISTRY[id(cls)] = steps_found


class _WorkflowNamespace(dict):
    """Custom namespace for class creation that captures Step instances before shadowing."""

    def __init__(self) -> None:
        super().__init__()
        self._captured_steps: dict[str, Step] = {}

    def __setitem__(self, key: str, value: Any) -> None:
        # Capture any Step assignments
        if isinstance(value, Step):
            self._captured_steps[key] = value
        super().__setitem__(key, value)


class _WorkflowMeta(type):
    """Metaclass that preserves Step instances even when shadowed by methods."""

    @classmethod
    def __prepare__(mcs, name: str, bases: tuple, **kwargs: Any) -> dict:
        return _WorkflowNamespace()

    def __new__(
        mcs, name: str, bases: tuple, namespace: dict, **kwargs: Any
    ) -> type:
        # Extract steps before the class is created
        captured_steps: dict[str, Step] = {}
        if isinstance(namespace, _WorkflowNamespace):
            captured_steps = namespace._captured_steps

        cls = super().__new__(mcs, name, bases, dict(namespace), **kwargs)

        # Store captured steps on the class
        if captured_steps:
            _STEP_REGISTRY[id(cls)] = captured_steps

        return cls


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

    Can be applied to classes with or without the _WorkflowMeta metaclass,
    but works best when used with @workflow on classes that will naturally
    use the metaclass during their definition.
    """

    def decorate(cls: type) -> type:
        if name in _REGISTRY:
            raise WorkflowDefinitionError(
                f"workflow name {name!r} already registered by {_REGISTRY[name]!r}"
            )

        # Retrieve steps from multiple sources, in priority order:
        # 1. From _STEP_REGISTRY (populated by __set_name__ if steps weren't shadowed)
        cls_id = id(cls)
        steps_by_attr = _STEP_REGISTRY.get(cls_id, {})

        # 2. From pending steps tracked during Step.__post_init__ for the frame where class was created
        # The decorator is called from a frame one level up from where the class was created.
        # The class was created in a frame two levels up from here (decorator -> test -> class body).
        if not steps_by_attr:
            # Get the frame where the decorator was called (typically at class decoration time)
            decorator_frame = sys._getframe(1)
            # Look for pending steps in the class definition frame or its parent
            class_def_frame_id = id(decorator_frame)

            if class_def_frame_id in _PENDING_STEPS_BY_FRAME:
                pending_list = _PENDING_STEPS_BY_FRAME[class_def_frame_id]
            else:
                # If not found, search through all frames with pending steps
                # and find the one that matches this class
                pending_list = None
                frames_to_delete = []
                for frame_id, plist in list(_PENDING_STEPS_BY_FRAME.items()):
                    # For each pending step, check if there's a matching method on the class
                    matching = {}
                    for step_obj in plist:
                        # The attribute name matches the step name
                        if callable(getattr(cls, step_obj.name, None)):
                            matching[step_obj.name] = step_obj
                    if matching:
                        pending_list = matching
                        frames_to_delete.append(frame_id)

                # Clean up the frames we matched
                for fid in frames_to_delete:
                    del _PENDING_STEPS_BY_FRAME[fid]
                steps_by_attr = pending_list or {}

            if pending_list and not isinstance(pending_list, dict):
                # Convert list to dict if needed
                steps_by_attr = {step.name: step for step in pending_list}
                # Clean up
                if class_def_frame_id in _PENDING_STEPS_BY_FRAME:
                    del _PENDING_STEPS_BY_FRAME[class_def_frame_id]

        # 3. Final fallback: look for Step instances still in vars()
        if not steps_by_attr:
            steps_by_attr = {
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
    """Retrieve a registered workflow class by name."""
    return _REGISTRY.get(name)
