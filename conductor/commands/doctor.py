"""bench conductor doctor [--demo]"""

from __future__ import annotations

import sys

import click
import frappe
from frappe.commands import get_site, pass_context


@click.command("doctor")
@click.option("--demo", is_flag=True, default=False, help="Run an end-to-end dispatch demo too.")
@pass_context
def doctor_command(ctx, demo):
    site = get_site(ctx)
    frappe.init(site=site)
    frappe.connect()
    try:
        from conductor.doctor import run
        sys.exit(run(demo=demo))
    finally:
        frappe.destroy()
