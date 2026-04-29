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
