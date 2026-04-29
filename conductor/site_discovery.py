"""Discover Frappe sites that have the conductor app installed.

Used by `bench conductor worker --sites=auto` (and `bench conductor depth
--all-sites`) to enumerate which sites a pool worker should serve. Pure
filesystem + Frappe-init scan; the result is cached by the caller, never
internally — there is no daemon and no re-scan.
"""

from __future__ import annotations

import os
from pathlib import Path

from conductor.logging import get_logger

log = get_logger("conductor.site_discovery")

# Bench convention: these names live alongside site directories under sites/
# but are never themselves sites. Add to the deny-list if the bench grows new
# special directories.
_NON_SITE_NAMES = {"assets", "apps", "logs"}


def _candidate_site_dirs(sites_path: str) -> list[str]:
    """List subdirectories of sites_path that look like they could be a
    Frappe site (have a site_config.json AND are not in the deny-list)."""
    base = Path(sites_path)
    if not base.is_dir():
        return []
    out: list[str] = []
    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        if entry.name in _NON_SITE_NAMES:
            continue
        if not (entry / "site_config.json").is_file():
            continue
        out.append(entry.name)
    return out


def _installed_apps_for_site(site: str, sites_path: str) -> list[str]:
    """Connect to `site` and return its installed_apps list. Always destroys
    the Frappe local context before returning so the caller does not inherit
    stale state. Raises on any init/connect failure (caller catches)."""
    import frappe  # local import — keeps this module importable without Frappe
    frappe.init(site=site, sites_path=sites_path)
    try:
        frappe.connect()
        try:
            return list(frappe.get_installed_apps())
        finally:
            frappe.db.close() if frappe.db else None
    finally:
        frappe.destroy()


def discover_installed_sites(sites_path: str) -> list[str]:
    """Return a sorted list of site names under `sites_path` that have the
    `conductor` app installed. Failures probing one site do not abort the
    scan — they log and skip."""
    out: list[str] = []
    for site in _candidate_site_dirs(sites_path):
        try:
            apps = _installed_apps_for_site(site, sites_path)
        except Exception as e:
            log.warning("site_discovery_skipped", site=site, error=str(e))
            continue
        if "conductor" in apps:
            out.append(site)
    return sorted(out)
