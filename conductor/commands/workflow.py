"""bench conductor workflow — list/run/status/cancel subcommands."""

from __future__ import annotations

import json
import sys

import click
import frappe
from frappe.commands import get_site, pass_context


@click.group("workflow")
def workflow_group():
	"""Manage Conductor workflows."""


@workflow_group.command("list")
@pass_context
def workflow_list(ctx):
	"""Print all registered workflows + their current versions."""
	site = get_site(ctx)
	frappe.init(site=site)
	frappe.connect()
	try:
		rows = frappe.db.sql(
			"SELECT workflow_name, version, enabled, last_version_bumped_at "
			"FROM `tabConductor Workflow` ORDER BY workflow_name",
			as_dict=True,
		)
		if not rows:
			click.echo("(no workflows)")
			return
		click.echo(f"{'NAME':32} {'V':3} {'EN':2} {'LAST_BUMP':25}")
		for r in rows:
			click.echo(
				f"{r['workflow_name'][:32]:32} "
				f"{r['version']:3} "
				f"{r['enabled']:2} "
				f"{str(r['last_version_bumped_at'] or '')[:25]:25}"
			)
	finally:
		frappe.destroy()


@workflow_group.command("run")
@click.argument("name")
@click.option("--kwargs", default="{}", help="JSON object of input kwargs")
@click.option("--idempotency-key", default=None)
@pass_context
def workflow_run(ctx, name, kwargs, idempotency_key):
	"""Trigger a workflow run."""
	site = get_site(ctx)
	frappe.init(site=site)
	frappe.connect()
	try:
		try:
			kwargs_dict = json.loads(kwargs)
		except json.JSONDecodeError as e:
			click.echo(f"--kwargs is not valid JSON: {e}", err=True)
			sys.exit(1)
		from conductor.workflow import run_workflow
		try:
			run_id = run_workflow(name, idempotency_key=idempotency_key, **kwargs_dict)
		except Exception as e:
			click.echo(f"run failed: {e}", err=True)
			sys.exit(1)
		click.echo(run_id)
	finally:
		frappe.destroy()


@workflow_group.command("status")
@click.argument("run_id")
@pass_context
def workflow_status(ctx, run_id):
	"""Print run + per-step status table."""
	site = get_site(ctx)
	frappe.init(site=site)
	frappe.connect()
	try:
		if not frappe.db.exists("Conductor Workflow Run", run_id):
			click.echo(f"unknown run: {run_id}", err=True)
			sys.exit(1)
		run = frappe.get_doc("Conductor Workflow Run", run_id)
		click.echo(f"Run:        {run.name}")
		click.echo(f"Workflow:   {run.workflow}  (v{run.definition_version})")
		click.echo(f"Status:     {run.status}")
		click.echo(f"Started:    {run.started_at}")
		click.echo(f"Finished:   {run.finished_at}")
		steps = frappe.get_all(
			"Conductor Workflow Step Run",
			filters={"workflow_run": run.name},
			fields=["step_id", "is_compensation", "status", "started_at", "finished_at", "job"],
			order_by="creation asc",
		)
		click.echo()
		click.echo(f"{'STEP':12} {'C':2} {'STATUS':12} {'JOB':40}")
		for s in steps:
			comp = "Y" if s["is_compensation"] else " "
			click.echo(f"{s['step_id'][:12]:12} {comp:2} {s['status']:12} {s['job'] or '':40}")
	finally:
		frappe.destroy()


@workflow_group.command("cancel")
@click.argument("run_id")
@pass_context
def workflow_cancel(ctx, run_id):
	"""Cancel a workflow run (best-effort, no compensation)."""
	site = get_site(ctx)
	frappe.init(site=site)
	frappe.connect()
	try:
		if not frappe.db.exists("Conductor Workflow Run", run_id):
			click.echo(f"unknown run: {run_id}", err=True)
			sys.exit(1)
		from conductor.workflow import cancel_workflow_run
		cancel_workflow_run(run_id)
		click.echo(f"cancelled: {run_id}")
	finally:
		frappe.destroy()


commands = [workflow_group]
