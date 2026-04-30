"""Smoke test for Conductor Workflow DocType."""

from __future__ import annotations

import unittest

import frappe


class TestConductorWorkflow(unittest.TestCase):
    def tearDown(self):
        for n in frappe.get_all("Conductor Workflow", pluck="name"):
            frappe.delete_doc("Conductor Workflow", n, force=True)
        frappe.db.commit()

    def test_insert_workflow_row(self):
        doc = frappe.get_doc({
            "doctype": "Conductor Workflow",
            "workflow_name": "TestFlow",
            "enabled": 1,
            "definition_path": "myapp.workflows.TestFlow",
            "version": 1,
            "definition_snapshot": '{"name":"TestFlow","queue":"default","steps":[]}',
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        self.assertEqual(doc.name, "TestFlow")
        self.assertEqual(doc.version, 1)
