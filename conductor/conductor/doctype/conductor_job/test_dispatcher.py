import json

import frappe
from frappe.tests.utils import FrappeTestCase

import conductor


class TestDispatcher(FrappeTestCase):
    def test_enqueue_creates_queued_row_and_returns_job_id(self):
        job_id = conductor.enqueue("conductor.demo.echo", queue="default", x=1, msg="hi")
        self.assertIsInstance(job_id, str)
        self.assertGreater(len(job_id), 0)

        doc = frappe.get_doc("Conductor Job", job_id)
        self.assertEqual(doc.status, "QUEUED")
        self.assertEqual(doc.method, "conductor.demo.echo")
        self.assertEqual(doc.queue, "default")
        self.assertEqual(doc.attempt, 1)
        self.assertIsNotNone(doc.enqueued_at)
        self.assertTrue(doc.kwargs)  # base64-msgpack non-empty
        # Preview should be human-readable JSON
        preview = json.loads(doc.kwargs_preview)
        self.assertEqual(preview, {"x": 1, "msg": "hi"})
        # Cleanup
        frappe.delete_doc("Conductor Job", job_id, force=True)

    def test_enqueue_writes_message_to_redis_stream(self):
        from conductor.client import get_redis
        from conductor.config import load_config
        from conductor.streams import stream_key
        from conductor.messages import decode

        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)
        skey = stream_key(frappe.local.site, "default")

        job_id = conductor.enqueue("conductor.demo.echo", queue="default", k=42)
        # Read the latest entry; we don't ack here (no consumer group used).
        entries = r.xrevrange(skey, count=1)
        self.assertEqual(len(entries), 1)
        _, fields = entries[0]
        decoded = {k.decode(): v.decode() for k, v in fields.items()}
        msg = decode(decoded)
        self.assertEqual(msg.job_id, job_id)
        self.assertEqual(msg.method, "conductor.demo.echo")
        self.assertEqual(msg.kwargs, {"k": 42})
        # Cleanup
        frappe.delete_doc("Conductor Job", job_id, force=True)
