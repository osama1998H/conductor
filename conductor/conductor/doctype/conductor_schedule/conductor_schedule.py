"""Conductor Schedule controller — keeps next_run_at fresh on validate/on_change."""

from __future__ import annotations

import frappe
from frappe.model.document import Document

from conductor.cron import compute_next_run_at


class ConductorSchedule(Document):
    def validate(self):
        if not self.enabled:
            self.next_run_at = None
            return
        if not self.cron_expression:
            frappe.throw("cron_expression required when enabled")
        # Validate by attempting to compute next_run_at — raises on bad expr.
        try:
            next_at = compute_next_run_at(self.cron_expression, self.timezone or "UTC")
        except Exception as e:
            frappe.throw(f"Invalid cron_expression {self.cron_expression!r}: {e}")
        self.next_run_at = next_at.replace(tzinfo=None)

    def on_update(self):
        # If user toggled enabled or edited cron/tz post-save, validate already
        # re-set next_run_at. on_update is called *after* validate, so nothing
        # else to do — the DB is consistent.
        pass
