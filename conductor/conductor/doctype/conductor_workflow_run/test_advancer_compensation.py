"""Advancer COMPENSATING branch tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from conductor.workflow import Step, workflow
from conductor.workflow.decorator import _REGISTRY


def _make_diamond(name="CompDiamond"):
    _REGISTRY.pop(name, None)

    @workflow(name=name, queue="default")
    class D:
        _a = Step("a", compensation="undo_a")
        _b = Step("b", depends_on=("a",), compensation="undo_b")
        _c = Step("c", depends_on=("a",))                     # no comp
        _d = Step("d", depends_on=("b", "c"), compensation="undo_d")
        def a(self): pass
        def undo_a(self): pass
        def b(self): pass
        def undo_b(self): pass
        def c(self): pass
        def d(self): pass
        def undo_d(self): pass
    return D


class TestAdvancerCompensation(unittest.TestCase):
    def setUp(self):
        for q in ("default", "workflow"):
            if not frappe.db.exists("Conductor Queue", q):
                frappe.get_doc({"doctype": "Conductor Queue", "queue_name": q, "enabled": 1}).insert(ignore_permissions=True)
        frappe.db.commit()
        _make_diamond()
        from conductor.workflow import run_workflow
        self._job_counter = 0
        with patch("conductor.workflow.advancer._enqueue_step_job"):
            self.run_id = run_workflow("CompDiamond")

        # Mark a and b SUCCEEDED, c FAILED, d still PENDING — simulating
        # the diamond after b succeeded but c failed.
        for sid, status in (("a", "SUCCEEDED"), ("b", "SUCCEEDED"), ("c", "FAILED")):
            sr = frappe.get_doc(
                "Conductor Workflow Step Run",
                {"workflow_run": self.run_id, "step_id": sid, "is_compensation": 0},
            )
            sr.status = status
            sr.save(ignore_permissions=True)
        frappe.db.set_value(
            "Conductor Workflow Step Run",
            {"workflow_run": self.run_id, "step_id": "d", "is_compensation": 0},
            "status", "SKIPPED",
        )
        frappe.db.set_value("Conductor Workflow Run", self.run_id, "status", "COMPENSATING")
        frappe.db.commit()

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
        for dt in ("Conductor Workflow Step Run", "Conductor Workflow Run", "Conductor Workflow", "Conductor Job"):
            for n in frappe.get_all(dt, pluck="name"):
                frappe.delete_doc(dt, n, force=True)
        frappe.db.commit()

    def test_compensation_first_step_is_b_in_reverse_topo(self):
        from conductor.workflow.advancer import advance

        with patch("conductor.workflow.advancer._enqueue_step_job") as mock_eq:
            mock_eq.side_effect = lambda **kwargs: self._next_job_id()
            advance(workflow_run_id=self.run_id, completed_step=None)

        # Reverse topo over completed-forward {a, b}: [b, a]
        # b has compensation, so first comp dispatched is b's.
        self.assertEqual(mock_eq.call_count, 1)
        kwargs = mock_eq.call_args.kwargs
        self.assertEqual(kwargs["step_id"], "b")
        self.assertTrue(kwargs.get("is_compensation"))

    def test_compensation_skips_steps_without_compensation_method(self):
        # Reset c to SUCCEEDED so it appears in the to-compensate set
        frappe.db.set_value(
            "Conductor Workflow Step Run",
            {"workflow_run": self.run_id, "step_id": "c", "is_compensation": 0},
            "status", "SUCCEEDED",
        )
        frappe.db.commit()

        from conductor.workflow.advancer import advance

        # Simulate b's compensation just COMPENSATED, plus a comp row exists
        for sid in ("b", "c"):
            if sid == "c":
                continue
            frappe.get_doc({
                "doctype": "Conductor Workflow Step Run",
                "workflow_run": self.run_id,
                "step_id": sid,
                "is_compensation": 1,
                "status": "COMPENSATED",
            }).insert(ignore_permissions=True)
        frappe.db.commit()

        with patch("conductor.workflow.advancer._enqueue_step_job") as mock_eq:
            mock_eq.side_effect = lambda **kwargs: self._next_job_id()
            advance(workflow_run_id=self.run_id, completed_step="b")

            # Next reverse-topo step is c, but c has no compensation. Advancer
            # should record that as a no-op (no enqueue) and re-fire itself for a.
            # Either: zero enqueues this call (no-op recurse), or one enqueue for a.
            # We accept either — but the eventual result must include a's comp.
            # For deterministic test, drive one more advance:
            if mock_eq.call_count == 0:
                advance(workflow_run_id=self.run_id, completed_step=None)
            kwargs_list = [c.kwargs for c in mock_eq.call_args_list]
            step_ids = [k["step_id"] for k in kwargs_list]
            self.assertIn("a", step_ids)

    def test_compensation_terminal_run_when_all_compensated(self):
        from conductor.workflow.advancer import advance

        # Insert "compensated" rows for b and a so the advancer sees nothing left to do
        for sid in ("b", "a"):
            frappe.get_doc({
                "doctype": "Conductor Workflow Step Run",
                "workflow_run": self.run_id, "step_id": sid,
                "is_compensation": 1, "status": "COMPENSATED",
            }).insert(ignore_permissions=True)
        frappe.db.commit()

        with patch("conductor.workflow.advancer._enqueue_step_job") as mock_eq:
            mock_eq.side_effect = lambda **kwargs: self._next_job_id()
            advance(workflow_run_id=self.run_id, completed_step="a")

        run_status = frappe.get_value("Conductor Workflow Run", self.run_id, "status")
        self.assertEqual(run_status, "FAILED")
        finished = frappe.get_value("Conductor Workflow Run", self.run_id, "finished_at")
        self.assertIsNotNone(finished)

    def test_compensation_waits_for_in_flight_forward_steps(self):
        # Mark d as RUNNING to simulate in-flight forward sibling
        frappe.db.set_value(
            "Conductor Workflow Step Run",
            {"workflow_run": self.run_id, "step_id": "d", "is_compensation": 0},
            "status", "RUNNING",
        )
        frappe.db.commit()

        from conductor.workflow.advancer import advance
        with patch("conductor.workflow.advancer._enqueue_step_job") as mock_eq:
            mock_eq.side_effect = lambda **kwargs: self._next_job_id()
            advance(workflow_run_id=self.run_id, completed_step=None)
        # No compensations dispatched while a forward step is still RUNNING
        self.assertEqual(mock_eq.call_count, 0)
