import frappe
from frappe.tests.utils import FrappeTestCase


class TestConductorJobRun(FrappeTestCase):
    def setUp(self):
        # Job Run requires a Conductor Job; create a minimal one.
        self.job_id = "test-jobrun-parent-0001"
        if not frappe.db.exists("Conductor Queue", "default"):
            frappe.get_doc({"doctype": "Conductor Queue", "queue_name": "default", "concurrency": 4}).insert(ignore_permissions=True)
        if frappe.db.exists("Conductor Job", self.job_id):
            frappe.delete_doc("Conductor Job", self.job_id, force=True)
        frappe.get_doc({
            "doctype": "Conductor Job",
            "job_id": self.job_id,
            "queue": "default",
            "method": "conductor.demo.echo",
            "status": "QUEUED",
            "site": frappe.local.site,
        }).insert(ignore_permissions=True)

    def tearDown(self):
        if frappe.db.exists("Conductor Job", self.job_id):
            frappe.delete_doc("Conductor Job", self.job_id, force=True)

    def test_create_and_read(self):
        doc = frappe.get_doc({
            "doctype": "Conductor Job Run",
            "job": self.job_id,
            "attempt_number": 1,
            "status": "SUCCEEDED",
            "worker_id": "test-worker",
            "duration_ms": 42,
        }).insert(ignore_permissions=True)
        self.assertEqual(doc.attempt_number, 1)
        self.assertEqual(doc.status, "SUCCEEDED")
        frappe.delete_doc("Conductor Job Run", doc.name, force=True)
