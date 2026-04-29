"""Frappe-integration tests for run_workflow() dispatcher (no advancer enqueue)."""

from __future__ import annotations

import unittest

import frappe

from conductor.workflow import Step, workflow
from conductor.workflow.decorator import _REGISTRY
from conductor.workflow.keys import wfdeps_key
from conductor.client import get_redis
from conductor.config import load_config


def _make_diamond(name: str = "DiamondTestFlow"):
    _REGISTRY.pop(name, None)

    @workflow(name=name, queue="default")
    class Diamond:
        _a = Step("a")
        _b = Step("b", depends_on=("a",), compensation="undo_b")
        _c = Step("c", depends_on=("a",))
        _d = Step("d", depends_on=("b", "c"))
        def a(self): pass
        def b(self): pass
        def undo_b(self): pass
        def c(self): pass
        def d(self): pass
    return Diamond


def _redis():
    cfg = load_config(frappe.local.conf)
    return get_redis(cfg.redis_url)


class TestRunWorkflowDispatch(unittest.TestCase):
    def setUp(self):
        from conductor.workflow.dispatcher import _ENQUEUE_ADVANCER_HOOK
        # The hook is set by Task 12; for this task it's None and dispatch must
        # still succeed (advancer simply isn't fired).
        self.workflow_cls = _make_diamond()
        if not frappe.db.exists("Conductor Queue", "default"):
            frappe.get_doc({
                "doctype": "Conductor Queue", "queue_name": "default", "enabled": 1,
            }).insert(ignore_permissions=True)
            frappe.db.commit()

    def tearDown(self):
        for n in frappe.get_all("Conductor Workflow Step Run", pluck="name"):
            frappe.delete_doc("Conductor Workflow Step Run", n, force=True)
        for n in frappe.get_all("Conductor Workflow Run", pluck="name"):
            frappe.delete_doc("Conductor Workflow Run", n, force=True)
        for n in frappe.get_all("Conductor Workflow", pluck="name"):
            frappe.delete_doc("Conductor Workflow", n, force=True)
        frappe.db.commit()
        # Clean Redis wfdeps keys
        r = _redis()
        for k in r.scan_iter("conductor:*:wfdeps:*"):
            r.delete(k)
        for k in r.scan_iter("conductor:*:wfidem:*"):
            r.delete(k)

    def test_first_dispatch_creates_workflow_row_at_version_1(self):
        from conductor.workflow.dispatcher import run_workflow
        run_id = run_workflow("DiamondTestFlow", order_id=42)
        self.assertTrue(run_id.startswith("WR-"))
        wf = frappe.get_doc("Conductor Workflow", "DiamondTestFlow")
        self.assertEqual(wf.version, 1)
        self.assertIn('"name":"DiamondTestFlow"', wf.definition_snapshot)

    def test_dispatch_inserts_one_step_row_per_step_status_pending(self):
        from conductor.workflow.dispatcher import run_workflow
        run_id = run_workflow("DiamondTestFlow", order_id=42)
        rows = frappe.get_all(
            "Conductor Workflow Step Run",
            filters={"workflow_run": run_id},
            fields=["step_id", "status", "is_compensation"],
        )
        self.assertEqual(len(rows), 4)
        self.assertEqual({r["step_id"] for r in rows}, {"a", "b", "c", "d"})
        self.assertTrue(all(r["status"] == "PENDING" for r in rows))
        self.assertTrue(all(r["is_compensation"] == 0 for r in rows))

    def test_dispatch_seeds_wfdeps_hash(self):
        from conductor.workflow.dispatcher import run_workflow
        run_id = run_workflow("DiamondTestFlow", order_id=42)
        site = frappe.local.site
        deps = _redis().hgetall(wfdeps_key(site, run_id))
        decoded = {k.decode(): int(v) for k, v in deps.items()}
        self.assertEqual(decoded, {"a": 0, "b": 1, "c": 1, "d": 2})

    def test_idempotent_dispatch_returns_first_run_id(self):
        from conductor.workflow.dispatcher import run_workflow
        a = run_workflow("DiamondTestFlow", order_id=42, idempotency_key="ord-42")
        b = run_workflow("DiamondTestFlow", order_id=42, idempotency_key="ord-42")
        self.assertEqual(a, b)
        # Only one run row
        runs = frappe.get_all("Conductor Workflow Run")
        self.assertEqual(len(runs), 1)

    def test_topology_change_bumps_version(self):
        from conductor.workflow.dispatcher import run_workflow
        run_workflow("DiamondTestFlow", order_id=42)
        v1 = frappe.get_value("Conductor Workflow", "DiamondTestFlow", "version")
        self.assertEqual(v1, 1)

        # Re-decorate with a structurally different DAG, same name
        _REGISTRY.pop("DiamondTestFlow", None)

        @workflow(name="DiamondTestFlow", queue="default")
        class V2:
            _a = Step("a")
            _b = Step("b", depends_on=("a",))
            _c = Step("c", depends_on=("a", "b"))   # added dep on b
            _d = Step("d", depends_on=("b", "c"))
            def a(self): pass
            def b(self): pass
            def c(self): pass
            def d(self): pass

        run_workflow("DiamondTestFlow", order_id=99)
        v2 = frappe.get_value("Conductor Workflow", "DiamondTestFlow", "version")
        self.assertEqual(v2, 2)

    def test_unknown_workflow_raises(self):
        from conductor.workflow.dispatcher import run_workflow
        from conductor.workflow.dispatcher import WorkflowNotFoundError
        with self.assertRaises(WorkflowNotFoundError):
            run_workflow("NonExistentFlow")
