"""bench conductor schedule — list/enable/disable/run-now subcommands."""

from __future__ import annotations

import sys

import click
import frappe
from frappe.commands import get_site, pass_context


@click.group("schedule")
def schedule_group():
    """Manage Conductor schedules."""


@schedule_group.command("list")
@pass_context
def schedule_list(ctx):
    """Print all schedules."""
    site = get_site(ctx)
    frappe.init(site=site)
    frappe.connect()
    try:
        rows = frappe.db.sql(
            "SELECT name, enabled, cron_expression, timezone, "
            "next_run_at, last_status FROM `tabConductor Schedule` ORDER BY name",
            as_dict=True,
        )
        if not rows:
            click.echo("(no schedules)")
            return
        click.echo(f"{'NAME':24} {'EN':2} {'CRON':16} {'TZ':18} {'NEXT_RUN':25} LAST_STATUS")
        for r in rows:
            click.echo(
                f"{r['name'][:24]:24} "
                f"{r['enabled']:2} "
                f"{(r['cron_expression'] or '')[:16]:16} "
                f"{(r['timezone'] or '')[:18]:18} "
                f"{str(r['next_run_at'] or '')[:25]:25} "
                f"{r['last_status'] or ''}"
            )
    finally:
        frappe.destroy()


@schedule_group.command("enable")
@click.argument("name")
@pass_context
def schedule_enable(ctx, name):
    """Enable a schedule and recompute next_run_at."""
    site = get_site(ctx)
    frappe.init(site=site)
    frappe.connect()
    try:
        if not frappe.db.exists("Conductor Schedule", name):
            click.echo(f"unknown schedule: {name}", err=True)
            sys.exit(1)
        doc = frappe.get_doc("Conductor Schedule", name)
        doc.enabled = 1
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        click.echo(f"enabled: {name} (next_run_at={doc.next_run_at})")
    finally:
        frappe.destroy()


@schedule_group.command("disable")
@click.argument("name")
@pass_context
def schedule_disable(ctx, name):
    """Disable a schedule. next_run_at is cleared."""
    site = get_site(ctx)
    frappe.init(site=site)
    frappe.connect()
    try:
        if not frappe.db.exists("Conductor Schedule", name):
            click.echo(f"unknown schedule: {name}", err=True)
            sys.exit(1)
        doc = frappe.get_doc("Conductor Schedule", name)
        doc.enabled = 0
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        click.echo(f"disabled: {name}")
    finally:
        frappe.destroy()


@schedule_group.command("run-now")
@click.argument("name")
@pass_context
def schedule_run_now(ctx, name):
    """Fire the schedule's payload via conductor.enqueue, out-of-band of cron.

    Updates last_status (DISPATCHED on success / DISPATCH_FAILED on failure)
    and last_job. Does NOT touch last_run_at — cron cadence is preserved.
    """
    site = get_site(ctx)
    frappe.init(site=site)
    frappe.connect()
    try:
        if not frappe.db.exists("Conductor Schedule", name):
            click.echo(f"unknown schedule: {name}", err=True)
            sys.exit(1)
        doc = frappe.get_doc("Conductor Schedule", name)
        from conductor.scheduler_loops import _decode_kwargs
        from conductor.dispatcher import enqueue as conductor_enqueue
        try:
            kwargs = _decode_kwargs(doc.kwargs) if doc.kwargs else {}
            max_attempts = doc.max_attempts or None
            job_id = conductor_enqueue(
                doc.method, queue=doc.queue, max_attempts=max_attempts, **kwargs,
            )
            doc.db_set("last_status", "DISPATCHED", update_modified=False)
            doc.db_set("last_job", job_id, update_modified=False)
            frappe.db.commit()
            click.echo(f"fired: {name} → job {job_id}")
        except Exception as e:
            doc.db_set("last_status", "DISPATCH_FAILED", update_modified=False)
            frappe.db.commit()
            click.echo(f"dispatch failed: {name} — {e}", err=True)
            sys.exit(1)
    finally:
        frappe.destroy()
