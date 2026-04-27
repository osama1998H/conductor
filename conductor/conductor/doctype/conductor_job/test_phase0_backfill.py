"""Backfill of the four Phase 0 §11 integration tests not implemented in Phase 0."""

import subprocess
import time

import frappe
from frappe.tests.utils import FrappeTestCase

import conductor
from conductor.client import get_redis
from conductor.config import load_config
from conductor.streams import stream_key


class TestWorkerRecordsTimeout(FrappeTestCase):
    def setUp(self):
        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)
        r.delete(stream_key(frappe.local.site, "default"))

    def test_timeout_writes_TIMED_OUT_run_row(self):
        from conductor.worker import run_worker_once
        from conductor import job as conductor_job
        import conductor.demo as demo_mod

        @conductor_job(no_retry_on=(Exception,), max_attempts=1)
        def slow_decorated(**kw):
            deadline = time.time() + 5
            while time.time() < deadline:
                time.sleep(0.05)
                if conductor.context.should_cancel():
                    raise TimeoutError("deadline exceeded")
            return {"finished": True}
        demo_mod.slow_decorated = slow_decorated

        try:
            jid = conductor.enqueue("conductor.demo.slow_decorated", queue="default", timeout=1)
            run_worker_once(queues=["default"], concurrency=1, site=frappe.local.site, block_ms=3000)
            frappe.db.rollback()
            runs = frappe.get_all(
                "Conductor Job Run", filters={"job": jid}, fields=["name", "status", "error_type"]
            )
            self.assertTrue(any(r.status == "TIMED_OUT" for r in runs),
                            f"expected at least one TIMED_OUT run; got {[r.status for r in runs]}")
            for r in runs:
                frappe.delete_doc("Conductor Job Run", r.name, force=True)
            dlq = frappe.get_all("Conductor DLQ Entry", filters={"job": jid}, fields=["name"])
            for d in dlq:
                frappe.delete_doc("Conductor DLQ Entry", d.name, force=True)
            frappe.delete_doc("Conductor Job", jid, force=True)
        finally:
            del demo_mod.slow_decorated


class TestDoctorCleanInstall(FrappeTestCase):
    def test_doctor_no_demo_exits_zero_in_clean_install(self):
        proc = subprocess.run(
            ["bench", "--site", frappe.local.site, "conductor", "doctor"],
            cwd="/Users/osamamuhammed/frappe_15",
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout}\nstderr={proc.stderr}")


class TestDoctorRedisDown(FrappeTestCase):
    def test_doctor_exits_one_when_redis_unreachable(self):
        from unittest.mock import patch
        from conductor.doctor import run

        class _BoomRedis:
            def ping(self): raise ConnectionError("simulated")
            def xadd(self, *a, **kw): raise ConnectionError("simulated")
            def xreadgroup(self, *a, **kw): raise ConnectionError("simulated")
            def delete(self, *a, **kw): raise ConnectionError("simulated")
            def xack(self, *a, **kw): raise ConnectionError("simulated")
            def xgroup_create(self, *a, **kw): raise ConnectionError("simulated")

        with patch("conductor.doctor.get_redis", return_value=_BoomRedis()):
            rc = run(demo=False)
        self.assertEqual(rc, 1)


class TestFrappeCompatShim(FrappeTestCase):
    def test_compat_shim_produces_equivalent_job(self):
        from conductor.frappe_compat import enqueue
        jid = enqueue("conductor.demo.echo", queue="default", x=1, msg="hi")
        self.assertIsInstance(jid, str)
        doc = frappe.get_doc("Conductor Job", jid)
        self.assertEqual(doc.method, "conductor.demo.echo")
        self.assertEqual(doc.queue, "default")
        self.assertEqual(doc.status, "QUEUED")
        frappe.delete_doc("Conductor Job", jid, force=True)
