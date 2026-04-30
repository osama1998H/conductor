"""RQ -> Conductor one-shot migration logic.

Public entry point: `migrate_from_rq(site, *, queue_map, commit=False,
force=False) -> MigrationReport`.

Test seams (keyword-only, optional, default to real implementations):
    _redis_client      - Redis client; default = conductor's standard one.
    _rq_pending_jobs   - () -> iterable of (rq_job, rq_origin_queue_name)
                         tuples OR plain rq_job objects (rq_job.origin is
                         the source queue name).
    _enqueue           - conductor.enqueue replacement, default = real one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional


_MARKER_KEY_PATTERN = "conductor:{site}:rq_migrated_at"


@dataclass
class MigrationReport:
    site: str
    plan: list[dict] = field(default_factory=list)  # dry-run preview rows
    moved: int = 0
    skipped_other_site: int = 0
    skipped_callable_method: int = 0
    skipped_due_to_marker: bool = False
    failed: int = 0
    unmapped_queues_seen: dict[str, int] = field(default_factory=dict)


def _default_redis_client():
    import frappe
    from conductor.client import get_redis
    from conductor.config import load_config
    cfg = load_config(frappe.local.conf)
    return get_redis(cfg.redis_url)


def _default_rq_pending_jobs() -> Iterable[tuple]:
    """Walk all Frappe RQ pending registries for the current bench's Redis,
    yielding (rq_job, origin_queue_name) tuples. Started/failed/scheduled
    registries are skipped."""
    from frappe.utils.background_jobs import (
        generate_qname,
        get_queues_timeout,
        get_redis_conn,
    )
    import rq
    conn = get_redis_conn()
    for qtype in get_queues_timeout().keys():
        qname = generate_qname(qtype)
        q = rq.Queue(qname, connection=conn)
        for jid in q.job_ids:
            try:
                job = rq.job.Job.fetch(jid, connection=conn)
            except Exception:
                continue
            yield (job, qtype)


def _default_enqueue(method: str, *, queue: str, **kwargs) -> str:
    import conductor
    return conductor.enqueue(method, queue=queue, **kwargs)


def _normalize_pending_jobs(it) -> list[tuple]:
    """Accept either iterable of (job, origin) tuples or iterable of jobs
    (with `.origin`). Always returns list of (job, origin)."""
    out: list[tuple] = []
    for entry in it:
        if isinstance(entry, tuple) and len(entry) == 2:
            out.append(entry)
        else:
            origin = getattr(entry, "origin", "default")
            out.append((entry, origin))
    return out


def migrate_from_rq(
    site: str,
    *,
    queue_map: dict[str, str],
    commit: bool,
    force: bool,
    _redis_client=None,
    _rq_pending_jobs: Optional[Callable] = None,
    _enqueue: Optional[Callable] = None,
) -> MigrationReport:
    rep = MigrationReport(site=site)

    r = _redis_client if _redis_client is not None else _default_redis_client()
    fetch = _rq_pending_jobs if _rq_pending_jobs is not None else _default_rq_pending_jobs
    enq = _enqueue if _enqueue is not None else _default_enqueue

    marker_key = _MARKER_KEY_PATTERN.format(site=site)
    if r.get(marker_key) is not None and not force:
        rep.skipped_due_to_marker = True
        return rep

    pending = _normalize_pending_jobs(fetch())

    for job, origin in pending:
        kw = getattr(job, "kwargs", {}) or {}
        if kw.get("site") != site:
            rep.skipped_other_site += 1
            continue
        method = kw.get("method")
        if not isinstance(method, str):
            rep.skipped_callable_method += 1
            continue

        target_queue = queue_map.get(origin)
        if target_queue is None:
            rep.unmapped_queues_seen[origin] = rep.unmapped_queues_seen.get(origin, 0) + 1
            target_queue = "default"

        rep.plan.append({
            "rq_job_id": job.id,
            "rq_queue": origin,
            "method": method,
            "target_queue": target_queue,
        })

        if not commit:
            continue

        try:
            new_id = enq(method, queue=target_queue, **(kw.get("kwargs") or {}))
            try:
                job.delete()
            except Exception:
                # Worst case: we enqueued but couldn't delete from RQ. Log,
                # increment failed, keep going. Operator must clean up.
                rep.failed += 1
                continue
            rep.moved += 1
            rep.plan[-1]["new_job_id"] = new_id
        except Exception:
            rep.failed += 1

    if commit and (rep.moved > 0 or rep.skipped_other_site > 0 or rep.unmapped_queues_seen):
        r.set(marker_key, datetime.now(timezone.utc).isoformat())

    return rep
