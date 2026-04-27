"""End-to-end: dispatch → worker thread → SUCCEEDED row."""

import time

import frappe
from frappe.tests.utils import FrappeTestCase

import conductor
from conductor.worker import run_worker_once


class TestWorkerE2E(FrappeTestCase):
    def _wait_for_status(self, job_id: str, status: str, timeout: float = 5.0):
        end = time.time() + timeout
        while time.time() < end:
            frappe.db.rollback()  # see latest committed state
            doc = frappe.db.get_value("Conductor Job", job_id, "status")
            if doc == status:
                return
            time.sleep(0.1)
        raise AssertionError(
            f"job {job_id} never reached {status} (last={frappe.db.get_value('Conductor Job', job_id, 'status')})"
        )

    def test_succeeds_round_trip(self):
        job_id = conductor.enqueue("conductor.demo.echo", queue="default", k=42)
        # Run a single worker pass that drains all messages we just enqueued.
        run_worker_once(queues=["default"], concurrency=2, site=frappe.local.site, block_ms=2000)
        self._wait_for_status(job_id, "SUCCEEDED")
        doc = frappe.get_doc("Conductor Job", job_id)
        self.assertEqual(doc.status, "SUCCEEDED")
        self.assertIsNotNone(doc.started_at)
        self.assertIsNotNone(doc.finished_at)
        frappe.delete_doc("Conductor Job", job_id, force=True)

    def test_records_failure(self):
        job_id = conductor.enqueue("conductor.demo.boom", queue="default")
        run_worker_once(queues=["default"], concurrency=2, site=frappe.local.site, block_ms=2000)
        self._wait_for_status(job_id, "FAILED")
        doc = frappe.get_doc("Conductor Job", job_id)
        self.assertEqual(doc.last_error_type, "RuntimeError")
        self.assertIn("intentional failure", doc.last_error_message)
        self.assertIn("RuntimeError", doc.last_traceback)
        frappe.delete_doc("Conductor Job", job_id, force=True)
