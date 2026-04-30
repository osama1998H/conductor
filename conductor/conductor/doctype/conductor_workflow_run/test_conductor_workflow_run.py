"""Smoke test for Conductor Workflow Run DocType."""

from __future__ import annotations

import unittest

import frappe


class TestConductorWorkflowRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not frappe.db.exists("Conductor Workflow", "TestFlowForRun"):
            frappe.get_doc({
                "doctype": "Conductor Workflow",
                "workflow_name": "TestFlowForRun",
                "definition_path": "myapp.x",
                "version": 1,
                "definition_snapshot": "{}",
            }).insert(ignore_permissions=True)
            frappe.db.commit()

    def tearDown(self):
        for n in frappe.get_all("Conductor Workflow Run", pluck="name"):
            frappe.delete_doc("Conductor Workflow Run", n, force=True)
        frappe.db.commit()

    def test_insert_run_row(self):
        doc = frappe.get_doc({
            "doctype": "Conductor Workflow Run",
            "workflow": "TestFlowForRun",
            "definition_version": 1,
            "status": "PENDING",
            "site": "frappe.localhost",
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        self.assertTrue(doc.name.startswith("WR-"))
        self.assertEqual(doc.status, "PENDING")
