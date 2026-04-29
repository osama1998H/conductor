"""Worker hook tests — mark_step_running / mark_step_terminal."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from conductor.workflow import Step, workflow
from conductor.workflow.decorator import _REGISTRY


def _make_simple(name="HookFlow"):
    _REGISTRY.pop(name, None)

    @workflow(name=name, queue="default")
    class F:
        _a = Step("a", compensation="undo_a")
        def a(self): pass
        def undo_a(self): pass
    return F


class TestWorkerHooks(unittest.TestCase):
    def setUp(self):
        if not frappe.db.exists("Conductor Queue", "default"):
            frappe.get_doc({"doctype": "Conductor Queue", "queue_name": "default", "enabled": 1}).insert(ignore_permissions=True)
        if not frappe.db.exists("Conductor Queue", "workflow"):
            frappe.get_doc({"doctype": "Conductor Queue", "queue_name": "workflow", "enabled": 1}).insert(ignore_permissions=True)
        frappe.db.commit()
        _make_simple()
        from conductor.workflow import run_workflow
        with patch("conductor.workflow.advancer._enqueue_step_job"):
            self.run_id = run_workflow("HookFlow")

    def tearDown(self):
        for dt in ("Conductor Workflow Step Run", "Conductor Workflow Run", "Conductor Workflow", "Conductor Job"):
            for n in frappe.get_all(dt, pluck="name"):
                frappe.delete_doc(dt, n, force=True)
        frappe.db.commit()

    def _step_run_a(self):
        return frappe.get_doc(
            "Conductor Workflow Step Run",
            {"workflow_run": self.run_id, "step_id": "a", "is_compensation": 0},
        )

    def test_mark_step_running_flips_status_and_sets_started_at(self):
        from conductor.workflow.worker_hooks import mark_step_running

        sr = self._step_run_a()
        sr.status = "READY"
        sr.save(ignore_permissions=True)
        frappe.db.commit()

        mark_step_running(workflow_run_id=self.run_id, step_id="a", is_compensation=False)

        sr = self._step_run_a()
        self.assertEqual(sr.status, "RUNNING")
        self.assertIsNotNone(sr.started_at)

    def test_mark_step_terminal_success_sets_finished_at(self):
        from conductor.workflow.worker_hooks import mark_step_terminal

        sr = self._step_run_a()
        sr.status = "RUNNING"
        sr.save(ignore_permissions=True)
        frappe.db.commit()

        mark_step_terminal(
            workflow_run_id=self.run_id, step_id="a",
            is_compensation=False, success=True,
        )
        sr = self._step_run_a()
        self.assertEqual(sr.status, "SUCCEEDED")
        self.assertIsNotNone(sr.finished_at)

    def test_mark_step_terminal_forward_failure_transitions_run_to_compensating(self):
        from conductor.workflow.worker_hooks import mark_step_terminal

        sr = self._step_run_a()
        sr.status = "RUNNING"
        sr.save(ignore_permissions=True)
        frappe.db.set_value("Conductor Workflow Run", self.run_id, "status", "RUNNING")
        frappe.db.commit()

        mark_step_terminal(
            workflow_run_id=self.run_id, step_id="a",
            is_compensation=False, success=False,
            error_type="ValueError", error_message="bang",
        )
        run_status = frappe.get_value("Conductor Workflow Run", self.run_id, "status")
        self.assertEqual(run_status, "COMPENSATING")
        sr = self._step_run_a()
        self.assertEqual(sr.status, "FAILED")
        self.assertEqual(sr.error_type, "ValueError")
