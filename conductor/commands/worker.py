"""bench conductor worker — run a long-lived worker process.

Single-site (today's default): bench --site=X conductor worker
Pool mode (Phase 6):           bench conductor worker --sites=auto
                               bench conductor worker --sites=A,B,C
"""

from __future__ import annotations

import sys

import click
import frappe
from frappe.commands import get_site, pass_context

from conductor.site_discovery import discover_installed_sites


def _resolve_pool_sites(
    sites_arg: str | None,
    *,
    sites_path: str,
    bench_site: str,
) -> list[str]:
    """Resolve the worker's site list. Three modes:
        - sites_arg is None              -> [bench_site]
        - sites_arg == 'auto'            -> installed-conductor sites
        - sites_arg == 'A, B,C'          -> comma-list, stripped
    Empty 'auto' is a fatal error (sys.exit). Empty comma-list falls back
    to bench_site (lenient — matches Click's own no-flag behavior)."""
    if sites_arg is None:
        return [bench_site]
    if sites_arg == "auto":
        sites = discover_installed_sites(sites_path)
        if not sites:
            click.echo(
                "ERROR: --sites=auto found no sites with conductor installed under "
                f"{sites_path}. Pass --sites=site1,site2,... explicitly.",
                err=True,
            )
            sys.exit(2)
        return sites
    parts = [s.strip() for s in sites_arg.split(",")]
    cleaned = [s for s in parts if s]
    if not cleaned:
        return [bench_site]
    return cleaned


@click.command("worker")
@click.option("--queue", "queues", multiple=True, default=("default",), help="Queue to consume (repeatable).")
@click.option("--concurrency", default=4, type=int, help="Threadpool size for executing jobs.")
@click.option("--grace", default=30, type=int, help="Graceful shutdown timeout (seconds).")
@click.option(
    "--sites", "sites_arg", default=None,
    help="Comma list, or 'auto' for all installed-conductor sites. When set, takes priority over the bench --site.",
)
@pass_context
def worker_command(ctx, queues, concurrency, grace, sites_arg):
    """Run a Conductor worker process. Single-site mode (--site from bench)
    or pool mode (--sites=auto|A,B,C)."""
    # Bench's own --site is the fallback for sites_arg=None.
    bench_site = get_site(ctx)

    # Init the bench site once just to grab sites_path. Destroy after; we
    # re-init for the primary site below.
    frappe.init(site=bench_site)
    try:
        sites_path = frappe.local.sites_path
    finally:
        frappe.destroy()

    sites = _resolve_pool_sites(
        sites_arg, sites_path=sites_path, bench_site=bench_site,
    )
    primary_site = sites[0]

    # Establish the outer init for run_worker_pool — it reads cfg and
    # sites_path from frappe.local at startup (Task 6 contract).
    frappe.init(site=primary_site)
    frappe.connect()
    try:
        from conductor.worker import run_worker_pool
        run_worker_pool(
            sites=sites,
            queues=list(queues),
            concurrency=concurrency,
            grace_seconds=grace,
        )
    finally:
        frappe.destroy()
