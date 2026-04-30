"""Smoke tests for install-time defaults (no Frappe required)."""

from conductor.install import DEFAULT_QUEUES


def test_workflow_queue_is_seeded():
    names = {q["queue_name"] for q in DEFAULT_QUEUES}
    assert "workflow" in names, "workflows need a 'workflow' queue for advancer/compensator jobs"


def test_workflow_queue_concurrency_is_at_least_4():
    wf = next(q for q in DEFAULT_QUEUES if q["queue_name"] == "workflow")
    assert wf["concurrency"] >= 4
