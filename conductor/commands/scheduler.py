"""bench conductor scheduler — run a long-lived scheduler process."""

from __future__ import annotations

import click
import frappe
from frappe.commands import get_site, pass_context


@click.command("scheduler")
@click.option("--lock-ttl-seconds", default=15, type=int,
              help="Singleton lock TTL (production default 15s).")
@click.option("--renew-interval-seconds", default=5, type=int,
              help="How often the holder renews the lock (default 5s).")
@click.option("--poll-interval-seconds", default=5, type=int,
              help="How often non-holders poll for the lock (default 5s).")
@pass_context
def scheduler_command(ctx, lock_ttl_seconds, renew_interval_seconds, poll_interval_seconds):
    """Run a Conductor scheduler process. Site comes from bench --site."""
    site = get_site(ctx)
    frappe.init(site=site)
    frappe.connect()
    try:
        from conductor.scheduler import run_scheduler
        run_scheduler(
            site=site,
            lock_ttl_seconds=lock_ttl_seconds,
            renew_interval_seconds=renew_interval_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
    finally:
        frappe.destroy()
