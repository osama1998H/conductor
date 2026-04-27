"""bench conductor worker — run a long-lived worker process."""

from __future__ import annotations

import click
import frappe
from frappe.commands import get_site, pass_context


@click.command("worker")
@click.option("--queue", "queues", multiple=True, default=("default",), help="Queue to consume (repeatable).")
@click.option("--concurrency", default=4, type=int, help="Threadpool size for executing jobs.")
@click.option("--grace", default=30, type=int, help="Graceful shutdown timeout (seconds).")
@pass_context
def worker_command(ctx, queues, concurrency, grace):
    """Run a Conductor worker process. Site comes from the bench context (--site)."""
    site = get_site(ctx)
    frappe.init(site=site)
    frappe.connect()
    try:
        from conductor.worker import run_worker
        run_worker(queues=list(queues), concurrency=concurrency, site=site, grace_seconds=grace)
    finally:
        frappe.destroy()
