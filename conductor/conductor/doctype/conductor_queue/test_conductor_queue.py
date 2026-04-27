import frappe
from frappe.tests.utils import FrappeTestCase


class TestConductorQueue(FrappeTestCase):
    def test_create_and_read(self):
        if frappe.db.exists("Conductor Queue", "test_queue"):
            frappe.delete_doc("Conductor Queue", "test_queue", force=True)
        doc = frappe.get_doc(
            {
                "doctype": "Conductor Queue",
                "queue_name": "test_queue",
                "concurrency": 2,
            }
        ).insert()
        self.assertEqual(doc.name, "test_queue")
        self.assertEqual(doc.concurrency, 2)
        self.assertEqual(doc.enabled, 1)
        self.assertEqual(doc.default_max_attempts, 3)

    def test_concurrency_validation(self):
        if frappe.db.exists("Conductor Queue", "bad_queue"):
            frappe.delete_doc("Conductor Queue", "bad_queue", force=True)
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {"doctype": "Conductor Queue", "queue_name": "bad_queue", "concurrency": 0}
            ).insert()
