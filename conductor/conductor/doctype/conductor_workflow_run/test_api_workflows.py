"""Tests for conductor.api.workflows endpoints."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from conductor.workflow import Step, workflow
from conductor.workflow.decorator import _REGISTRY


def _make_simple(name="ApiFlow"):
    _REGISTRY.pop(name, None)

    @workflow(name=name, queue="default")
    class F:
        _a = Step("a")
        _b = Step("b", depends_on=("a",))
        def a(self): pass
        def b(self): pass
    return F


class TestApiWorkflows(unittest.TestCase):
    def setUp(self):
        for q in ("default", "workflow"):
            if not frappe.db.exists("Conductor Queue", q):
                frappe.get_doc({"doctype": "Conductor Queue", "queue_name": q, "enabled": 1}).insert(ignore_permissions=True)
        frappe.db.commit()
        _make_simple()
        from conductor.workflow import run_workflow
        with patch("conductor.workflow.advancer._enqueue_step_job"):
            self.run_id = run_workflow("ApiFlow")

    def tearDown(self):
        for dt in ("Conductor Workflow Step Run", "Conductor Workflow Run", "Conductor Workflow"):
            for n in frappe.get_all(dt, pluck="name"):
                frappe.delete_doc(dt, n, force=True)
        frappe.db.commit()

    def test_list_workflows_returns_registered(self):
        from conductor.api.workflows import list_workflows
        rows = list_workflows()
        names = [r["workflow_name"] for r in rows]
        self.assertIn("ApiFlow", names)
        wf = next(r for r in rows if r["workflow_name"] == "ApiFlow")
        self.assertEqual(wf["version"], 1)

    def test_list_runs_filters_by_workflow(self):
        from conductor.api.workflows import list_runs
        rows = list_runs(workflow="ApiFlow")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], self.run_id)

    def test_get_run_includes_step_rows_and_snapshot(self):
        from conductor.api.workflows import get_run
        result = get_run(self.run_id)
        self.assertEqual(result["run"]["name"], self.run_id)
        self.assertEqual(len(result["steps"]), 2)
        step_ids = {s["step_id"] for s in result["steps"]}
        self.assertEqual(step_ids, {"a", "b"})
        self.assertIn("snapshot", result)
        self.assertIn('"name":"ApiFlow"', result["snapshot"])

    def test_cancel_run_endpoint_marks_cancelled(self):
        from conductor.api.workflows import cancel_run
        cancel_run(self.run_id)
        self.assertEqual(
            frappe.get_value("Conductor Workflow Run", self.run_id, "status"),
            "CANCELLED",
        )
