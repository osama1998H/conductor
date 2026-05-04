"""bench conductor dlq {list,retry,discard} — operational subcommands over
Conductor DLQ Entry rows."""

from __future__ import annotations

import base64
from datetime import datetime

import click
import frappe
from frappe.commands import get_site, pass_context

from conductor.serialization import loads as msgpack_loads
from conductor.worker import now_naive


def _connect_to_site(site: str) -> None:
    frappe.init(site=site)
    frappe.connect()


def _disconnect() -> None:
    frappe.destroy()


def _fetch_dlq_rows(filters: dict, limit: int) -> list[dict]:
    """Return DLQ Entry rows matching `filters`, newest first, capped at `limit`."""
    return frappe.get_all(
        "Conductor DLQ Entry",
        filters=filters or None,
        fields=["name", "job", "queue", "moved_at", "last_error_type",
                "last_error_message", "status"],
        order_by="moved_at desc",
        limit_page_length=limit,
    )


@click.group("dlq")
def dlq_group():
    """Operational subcommands over Conductor DLQ Entry rows."""


@dlq_group.command("list")
@click.option("--site", default=None,
              help="Frappe site name. Defaults to the bench --site context.")
@click.option("--queue", default=None, help="Filter to one queue.")
@click.option("--status", "status",
              type=click.Choice(["PENDING_REVIEW", "RETRIED", "DISCARDED"]),
              default=None, help="Filter by review status.")
@click.option("--limit", default=50, type=int, help="Max rows to print.")
@pass_context
def list_command(ctx, site, queue, status, limit):
    """List DLQ entries, newest first."""
    site = site or get_site(ctx)
    filters: dict = {}
    if queue:
        filters["queue"] = queue
    if status:
        filters["status"] = status
    _connect_to_site(site)
    try:
        rows = _fetch_dlq_rows(filters, limit)
    finally:
        _disconnect()

    if not rows:
        click.echo("No DLQ entries match.")
        return
    headers = ["name", "job", "queue", "moved_at", "last_error_type", "last_error_message"]
    widths = [max(len(h), 10) for h in headers]
    for r in rows:
        for i, k in enumerate(headers):
            widths[i] = max(widths[i], len(str(r.get(k, "") or "")[:60]))
    sep = "  "
    click.echo(sep.join(h.ljust(w) for h, w in zip(headers, widths)))
    click.echo(sep.join("-" * w for w in widths))
    for r in rows:
        cells = [str(r.get(h, "") or "")[:60] for h in headers]
        click.echo(sep.join(c.ljust(w) for c, w in zip(cells, widths)))


def _fetch_pending_rows(filters: dict, limit: int, job_id: str | None) -> list[dict]:
    """Find PENDING_REVIEW rows matching filters, optionally pinned to one job_id.
    Joins through Conductor Job to retrieve `method`, `args`, `kwargs`."""
    if job_id:
        return frappe.db.sql(
            """SELECT d.name, d.job, d.queue, d.status,
                       j.method, j.args, j.kwargs
               FROM `tabConductor DLQ Entry` d
               JOIN `tabConductor Job` j ON j.name = d.job
               WHERE d.status='PENDING_REVIEW' AND d.job=%s
               LIMIT 1""",
            (job_id,), as_dict=True,
        )
    f = ["d.status='PENDING_REVIEW'"]
    args: list = []
    if filters.get("queue"):
        f.append("d.queue=%s")
        args.append(filters["queue"])
    sql = (
        "SELECT d.name, d.job, d.queue, d.status, j.method, j.args, j.kwargs "
        "FROM `tabConductor DLQ Entry` d "
        "JOIN `tabConductor Job` j ON j.name = d.job "
        f"WHERE {' AND '.join(f)} "
        "ORDER BY d.moved_at DESC LIMIT %s"
    )
    args.append(limit)
    return frappe.db.sql(sql, tuple(args), as_dict=True)


def _enqueue_from_dlq_row(method: str, *, queue: str, **kwargs) -> str:
    """Indirection so tests can spy on it."""
    import conductor
    return conductor.enqueue(method, queue=queue, **kwargs)


def _get_actor() -> str:
    """Return the current Frappe session user, or 'system' if Frappe is
    not connected (e.g., CliRunner tests). Robust to missing frappe.session."""
    try:
        return frappe.session.user  # type: ignore[union-attr]
    except Exception:
        return "system"


def _decode_kwargs(b64: str) -> dict:
    if not b64:
        return {}
    return msgpack_loads(base64.b64decode(b64.encode("ascii")))


def _mark_dlq_row(name: str, payload: dict) -> None:
    frappe.db.set_value("Conductor DLQ Entry", name, payload, update_modified=False)
    frappe.db.commit()


@dlq_group.command("retry")
@click.option("--site", default=None,
              help="Frappe site name. Defaults to the bench --site context.")
@click.option("--queue", default=None)
@click.option("--limit", default=50, type=int)
@click.option("--job", "job_id", default=None,
              help="Operate on this specific job_id only.")
@pass_context
def retry_command(ctx, site, queue, limit, job_id):
    """Re-enqueue PENDING_REVIEW DLQ entries via conductor.enqueue and mark
    each row RETRIED."""
    site = site or get_site(ctx)
    filters = {"queue": queue} if queue else {}
    _connect_to_site(site)
    try:
        rows = _fetch_pending_rows(filters, limit, job_id)
        if not rows:
            click.echo("No PENDING_REVIEW DLQ entries match.")
            return
        moved = 0
        for r in rows:
            try:
                kwargs = _decode_kwargs(r.get("kwargs") or "")
                new_id = _enqueue_from_dlq_row(r["method"], queue=r["queue"], **kwargs)
                _mark_dlq_row(r["name"], {
                    "status": "RETRIED",
                    "reviewed_by": _get_actor(),
                    "reviewed_at": now_naive().replace(microsecond=0),
                })
                moved += 1
                click.echo(f"  retried {r['name']} (job {r['job']} -> {new_id})")
            except Exception as e:
                click.echo(f"  FAILED {r['name']}: {type(e).__name__}: {e}", err=True)
        click.echo(f"\nRetried {moved} of {len(rows)} entries.")
    finally:
        _disconnect()


@dlq_group.command("discard")
@click.option("--site", default=None,
              help="Frappe site name. Defaults to the bench --site context.")
@click.option("--queue", default=None)
@click.option("--limit", default=50, type=int)
@click.option("--job", "job_id", default=None)
@pass_context
def discard_command(ctx, site, queue, limit, job_id):
    """Mark PENDING_REVIEW DLQ entries DISCARDED without re-enqueuing."""
    site = site or get_site(ctx)
    filters = {"queue": queue} if queue else {}
    _connect_to_site(site)
    try:
        rows = _fetch_pending_rows(filters, limit, job_id)
        if not rows:
            click.echo("No PENDING_REVIEW DLQ entries match.")
            return
        for r in rows:
            _mark_dlq_row(r["name"], {
                "status": "DISCARDED",
                "reviewed_by": _get_actor(),
                "reviewed_at": now_naive().replace(microsecond=0),
            })
            click.echo(f"  discarded {r['name']}")
        click.echo(f"\nDiscarded {len(rows)} entries.")
    finally:
        _disconnect()
