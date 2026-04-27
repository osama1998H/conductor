import frappe
from frappe.tests.utils import FrappeTestCase


class TestConductorJob(FrappeTestCase):
    def setUp(self):
        if not frappe.db.exists("Conductor Queue", "default"):
            frappe.get_doc(
                {"doctype": "Conductor Queue", "queue_name": "default", "concurrency": 4}
            ).insert(ignore_permissions=True)

    def test_can_create_and_read_minimal_row(self):
        doc = frappe.get_doc(
            {
                "doctype": "Conductor Job",
                "job_id": "test-uuid-0001",
                "queue": "default",
                "method": "conductor.demo.echo",
                "status": "QUEUED",
                "attempt": 1,
                "max_attempts": 1,
                "timeout_seconds": 60,
                "site": frappe.local.site,
            }
        ).insert(ignore_permissions=True)
        self.assertEqual(doc.name, "test-uuid-0001")
        self.assertEqual(doc.status, "QUEUED")
        frappe.delete_doc("Conductor Job", doc.name, force=True)
