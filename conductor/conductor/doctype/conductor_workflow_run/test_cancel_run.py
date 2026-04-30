"""cancel_workflow_run() tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from conductor.workflow import Step, workflow
from conductor.workflow.decorator import _REGISTRY


def _make_simple(name="CancelFlow"):
    _REGISTRY.pop(name, None)

    @workflow(name=name, queue="default")
    class F:
        _a = Step("a")
        _b = Step("b", depends_on=("a",))
        def a(self): pass
        def b(self): pass
    return F


class TestCancelWorkflowRun(unittest.TestCase):
    def setUp(self):
        for q in ("default", "workflow"):
            if not frappe.db.exists("Conductor Queue", q):
                frappe.get_doc({"doctype": "Conductor Queue", "queue_name": q, "enabled": 1}).insert(ignore_permissions=True)
        frappe.db.commit()
        _make_simple()
        from conductor.workflow import run_workflow
        with patch("conductor.workflow.advancer._enqueue_step_job"):
            self.run_id = run_workflow("CancelFlow")

    def tearDown(self):
        for dt in ("Conductor Workflow Step Run", "Conductor Workflow Run", "Conductor Workflow", "Conductor Job"):
            for n in frappe.get_all(dt, pluck="name"):
                frappe.delete_doc(dt, n, force=True)
        frappe.db.commit()

    def test_cancel_marks_run_cancelled(self):
        from conductor.workflow.cancellation import cancel_workflow_run
        cancel_workflow_run(self.run_id)
        self.assertEqual(
            frappe.get_value("Conductor Workflow Run", self.run_id, "status"),
            "CANCELLED",
        )

    def test_cancel_skips_pending_and_ready_steps(self):
        from conductor.workflow.cancellation import cancel_workflow_run
        # Mark a as READY to test transition
        frappe.db.set_value(
            "Conductor Workflow Step Run",
            {"workflow_run": self.run_id, "step_id": "a", "is_compensation": 0},
            "status", "READY",
        )
        frappe.db.commit()

        cancel_workflow_run(self.run_id)
        for sid in ("a", "b"):
            sr = frappe.get_doc(
                "Conductor Workflow Step Run",
                {"workflow_run": self.run_id, "step_id": sid, "is_compensation": 0},
            )
            self.assertEqual(sr.status, "SKIPPED")

    def test_cancel_calls_cancel_job_for_running_steps(self):
        from conductor.workflow.cancellation import cancel_workflow_run

        # Create a fake job first
        frappe.get_doc({
            "doctype": "Conductor Job",
            "job_id": "fake-job-id",
            "method": "test.method",
            "queue": "default",
            "status": "RUNNING",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        # Mark a as RUNNING with an attached job_id
        sr = frappe.get_doc(
            "Conductor Workflow Step Run",
            {"workflow_run": self.run_id, "step_id": "a", "is_compensation": 0},
        )
        sr.status = "RUNNING"
        sr.job = "fake-job-id"
        sr.save(ignore_permissions=True)
        frappe.db.commit()

        with patch("conductor.cancellation.cancel_job") as mock_cancel:
            cancel_workflow_run(self.run_id)
            mock_cancel.assert_called_once_with("fake-job-id")

    def test_cancel_clears_wfdeps_redis_key(self):
        from conductor.workflow.cancellation import cancel_workflow_run
        from conductor.workflow.keys import wfdeps_key
        from conductor.client import get_redis
        from conductor.config import load_config

        site = frappe.local.site
        r = get_redis(load_config(frappe.local.conf).redis_url)
        # The dispatcher seeded the hash; confirm it's there
        self.assertTrue(r.exists(wfdeps_key(site, self.run_id)))

        cancel_workflow_run(self.run_id)
        self.assertFalse(r.exists(wfdeps_key(site, self.run_id)))

    def test_cancel_idempotent_on_already_cancelled(self):
        from conductor.workflow.cancellation import cancel_workflow_run
        cancel_workflow_run(self.run_id)
        # Second call must not raise
        cancel_workflow_run(self.run_id)
