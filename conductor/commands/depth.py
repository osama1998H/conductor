"""bench conductor depth — show per-queue depth stats for one site or all
installed-conductor sites."""

from __future__ import annotations

import click
import frappe
from frappe.commands import get_site, pass_context

from conductor.client import get_redis
from conductor.config import load_config
from conductor.inflight import get_count as inflight_get_count
from conductor.streams import dlq_key, scheduled_key, stream_key


def _all_queues():
    """Return Conductor Queue rows ordered by name."""
    return frappe.get_all(
        "Conductor Queue",
        fields=["name", "max_rps", "max_concurrent"],
        order_by="name asc",
    )


def collect_depth_for_site(redis_client, site: str) -> list[dict]:
    """Build one row per Conductor Queue with stream/DLQ/scheduled/inflight counts."""
    out: list[dict] = []
    sched_zcard = redis_client.zcard(scheduled_key(site)) or 0
    for q in _all_queues():
        # Support both real Frappe rows (dict-like) and test-fixture objects with attrs.
        if isinstance(q, dict):
            qname = q["name"]
            max_rps = int(q.get("max_rps", 0) or 0)
            max_conc = int(q.get("max_concurrent", 0) or 0)
        else:
            qname = q.name
            max_rps = int(getattr(q, "max_rps", 0) or 0)
            max_conc = int(getattr(q, "max_concurrent", 0) or 0)
        stream_len = redis_client.xlen(stream_key(site, qname)) or 0
        dlq_len = redis_client.xlen(dlq_key(site, qname)) or 0
        out.append({
            "queue": qname,
            "stream_xlen": stream_len,
            "dlq_xlen": dlq_len,
            "scheduled_zcard": sched_zcard,
            "inflight": inflight_get_count(redis_client, site, qname),
            "max_rps": max_rps,
            "max_concurrent": max_conc,
        })
    return out


def format_depth_table(site: str, rows: list[dict]) -> str:
    headers = ["queue", "stream", "dlq", "scheduled", "inflight", "max_rps", "max_concurrent"]
    widths = [max(len(h), 8) for h in headers]
    for r in rows:
        for i, key in enumerate(("queue", "stream_xlen", "dlq_xlen", "scheduled_zcard",
                                  "inflight", "max_rps", "max_concurrent")):
            widths[i] = max(widths[i], len(str(r[key])))
    out_lines = [f"site: {site}"]
    sep = "  "
    out_lines.append(sep.join(h.ljust(w) for h, w in zip(headers, widths)))
    out_lines.append(sep.join("-" * w for w in widths))
    for r in rows:
        cells = [
            r["queue"], r["stream_xlen"], r["dlq_xlen"],
            r["scheduled_zcard"], r["inflight"],
            r["max_rps"], r["max_concurrent"],
        ]
        out_lines.append(sep.join(str(c).ljust(w) for c, w in zip(cells, widths)))
    return "\n".join(out_lines)


@click.command("depth")
@click.option("--all-sites", is_flag=True, default=False,
              help="Walk all sites with conductor installed and print one table per site.")
@pass_context
def depth_command(ctx, all_sites):
    """Print queue/DLQ/scheduled depths for one site (--all-sites for the fleet)."""
    if all_sites:
        from conductor.site_discovery import discover_installed_sites
        bench_site = get_site(ctx)
        frappe.init(site=bench_site)
        try:
            sites_path = frappe.local.sites_path
        finally:
            frappe.destroy()
        sites = discover_installed_sites(sites_path)
    else:
        sites = [get_site(ctx)]

    for site in sites:
        frappe.init(site=site)
        try:
            frappe.connect()
            cfg = load_config(frappe.local.conf)
            r = get_redis(cfg.redis_url)
            rows = collect_depth_for_site(r, site)
            click.echo(format_depth_table(site, rows))
            click.echo("")
        finally:
            frappe.destroy()
