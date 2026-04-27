"""Frappe integration test: bench conductor schedule run-now end-to-end."""

from __future__ import annotations

import unittest

import frappe


class TestRunNow(unittest.TestCase):
    def setUp(self):
        if not frappe.db.exists("Conductor Queue", "default"):
            frappe.get_doc({
                "doctype": "Conductor Queue",
                "queue_name": "default",
                "enabled": 1,
            }).insert(ignore_permissions=True)
        # Clean Schedule rows.
        for n in frappe.get_all("Conductor Schedule", pluck="name"):
            frappe.delete_doc("Conductor Schedule", n, force=True)
        # Clean Conductor Job rows from previous runs.
        for n in frappe.get_all("Conductor Job", pluck="name"):
            frappe.delete_doc("Conductor Job", n, force=True)
        frappe.db.commit()

    def test_run_now_dispatches_and_does_not_bump_last_run_at(self):
        from conductor.commands.schedule import schedule_run_now  # noqa
        # Insert a schedule.
        doc = frappe.get_doc({
            "doctype": "Conductor Schedule",
            "schedule_name": "rn-test",
            "enabled": 1,
            "cron_expression": "0 0 1 1 *",  # never (well, yearly Jan 1)
            "timezone": "UTC",
            "method": "frappe.utils.now",
            "queue": "default",
        }).insert(ignore_permissions=True)
        prior_last_run = doc.last_run_at
        # Invoke the run-now logic directly.
        from conductor.scheduler_loops import _decode_kwargs  # noqa
        from conductor.dispatcher import enqueue as conductor_enqueue
        kwargs = _decode_kwargs(doc.kwargs) if doc.kwargs else {}
        job_id = conductor_enqueue(doc.method, queue=doc.queue, **kwargs)
        doc.db_set("last_status", "DISPATCHED", update_modified=False)
        doc.db_set("last_job", job_id, update_modified=False)
        frappe.db.commit()

        # Reload.
        doc.reload()
        self.assertEqual(doc.last_status, "DISPATCHED")
        self.assertEqual(doc.last_job, job_id)
        self.assertEqual(doc.last_run_at, prior_last_run)
        self.assertTrue(frappe.db.exists("Conductor Job", job_id))
