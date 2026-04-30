"""Chaos test: dispatcher emits a QUEUED event with correct per-job scoping.

Spec §8.6.1: realtime events must carry doctype="Conductor Job" and
docname=job_id so Socket.IO delivers them to the per-doc room only.
Event-only emits (no doctype/docname) broadcast site-wide via the "all" room —
the regression this test guards against.

Subprocess isolation note: unittest.mock.patch targets the test process's
frappe module. Worker subprocesses import their own frappe and call the
unpatched function, so RUNNING/FAILED/DLQ transitions are invisible to this
capture. The unit test test_emit_targets_doctype_and_docname (in
tests/test_emit_job_event.py) covers the helper-level contract for all
statuses. This test covers the dispatcher's QUEUED emit end-to-end.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe

from conductor.dispatcher import enqueue


def test_dispatcher_emits_queued_event_with_doc_scoping():
    """Dispatcher's QUEUED publish_realtime call carries the per-doc scoping
    fields required by spec §8.6.1."""
    captured = []

    def capture_emit(*args, **kwargs):
        if kwargs.get("event", "").startswith("conductor:job:"):
            captured.append({
                "event": kwargs["event"],
                "status": kwargs["message"]["status"],
                "after_commit": kwargs.get("after_commit"),
                "doctype": kwargs.get("doctype"),
                "docname": kwargs.get("docname"),
            })

    with patch("frappe.publish_realtime", side_effect=capture_emit):
        job_id = enqueue("conductor.demo.boom", queue="default", max_attempts=1)

    queued = [e for e in captured if e["status"] == "QUEUED" and e["event"].endswith(job_id)]
    assert len(queued) == 1, f"expected 1 QUEUED emit, got {len(queued)}: {captured}"
    assert queued[0]["doctype"] == "Conductor Job", (
        f"expected doctype='Conductor Job', got {queued[0]['doctype']!r}; "
        "missing doctype= causes site-wide broadcast (spec §8.6.1 regression)"
    )
    assert queued[0]["docname"] == job_id, (
        f"expected docname={job_id!r}, got {queued[0]['docname']!r}; "
        "missing docname= causes site-wide broadcast (spec §8.6.1 regression)"
    )
    assert queued[0]["after_commit"] is True, (
        f"expected after_commit=True, got {queued[0]['after_commit']!r}"
    )
