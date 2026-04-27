"""bench --site <site> conductor cancel <job_id>"""

from __future__ import annotations

import sys

import click
import frappe
from frappe.commands import get_site, pass_context


@click.command("cancel")
@click.argument("job_id")
@pass_context
def cancel_command(ctx, job_id):
    """Cancel a Conductor Job by ID."""
    site = get_site(ctx)
    frappe.init(site=site)
    frappe.connect()
    try:
        from conductor.cancellation import cancel
        ok = cancel(job_id)
        if ok:
            click.echo(f"cancelled: {job_id}")
            sys.exit(0)
        click.echo(f"not cancelled (already terminal or unknown): {job_id}", err=True)
        sys.exit(1)
    finally:
        frappe.destroy()
