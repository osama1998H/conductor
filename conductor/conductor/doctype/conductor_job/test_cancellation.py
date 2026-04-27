"""Integration tests for conductor.cancellation."""

from datetime import datetime, timezone

import frappe
from frappe.tests.utils import FrappeTestCase

import conductor
from conductor.messages import JobMessage


def _sample_message(**overrides) -> JobMessage:
    base = JobMessage(
        job_id="11111111-1111-1111-1111-111111111111",
        site="frappe.localhost",
        method="conductor.demo.echo",
        queue="default",
        kwargs={"x": 1},
        attempt=1,
        max_attempts=1,
        timeout_seconds=60,
        enqueued_at=datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc),
        deadline=None,
        trace_parent="",
        idempotency_key="",
        workflow_run_id="",
        step_id="",
    )
    return base.replace(**overrides) if overrides else base


class TestCancelQueuedJob(FrappeTestCase):
    def setUp(self):
        from conductor.client import get_redis
        from conductor.config import load_config
        from conductor.streams import stream_key
        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)
        r.delete(stream_key(frappe.local.site, "default"))

    def test_cancel_returns_true_and_sets_status(self):
        jid = conductor.enqueue("conductor.demo.echo", queue="default")
        ok = conductor.cancel(jid)
        self.assertTrue(ok)
        self.assertEqual(frappe.db.get_value("Conductor Job", jid, "status"), "CANCELLED")
        frappe.delete_doc("Conductor Job", jid, force=True)

    def test_cancel_already_terminal_returns_false(self):
        jid = conductor.enqueue("conductor.demo.echo", queue="default")
        frappe.db.set_value("Conductor Job", jid, "status", "SUCCEEDED", update_modified=False)
        frappe.db.commit()
        ok = conductor.cancel(jid)
        self.assertFalse(ok)
        self.assertEqual(frappe.db.get_value("Conductor Job", jid, "status"), "SUCCEEDED")
        frappe.delete_doc("Conductor Job", jid, force=True)

    def test_cancel_unknown_job_returns_false(self):
        self.assertFalse(conductor.cancel("nonexistent-job-id"))

    def test_cancel_scheduled_retry_removes_from_zset(self):
        from conductor.client import get_redis
        from conductor.config import load_config
        from conductor.messages import encode
        from conductor.scheduled import schedule_message, scheduled_redis_key
        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)

        jid = conductor.enqueue("conductor.demo.echo", queue="default")
        msg = _sample_message().replace(job_id=jid)
        encoded = encode(msg)
        schedule_message(r, frappe.local.site, encoded, run_at_ms=999_999_999_999)
        frappe.db.set_value("Conductor Job", jid, "status", "SCHEDULED_RETRY", update_modified=False)
        frappe.db.commit()

        before = r.zcard(scheduled_redis_key(frappe.local.site))
        ok = conductor.cancel(jid)
        after = r.zcard(scheduled_redis_key(frappe.local.site))
        self.assertTrue(ok)
        self.assertEqual(after, before - 1)
        self.assertEqual(frappe.db.get_value("Conductor Job", jid, "status"), "CANCELLED")
        frappe.delete_doc("Conductor Job", jid, force=True)
