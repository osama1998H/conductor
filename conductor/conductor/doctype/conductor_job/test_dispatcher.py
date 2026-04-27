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


class TestDispatcherIdempotency(FrappeTestCase):
    def setUp(self):
        from conductor.client import get_redis
        from conductor.config import load_config
        from conductor.idempotency import idem_redis_key
        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)
        r.delete(idem_redis_key(frappe.local.site, "dup-test-key"))

    def test_duplicate_dispatch_with_same_key_returns_same_job_id(self):
        jid1 = conductor.enqueue(
            "conductor.demo.echo", queue="default", idempotency_key="dup-test-key", x=1,
        )
        jid2 = conductor.enqueue(
            "conductor.demo.echo", queue="default", idempotency_key="dup-test-key", x=2,
        )
        self.assertEqual(jid1, jid2, "second enqueue should return the first job_id")
        rows = frappe.get_all("Conductor Job", filters={"job_id": jid1})
        self.assertEqual(len(rows), 1)
        frappe.delete_doc("Conductor Job", jid1, force=True)


class TestDispatcherDecoratorPullThrough(FrappeTestCase):
    def test_decorator_metadata_stamped_into_message(self):
        from conductor.client import get_redis
        from conductor.config import load_config
        from conductor.streams import stream_key
        from conductor.messages import decode

        from conductor import job as conductor_job
        import conductor.demo as demo_mod

        @conductor_job(queue="default", max_attempts=7, backoff="linear", base_delay_seconds=4)
        def _decorated_echo(**kw):
            return kw
        demo_mod._decorated_echo = _decorated_echo

        try:
            jid = conductor.enqueue("conductor.demo._decorated_echo", k=99)

            cfg = load_config(frappe.local.conf)
            r = get_redis(cfg.redis_url)
            skey = stream_key(frappe.local.site, "default")
            entries = r.xrevrange(skey, count=1)
            _, fields = entries[0]
            decoded = {k.decode(): v.decode() for k, v in fields.items()}
            msg = decode(decoded)

            self.assertEqual(msg.max_attempts, 7)
            self.assertEqual(msg.backoff, "linear")
            self.assertEqual(msg.base_delay_seconds, 4)
            frappe.delete_doc("Conductor Job", jid, force=True)
        finally:
            del demo_mod._decorated_echo


class TestDispatcherDispatchFailedSingleTxn(FrappeTestCase):
    def test_xadd_failure_uses_single_db_transaction(self):
        import redis
        from unittest.mock import patch

        def _boom(*a, **kw):
            raise redis.exceptions.ConnectionError("simulated XADD failure")

        with patch("conductor.dispatcher.get_redis") as mock_get:
            fake_client = type("FakeRedis", (), {})()
            fake_client.xadd = _boom
            fake_client.xgroup_create = lambda *a, **kw: None
            fake_client.set = lambda *a, **kw: True  # idempotency lock acquires fine
            fake_client.get = lambda *a, **kw: None
            mock_get.return_value = fake_client

            try:
                conductor.enqueue("conductor.demo.echo", queue="default", x=1)
                self.fail("expected ConnectionError")
            except redis.exceptions.ConnectionError:
                pass

        rows = frappe.get_all(
            "Conductor Job",
            filters={"status": "DISPATCH_FAILED"},
            fields=["name", "last_error_type", "last_error_message"],
            order_by="enqueued_at desc",
            limit=1,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].last_error_type, "ConnectionError")
        self.assertIn("simulated", rows[0].last_error_message)
        frappe.delete_doc("Conductor Job", rows[0].name, force=True)
