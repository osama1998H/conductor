"""run_workflow() — entry point for triggering a workflow run.

Spec §6.1 (forward dispatch flow) and §13 (versioning algorithm).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

import frappe

from conductor.client import get_redis
from conductor.config import load_config
from conductor.logging import get_logger
from conductor.serialization import dumps as msgpack_dumps
from conductor.workflow.decorator import get_registered
from conductor.workflow.idempotency import acquire_wfidem_lock
from conductor.workflow.keys import wfdeps_key
from conductor.workflow.snapshot import snapshot_from_class, topology_hash
from conductor.workflow.topo import in_degrees

log = get_logger("conductor.workflow.dispatcher")

_DEFAULT_WFIDEM_TTL = 86_400  # 24h, mirrors job idempotency

# Hook set by Task 12 (advancer module). Left as None here so dispatch is
# testable without the advancer.
_ENQUEUE_ADVANCER_HOOK: Optional[Callable[[str, Optional[str]], None]] = None


def _bind_advancer_hook():
    """Late binding to avoid circular import — called once on first run_workflow."""
    global _ENQUEUE_ADVANCER_HOOK
    if _ENQUEUE_ADVANCER_HOOK is None:
        from conductor.workflow.advancer import enqueue_advance
        _ENQUEUE_ADVANCER_HOOK = enqueue_advance


class WorkflowNotFoundError(Exception):
    pass


def _b64encode_kwargs(d: dict[str, Any]) -> str:
    if not d:
        return ""
    import base64
    return base64.b64encode(msgpack_dumps(d)).decode("ascii")


def _bump_or_insert_workflow_row(cls: type) -> int:
    name = cls.__conductor_workflow_name__
    snap = snapshot_from_class(cls)

    if not frappe.db.exists("Conductor Workflow", name):
        frappe.get_doc({
            "doctype": "Conductor Workflow",
            "workflow_name": name,
            "enabled": 1,
            "definition_path": f"{cls.__module__}.{cls.__qualname__}",
            "version": 1,
            "definition_snapshot": snap,
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        return 1

    row = frappe.get_doc("Conductor Workflow", name)
    if row.definition_snapshot == snap:
        return int(row.version)
    row.version = int(row.version) + 1
    row.definition_snapshot = snap
    row.definition_path = f"{cls.__module__}.{cls.__qualname__}"
    row.last_version_bumped_at = datetime.now(timezone.utc).replace(tzinfo=None)
    row.save(ignore_permissions=True)
    frappe.db.commit()
    log.info("workflow_version_bumped", workflow=name, new_version=row.version)
    return int(row.version)


def _insert_step_runs(run_id: str, cls: type) -> None:
    import json
    for step in cls.__conductor_workflow_steps__:
        frappe.get_doc({
            "doctype": "Conductor Workflow Step Run",
            "workflow_run": run_id,
            "step_id": step.name,
            "is_compensation": 0,
            "status": "PENDING",
            "depends_on": json.dumps(list(step.depends_on)),
        }).insert(ignore_permissions=True)
    frappe.db.commit()


def _seed_deps_hash(redis_client, site: str, run_id: str, cls: type) -> None:
    deps = in_degrees(cls.__conductor_workflow_steps__)
    if deps:
        redis_client.hset(
            wfdeps_key(site, run_id),
            mapping={k: str(v) for k, v in deps.items()},
        )


def run_workflow(
    name: str,
    *,
    idempotency_key: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """Trigger a workflow run. Returns the (new or idempotent-existing) run_id."""
    cls = get_registered(name)
    if cls is None:
        raise WorkflowNotFoundError(f"workflow not registered: {name!r}")

    site = frappe.local.site
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)

    version = _bump_or_insert_workflow_row(cls)

    run_id_placeholder = frappe.generate_hash(length=10)
    if idempotency_key:
        ttl = int(
            (frappe.local.conf.get("conductor") or {}).get(
                "wfidem_ttl_seconds", _DEFAULT_WFIDEM_TTL
            )
        )
        existing = acquire_wfidem_lock(
            r, site, idempotency_key, run_id_placeholder, ttl=ttl
        )
        if existing is not None:
            log.info(
                "workflow_idempotency_hit",
                workflow=name, idem_key=idempotency_key, existing_run_id=existing,
            )
            return existing

    run_doc = frappe.get_doc({
        "doctype": "Conductor Workflow Run",
        "workflow": name,
        "definition_version": version,
        "status": "PENDING",
        "site": site,
        "input_args": "",
        "input_kwargs": _b64encode_kwargs(kwargs),
        "idempotency_key": idempotency_key or "",
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    run_id = run_doc.name

    _insert_step_runs(run_id, cls)
    _seed_deps_hash(r, site, run_id, cls)

    if idempotency_key:
        # Replace the placeholder in the idem key with the real run_id, so
        # idempotent re-dispatches return the right id.
        from conductor.workflow.keys import wfidem_key as _kfn
        r.set(_kfn(site, idempotency_key), run_id, ex=_DEFAULT_WFIDEM_TTL, xx=True)

    _bind_advancer_hook()
    if _ENQUEUE_ADVANCER_HOOK is not None:
        _ENQUEUE_ADVANCER_HOOK(run_id, None)

    return run_id
