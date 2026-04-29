"""bench conductor dlq {list,retry,discard} — operational subcommands over
Conductor DLQ Entry rows. retry/discard live here too but are added in
Task 14."""

from __future__ import annotations

import click
import frappe


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
@click.option("--site", required=True, help="Frappe site name.")
@click.option("--queue", default=None, help="Filter to one queue.")
@click.option("--status", "status",
              type=click.Choice(["PENDING_REVIEW", "RETRIED", "DISCARDED"]),
              default=None, help="Filter by review status.")
@click.option("--limit", default=50, type=int, help="Max rows to print.")
def list_command(site, queue, status, limit):
    """List DLQ entries, newest first."""
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
