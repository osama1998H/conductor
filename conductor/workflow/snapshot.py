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
