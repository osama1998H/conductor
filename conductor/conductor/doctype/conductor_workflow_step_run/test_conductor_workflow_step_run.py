"""Smoke test for Conductor Workflow Step Run DocType."""

from __future__ import annotations

import unittest

import frappe


class TestConductorWorkflowStepRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not frappe.db.exists("Conductor Workflow", "TestFlowForStep"):
            frappe.get_doc({
                "doctype": "Conductor Workflow",
                "workflow_name": "TestFlowForStep",
                "definition_path": "myapp.x",
                "version": 1,
                "definition_snapshot": "{}",
            }).insert(ignore_permissions=True)
        cls.run_name = frappe.get_doc({
            "doctype": "Conductor Workflow Run",
            "workflow": "TestFlowForStep",
            "definition_version": 1,
            "status": "PENDING",
            "site": "frappe.localhost",
        }).insert(ignore_permissions=True).name
        frappe.db.commit()

    def tearDown(self):
        for n in frappe.get_all("Conductor Workflow Step Run", pluck="name"):
            frappe.delete_doc("Conductor Workflow Step Run", n, force=True)
        frappe.db.commit()

    def test_insert_step_run(self):
        doc = frappe.get_doc({
            "doctype": "Conductor Workflow Step Run",
            "workflow_run": self.run_name,
            "step_id": "a",
            "is_compensation": 0,
            "status": "PENDING",
            "depends_on": "[]",
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        self.assertTrue(doc.name.startswith("WSR-"))
        self.assertEqual(doc.status, "PENDING")
