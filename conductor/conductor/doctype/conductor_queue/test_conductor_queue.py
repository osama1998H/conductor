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


class TestConductorQueuePhase6Fields(FrappeTestCase):
    def test_default_queue_has_max_rps_field_default_zero(self):
        q = frappe.get_doc("Conductor Queue", "default")
        assert hasattr(q, "max_rps"), "max_rps field missing on Conductor Queue"
        assert int(q.max_rps or 0) == 0, "max_rps default must be 0 (unlimited)"

    def test_default_queue_has_max_concurrent_field_default_zero(self):
        q = frappe.get_doc("Conductor Queue", "default")
        assert hasattr(q, "max_concurrent"), "max_concurrent field missing"
        assert int(q.max_concurrent or 0) == 0, "max_concurrent default must be 0"

    def test_can_set_and_persist_limits(self):
        q = frappe.get_doc("Conductor Queue", "default")
        q.max_rps = 50
        q.max_concurrent = 10
        q.save(ignore_permissions=True)
        frappe.db.commit()
        # Re-fetch (skip cache)
        frappe.clear_document_cache("Conductor Queue", "default")
        q2 = frappe.get_doc("Conductor Queue", "default")
        assert int(q2.max_rps) == 50
        assert int(q2.max_concurrent) == 10
        # Reset for other tests
        q2.max_rps = 0
        q2.max_concurrent = 0
        q2.save(ignore_permissions=True)
        frappe.db.commit()
