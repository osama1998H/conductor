"""bench conductor migrate-from-rq — one-shot RQ -> Conductor migration."""

from __future__ import annotations

import click
import frappe

from conductor.migrate_rq import migrate_from_rq

DEFAULT_QUEUE_MAP = {"short": "short", "default": "default", "long": "long"}


def _init_site(site: str) -> None:
    frappe.init(site=site)
    frappe.connect()


def _destroy_site() -> None:
    frappe.destroy()


def _parse_queue_map(spec: str | None) -> dict[str, str]:
    if spec is None or spec == "":
        return dict(DEFAULT_QUEUE_MAP)
    out: dict[str, str] = {}
    for pair in spec.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ValueError(f"invalid --queue-map entry: {pair!r} (expected 'rq=conductor')")
        rq, _, cd = pair.partition("=")
        out[rq.strip()] = cd.strip()
    return out


@click.command("migrate-from-rq")
@click.option("--site", required=True, help="Frappe site to migrate.")
@click.option("--queue-map", "queue_map_str", default=None,
              help="Comma list 'rq_queue=conductor_queue,...'. Default: short,default,long -> identity.")
@click.option("--commit", is_flag=True, default=False,
              help="Actually perform the migration. Without this flag, runs as a dry-run preview.")
@click.option("--force", is_flag=True, default=False,
              help="Ignore the conductor:{site}:rq_migrated_at marker (re-run a previously-completed migration).")
def migrate_rq_command(site, queue_map_str, commit, force):
    """One-shot RQ -> Conductor migration (defaults to dry-run)."""
    qmap = _parse_queue_map(queue_map_str)

    if commit and not force:
        click.echo(
            "WARNING: This will move pending RQ jobs into Conductor.\n"
            "For a clean cutover, stop Frappe processes that still call frappe.enqueue\n"
            "or that route through conductor.frappe_compat.enqueue's HTTP shim.\n"
        )
        click.confirm("Continue?", default=False, abort=True)

    _init_site(site)
    try:
        rep = migrate_from_rq(
            site, queue_map=qmap, commit=commit, force=force,
        )
    finally:
        _destroy_site()

    if rep.skipped_due_to_marker:
        click.echo(f"Site {site} already has an RQ migration marker. Pass --force to re-run.")
        return

    mode = "COMMIT" if commit else "DRY RUN"
    click.echo(f"\n=== {mode} report — site {site} ===")
    click.echo(f"  plan rows           : {len(rep.plan)}")
    if commit:
        click.echo(f"  moved               : {rep.moved}")
    click.echo(f"  skipped (other site): {rep.skipped_other_site}")
    click.echo(f"  skipped (callable)  : {rep.skipped_callable_method}")
    click.echo(f"  failed              : {rep.failed}")
    if rep.unmapped_queues_seen:
        click.echo(f"  unmapped queues seen: {dict(rep.unmapped_queues_seen)} (fell back to 'default')")
    if not commit and rep.plan:
        click.echo("\nFirst 5 plan rows:")
        for row in rep.plan[:5]:
            click.echo(f"  {row}")
        click.echo("\nRe-run with --commit to apply.")
