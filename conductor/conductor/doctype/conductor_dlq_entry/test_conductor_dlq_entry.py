import frappe
from frappe.tests.utils import FrappeTestCase


class TestConductorDLQEntry(FrappeTestCase):
    def setUp(self):
        self.job_id = "test-dlq-parent-0001"
        if not frappe.db.exists("Conductor Queue", "default"):
            frappe.get_doc({"doctype": "Conductor Queue", "queue_name": "default", "concurrency": 4}).insert(ignore_permissions=True)
        if frappe.db.exists("Conductor Job", self.job_id):
            frappe.delete_doc("Conductor Job", self.job_id, force=True)
        frappe.get_doc({
            "doctype": "Conductor Job",
            "job_id": self.job_id,
            "queue": "default",
            "method": "conductor.demo.echo",
            "status": "DLQ",
            "site": frappe.local.site,
        }).insert(ignore_permissions=True)

    def tearDown(self):
        if frappe.db.exists("Conductor Job", self.job_id):
            frappe.delete_doc("Conductor Job", self.job_id, force=True)

    def test_create_with_default_status(self):
        doc = frappe.get_doc({
            "doctype": "Conductor DLQ Entry",
            "job": self.job_id,
            "queue": "default",
            "attempts": 3,
            "last_error_type": "RuntimeError",
            "last_error_message": "boom",
        }).insert(ignore_permissions=True)
        self.assertEqual(doc.status, "PENDING_REVIEW")
        self.assertEqual(doc.attempts, 3)
        frappe.delete_doc("Conductor DLQ Entry", doc.name, force=True)
