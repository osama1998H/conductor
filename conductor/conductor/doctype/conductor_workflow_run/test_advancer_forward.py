"""Advancer forward-path Frappe-integration tests."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import frappe

from conductor.workflow import Step, workflow
from conductor.workflow.decorator import _REGISTRY


def _make_diamond(name="AdvDiamond"):
    _REGISTRY.pop(name, None)

    @workflow(name=name, queue="default")
    class D:
        _a = Step("a")
        _b = Step("b", depends_on=("a",))
        _c = Step("c", depends_on=("a",))
        _d = Step("d", depends_on=("b", "c"))
        def a(self): pass
        def b(self): pass
        def c(self): pass
        def d(self): pass
    return D


class TestAdvancerForward(unittest.TestCase):
    def setUp(self):
        if not frappe.db.exists("Conductor Queue", "default"):
            frappe.get_doc({"doctype": "Conductor Queue", "queue_name": "default", "enabled": 1}).insert(ignore_permissions=True)
        if not frappe.db.exists("Conductor Queue", "workflow"):
            frappe.get_doc({"doctype": "Conductor Queue", "queue_name": "workflow", "enabled": 1}).insert(ignore_permissions=True)
        frappe.db.commit()
        _make_diamond()
        self._job_counter = 0

    def _next_job_id(self):
        """Generate a unique job ID and create a Conductor Job doc for it."""
        self._job_counter += 1
        job_id = f"job-{self._job_counter}"
        if not frappe.db.exists("Conductor Job", job_id):
            frappe.get_doc({
                "doctype": "Conductor Job",
                "job_id": job_id,
                "method": "test.method",
                "queue": "default",
                "status": "QUEUED",
            }).insert(ignore_permissions=True)
        frappe.db.commit()
        return job_id

    def tearDown(self):
        for dt in (
            "Conductor Job",
            "Conductor Workflow Step Run",
            "Conductor Workflow Run",
            "Conductor Workflow",
        ):
            for n in frappe.get_all(dt, pluck="name"):
                frappe.delete_doc(dt, n, force=True)
        frappe.db.commit()

    def test_first_advance_dispatches_only_root_steps(self):
        from conductor.workflow import run_workflow
        from conductor.workflow.advancer import advance

        with patch("conductor.workflow.advancer._enqueue_step_job") as mock_eq:
            mock_eq.side_effect = lambda **kwargs: self._next_job_id()
            run_id = run_workflow("AdvDiamond")
            advance(workflow_run_id=run_id, completed_step=None)

            dispatched = [c.kwargs["step_id"] for c in mock_eq.call_args_list]
            self.assertEqual(dispatched, ["a"])  # only root

    def test_advance_marks_run_running_on_first_dispatch(self):
        from conductor.workflow import run_workflow
        from conductor.workflow.advancer import advance

        with patch("conductor.workflow.advancer._enqueue_step_job") as mock_eq:
            mock_eq.side_effect = lambda **kwargs: self._next_job_id()
            run_id = run_workflow("AdvDiamond")
            advance(workflow_run_id=run_id, completed_step=None)
        status = frappe.get_value("Conductor Workflow Run", run_id, "status")
        self.assertEqual(status, "RUNNING")

    def test_advance_after_a_succeeded_dispatches_b_and_c(self):
        from conductor.workflow import run_workflow
        from conductor.workflow.advancer import advance

        with patch("conductor.workflow.advancer._enqueue_step_job") as mock_eq:
            mock_eq.side_effect = lambda **kwargs: self._next_job_id()
            run_id = run_workflow("AdvDiamond")
            advance(workflow_run_id=run_id, completed_step=None)
            mock_eq.reset_mock()

            # Simulate step a succeeded
            sr = frappe.get_doc(
                "Conductor Workflow Step Run",
                {"workflow_run": run_id, "step_id": "a", "is_compensation": 0},
            )
            sr.status = "SUCCEEDED"
            sr.save(ignore_permissions=True)
            frappe.db.commit()

            advance(workflow_run_id=run_id, completed_step="a")
            dispatched = sorted(c.kwargs["step_id"] for c in mock_eq.call_args_list)
            self.assertEqual(dispatched, ["b", "c"])

    def test_advance_marks_step_ready_before_enqueue(self):
        from conductor.workflow import run_workflow
        from conductor.workflow.advancer import advance

        with patch("conductor.workflow.advancer._enqueue_step_job") as mock_eq:
            mock_eq.side_effect = lambda **kwargs: self._next_job_id()
            run_id = run_workflow("AdvDiamond")
            advance(workflow_run_id=run_id, completed_step=None)
        sr_a = frappe.get_doc(
            "Conductor Workflow Step Run",
            {"workflow_run": run_id, "step_id": "a", "is_compensation": 0},
        )
        self.assertEqual(sr_a.status, "READY")

    def test_advance_ignores_run_in_terminal_status(self):
        from conductor.workflow import run_workflow
        from conductor.workflow.advancer import advance

        with patch("conductor.workflow.advancer._enqueue_step_job") as mock_eq:
            run_id = run_workflow("AdvDiamond")
            frappe.db.set_value("Conductor Workflow Run", run_id, "status", "CANCELLED")
            advance(workflow_run_id=run_id, completed_step=None)
            self.assertEqual(mock_eq.call_count, 0)

    def test_run_completes_when_all_steps_succeeded(self):
        from conductor.workflow import run_workflow
        from conductor.workflow.advancer import advance

        with patch("conductor.workflow.advancer._enqueue_step_job") as mock_eq:
            mock_eq.side_effect = lambda **kwargs: self._next_job_id()
            run_id = run_workflow("AdvDiamond")
            advance(workflow_run_id=run_id, completed_step=None)
            for step in ("a", "b", "c", "d"):
                sr = frappe.get_doc(
                    "Conductor Workflow Step Run",
                    {"workflow_run": run_id, "step_id": step, "is_compensation": 0},
                )
                sr.status = "SUCCEEDED"
                sr.save(ignore_permissions=True)
            frappe.db.commit()
            advance(workflow_run_id=run_id, completed_step="d")

        status = frappe.get_value("Conductor Workflow Run", run_id, "status")
        self.assertEqual(status, "SUCCEEDED")
