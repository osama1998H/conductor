"""Backfill max_rps and max_concurrent on Conductor Queue rows.

Frappe migrate adds the columns automatically from the JSON; this patch fills
in 0 for any pre-existing rows whose new columns came back NULL on add. The
patch is idempotent — re-running it is a no-op once values are 0.
"""

import frappe


def execute():
    frappe.db.sql(
        "UPDATE `tabConductor Queue` SET max_rps = 0 WHERE max_rps IS NULL"
    )
    frappe.db.sql(
        "UPDATE `tabConductor Queue` SET max_concurrent = 0 WHERE max_concurrent IS NULL"
    )
    frappe.db.commit()
