import frappe
from frappe.tests.utils import FrappeTestCase


class TestConductorWorker(FrappeTestCase):
    def test_create_and_read(self):
        wid = "test-worker-0001"
        if frappe.db.exists("Conductor Worker", wid):
            frappe.delete_doc("Conductor Worker", wid, force=True)
        doc = frappe.get_doc(
            {
                "doctype": "Conductor Worker",
                "worker_id": wid,
                "host": "localhost",
                "pid": 12345,
                "queues": '["default"]',
                "site": frappe.local.site,
                "status": "ALIVE",
            }
        ).insert(ignore_permissions=True)
        self.assertEqual(doc.name, wid)
        self.assertEqual(doc.status, "ALIVE")
        frappe.delete_doc("Conductor Worker", doc.name, force=True)
