"""End-to-end: dispatch → worker thread → SUCCEEDED row."""

import time

import frappe
from frappe.tests.utils import FrappeTestCase

import conductor
from conductor.client import get_redis
from conductor.config import load_config
from conductor.streams import stream_key
from conductor.worker import run_worker_once


class TestWorkerE2E(FrappeTestCase):
    def setUp(self):
        # Other tests in this run (e.g., test_dispatcher) leave XADDed stream entries
        # behind when they only delete the Conductor Job row. Clear the stream so the
        # worker pass below drains exactly the message this test enqueues.
        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)
        r.delete(stream_key(frappe.local.site, "default"))

    def _wait_for_status(self, job_id: str, status: str, timeout: float = 5.0):
        end = time.time() + timeout
        while time.time() < end:
            frappe.db.rollback()  # see latest committed state
            doc = frappe.db.get_value("Conductor Job", job_id, "status")
            if doc == status:
                return
            time.sleep(0.1)
        raise AssertionError(
            f"job {job_id} never reached {status} (last={frappe.db.get_value('Conductor Job', job_id, 'status')})"
        )

    def test_succeeds_round_trip(self):
        job_id = conductor.enqueue("conductor.demo.echo", queue="default", k=42)
        # Run a single worker pass that drains all messages we just enqueued.
        run_worker_once(queues=["default"], concurrency=2, site=frappe.local.site, block_ms=2000)
        self._wait_for_status(job_id, "SUCCEEDED")
        doc = frappe.get_doc("Conductor Job", job_id)
        self.assertEqual(doc.status, "SUCCEEDED")
        self.assertIsNotNone(doc.started_at)
        self.assertIsNotNone(doc.finished_at)
        frappe.delete_doc("Conductor Job", job_id, force=True)

    def test_records_failure(self):
        # max_attempts=1 → no retry → immediate DLQ on first failure.
        # Phase 1 moves error fields from Job to the per-attempt Conductor Job Run row.
        job_id = conductor.enqueue("conductor.demo.boom", queue="default", max_attempts=1)
        run_worker_once(queues=["default"], concurrency=2, site=frappe.local.site, block_ms=2000)
        self._wait_for_status(job_id, "DLQ")
        # Error detail lives on the Conductor Job Run row (Phase 1 state machine).
        runs = frappe.get_all(
            "Conductor Job Run",
            filters={"job": job_id},
            fields=["name", "status", "error_type", "error_message", "traceback"],
        )
        self.assertEqual(len(runs), 1)
        run = runs[0]
        self.assertEqual(run.error_type, "RuntimeError")
        self.assertIn("intentional failure", run.error_message)
        self.assertIn("RuntimeError", run.traceback)
        frappe.delete_doc("Conductor Job Run", run.name, force=True)
        dlq = frappe.get_all("Conductor DLQ Entry", filters={"job": job_id}, fields=["name"])
        for d in dlq:
            frappe.delete_doc("Conductor DLQ Entry", d.name, force=True)
        frappe.delete_doc("Conductor Job", job_id, force=True)


class _AlwaysFails:
    """Demo function that always raises RuntimeError."""
    @staticmethod
    def boom_immediately(**kw):
        raise RuntimeError("scheduled-always-fails")


class TestWorkerRetryThenSucceed(FrappeTestCase):
    """A function that fails twice with a retryable error, then succeeds, must
    produce 3 Conductor Job Run rows and final status SUCCEEDED."""

    def setUp(self):
        import conductor.demo as demo_mod
        demo_mod._fail_count = 0

        def flaky(**kw):
            if demo_mod._fail_count < 2:
                demo_mod._fail_count += 1
                raise RuntimeError(f"flaky attempt {demo_mod._fail_count}")
            return {"ok": True, "attempts": demo_mod._fail_count + 1}

        demo_mod.flaky = flaky
        from conductor.client import get_redis
        from conductor.config import load_config
        from conductor.streams import stream_key
        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)
        r.delete(stream_key(frappe.local.site, "default"))

    def tearDown(self):
        import conductor.demo as demo_mod
        if hasattr(demo_mod, "flaky"):
            del demo_mod.flaky
        if hasattr(demo_mod, "_fail_count"):
            del demo_mod._fail_count

    def test_three_attempts_terminal_success(self):
        from conductor.worker import run_worker_once

        jid = conductor.enqueue(
            "conductor.demo.flaky",
            queue="default",
            max_attempts=3,
        )
        from conductor.client import get_redis
        from conductor.config import load_config
        from conductor.scheduled import drain_due_messages
        from conductor.streams import ensure_consumer_group, stream_key
        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)

        for _ in range(6):
            run_worker_once(queues=["default"], concurrency=1, site=frappe.local.site, block_ms=500)
            for encoded in drain_due_messages(r, frappe.local.site, now_ms=int(__import__("time").time() * 1000) + 60_000):
                target = stream_key(frappe.local.site, encoded["queue"])
                ensure_consumer_group(r, target)
                r.xadd(target, encoded, maxlen=10000, approximate=True)
            frappe.db.rollback()
            status = frappe.db.get_value("Conductor Job", jid, "status")
            if status in ("SUCCEEDED", "DLQ"):
                break

        self.assertEqual(frappe.db.get_value("Conductor Job", jid, "status"), "SUCCEEDED")
        runs = frappe.get_all(
            "Conductor Job Run", filters={"job": jid}, fields=["name", "status"], order_by="creation"
        )
        statuses = [r.status for r in runs]
        self.assertEqual(statuses[-1], "SUCCEEDED")
        self.assertEqual(statuses.count("FAILED"), 2)
        for r in runs:
            frappe.delete_doc("Conductor Job Run", r.name, force=True)
        frappe.delete_doc("Conductor Job", jid, force=True)


class TestWorkerExhaustsToDLQ(FrappeTestCase):
    def setUp(self):
        from conductor.client import get_redis
        from conductor.config import load_config
        from conductor.streams import stream_key
        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)
        r.delete(stream_key(frappe.local.site, "default"))

    def test_exhausts_to_dlq(self):
        from conductor.worker import run_worker_once
        from conductor.client import get_redis
        from conductor.config import load_config
        from conductor.scheduled import drain_due_messages
        from conductor.streams import ensure_consumer_group, stream_key

        jid = conductor.enqueue("conductor.demo.boom", queue="default", max_attempts=3)

        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)
        for _ in range(8):
            run_worker_once(queues=["default"], concurrency=1, site=frappe.local.site, block_ms=500)
            for encoded in drain_due_messages(r, frappe.local.site, now_ms=int(__import__("time").time() * 1000) + 60_000):
                target = stream_key(frappe.local.site, encoded["queue"])
                ensure_consumer_group(r, target)
                r.xadd(target, encoded, maxlen=10000, approximate=True)
            frappe.db.rollback()
            if frappe.db.get_value("Conductor Job", jid, "status") == "DLQ":
                break

        self.assertEqual(frappe.db.get_value("Conductor Job", jid, "status"), "DLQ")
        runs = frappe.get_all("Conductor Job Run", filters={"job": jid}, fields=["name", "status"])
        self.assertEqual(len(runs), 3)
        self.assertTrue(all(r.status == "FAILED" for r in runs))
        dlq = frappe.get_all("Conductor DLQ Entry", filters={"job": jid}, fields=["name"])
        self.assertEqual(len(dlq), 1)
        for r in runs:
            frappe.delete_doc("Conductor Job Run", r.name, force=True)
        for d in dlq:
            frappe.delete_doc("Conductor DLQ Entry", d.name, force=True)
        frappe.delete_doc("Conductor Job", jid, force=True)


class TestWorkerNoRetryOnValueError(FrappeTestCase):
    def setUp(self):
        from conductor.client import get_redis
        from conductor.config import load_config
        from conductor.streams import stream_key
        cfg = load_config(frappe.local.conf)
        r = get_redis(cfg.redis_url)
        r.delete(stream_key(frappe.local.site, "default"))

    def test_value_error_in_no_retry_on_terminates_immediately(self):
        from conductor.worker import run_worker_once
        from conductor import job as conductor_job
        import conductor.demo as demo_mod

        @conductor_job(no_retry_on=(ValueError,), max_attempts=10)
        def bad_input_decorated(**kw):
            raise ValueError("nope")
        demo_mod.bad_input_decorated = bad_input_decorated

        try:
            jid = conductor.enqueue("conductor.demo.bad_input_decorated")
            run_worker_once(queues=["default"], concurrency=1, site=frappe.local.site, block_ms=2000)
            frappe.db.rollback()
            self.assertEqual(frappe.db.get_value("Conductor Job", jid, "status"), "DLQ")
            runs = frappe.get_all("Conductor Job Run", filters={"job": jid}, fields=["name"])
            self.assertEqual(len(runs), 1)
            for r in runs:
                frappe.delete_doc("Conductor Job Run", r.name, force=True)
            dlq = frappe.get_all("Conductor DLQ Entry", filters={"job": jid}, fields=["name"])
            for d in dlq:
                frappe.delete_doc("Conductor DLQ Entry", d.name, force=True)
            frappe.delete_doc("Conductor Job", jid, force=True)
        finally:
            del demo_mod.bad_input_decorated
