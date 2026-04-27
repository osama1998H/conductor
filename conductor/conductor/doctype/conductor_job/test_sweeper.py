"""Integration tests for conductor.sweeper — recovers orphaned QUEUED rows
that have no redis_msg_id (the dispatch dual-write crash window)."""

import time
from datetime import datetime, timedelta

import frappe
from frappe.tests.utils import FrappeTestCase

from conductor.client import get_redis
from conductor.config import load_config
from conductor.streams import stream_key


class TestOrphanSweeper(FrappeTestCase):
    def setUp(self):
        cfg = load_config(frappe.local.conf)
        self.r = get_redis(cfg.redis_url)
        self.r.delete(stream_key(frappe.local.site, "default"))

    def _insert_orphan(self, age_seconds: int) -> str:
        job_id = f"test-orphan-{int(time.time() * 1000)}-{age_seconds}"
        enq_at = (datetime.now() - timedelta(seconds=age_seconds)).replace(microsecond=0)
        if frappe.db.exists("Conductor Job", job_id):
            frappe.delete_doc("Conductor Job", job_id, force=True)
        if not frappe.db.exists("Conductor Queue", "default"):
            frappe.get_doc({"doctype": "Conductor Queue", "queue_name": "default", "concurrency": 4}).insert(ignore_permissions=True)
        frappe.get_doc({
            "doctype": "Conductor Job",
            "job_id": job_id,
            "queue": "default",
            "method": "conductor.demo.echo",
            "status": "QUEUED",
            "site": frappe.local.site,
            "args": "",
            "kwargs": "",
            "args_preview": "[]",
            "kwargs_preview": "{}",
            "attempt": 1,
            "max_attempts": 3,
            "timeout_seconds": 60,
            "enqueued_at": enq_at,
            "deadline": enq_at + timedelta(seconds=60),
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        return job_id

    def tearDown(self):
        for j in frappe.get_all("Conductor Job", filters={"job_id": ["like", "test-orphan-%"]}, pluck="name"):
            frappe.delete_doc("Conductor Job", j, force=True)

    def test_sweeper_re_xadds_orphan_older_than_threshold(self):
        from conductor.sweeper import sweep_orphans

        old = self._insert_orphan(age_seconds=60)
        sweep_orphans(self.r, frappe.local.site, threshold_seconds=30)

        frappe.db.rollback()
        msg_id = frappe.db.get_value("Conductor Job", old, "redis_msg_id")
        self.assertTrue(msg_id, "orphan should have a redis_msg_id after sweep")
        entries = self.r.xrange(stream_key(frappe.local.site, "default"))
        self.assertTrue(any(mid.decode() == msg_id for mid, _ in entries))

    def test_sweeper_ignores_recent_rows(self):
        from conductor.sweeper import sweep_orphans

        recent = self._insert_orphan(age_seconds=5)
        sweep_orphans(self.r, frappe.local.site, threshold_seconds=30)

        frappe.db.rollback()
        self.assertIsNone(frappe.db.get_value("Conductor Job", recent, "redis_msg_id"))

    def test_sweeper_ignores_already_dispatched(self):
        from conductor.sweeper import sweep_orphans

        old = self._insert_orphan(age_seconds=60)
        frappe.db.set_value("Conductor Job", old, "redis_msg_id", "1234567-0", update_modified=False)
        frappe.db.commit()
        sweep_orphans(self.r, frappe.local.site, threshold_seconds=30)
        frappe.db.rollback()
        self.assertEqual(frappe.db.get_value("Conductor Job", old, "redis_msg_id"), "1234567-0")
