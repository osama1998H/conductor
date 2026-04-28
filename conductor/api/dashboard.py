"""Dashboard whitelisted API surface — Phase 3.

Reference: docs/superpowers/specs/2026-04-28-conductor-phase3-dashboard-design.md §7.

Permission model (spec §6):
  - System Manager: full access.
  - Conductor Operator: read everything + safe-mutating actions
    (retry / cancel / schedule run-now).
  - Destructive actions (DLQ discard, edit-and-retry, schedule enable/disable)
    are System-Manager-only.

The server is the source of truth for permission enforcement. The frontend
hides destructive controls for non-SysMgr users as UX polish only.
"""

from __future__ import annotations

import frappe


def _require_read() -> None:
    if not (
        frappe.has_permission("Conductor Job", "read")
        or "Conductor Operator" in frappe.get_roles()
    ):
        raise frappe.PermissionError("Not permitted")


def _require_destructive() -> None:
    if "System Manager" not in frappe.get_roles():
        raise frappe.PermissionError("System Manager only")
