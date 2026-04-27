"""Frappe integration tests for Conductor Schedule."""

from __future__ import annotations

import unittest

import frappe


class TestConductorSchedule(unittest.TestCase):
    def setUp(self):
        # Ensure the default queue exists.
        if not frappe.db.exists("Conductor Queue", "default"):
            frappe.get_doc({
                "doctype": "Conductor Queue",
                "queue_name": "default",
                "enabled": 1,
            }).insert(ignore_permissions=True)
            frappe.db.commit()

    def tearDown(self):
        for name in frappe.get_all("Conductor Schedule", pluck="name"):
            frappe.delete_doc("Conductor Schedule", name, force=True)
        frappe.db.commit()

    def test_insert_populates_next_run_at(self):
        doc = frappe.get_doc({
            "doctype": "Conductor Schedule",
            "schedule_name": "test-every-minute",
            "enabled": 1,
            "cron_expression": "* * * * *",
            "timezone": "UTC",
            "method": "frappe.utils.now",
            "queue": "default",
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        self.assertIsNotNone(doc.next_run_at)

    def test_malformed_cron_raises(self):
        with self.assertRaises(Exception):
            frappe.get_doc({
                "doctype": "Conductor Schedule",
                "schedule_name": "test-bad",
                "enabled": 1,
                "cron_expression": "this is not cron",
                "timezone": "UTC",
                "method": "frappe.utils.now",
                "queue": "default",
            }).insert(ignore_permissions=True)

    def test_disabled_clears_next_run_at(self):
        doc = frappe.get_doc({
            "doctype": "Conductor Schedule",
            "schedule_name": "test-disable",
            "enabled": 1,
            "cron_expression": "@hourly",
            "timezone": "UTC",
            "method": "frappe.utils.now",
            "queue": "default",
        }).insert(ignore_permissions=True)
        self.assertIsNotNone(doc.next_run_at)
        doc.enabled = 0
        doc.save(ignore_permissions=True)
        self.assertIsNone(doc.next_run_at)

    def test_edit_cron_updates_next_run_at(self):
        doc = frappe.get_doc({
            "doctype": "Conductor Schedule",
            "schedule_name": "test-edit",
            "enabled": 1,
            "cron_expression": "0 0 * * *",  # daily midnight
            "timezone": "UTC",
            "method": "frappe.utils.now",
            "queue": "default",
        }).insert(ignore_permissions=True)
        first_next = doc.next_run_at
        doc.cron_expression = "0 12 * * *"  # daily noon
        doc.save(ignore_permissions=True)
        self.assertNotEqual(doc.next_run_at, first_next)
