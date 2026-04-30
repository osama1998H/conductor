"""Realtime event emission for workflow runs (no Frappe required for shape)."""

from unittest.mock import patch

from conductor.messages import emit_workflow_event


def test_emit_workflow_event_publishes_to_run_room():
    with patch("frappe.publish_realtime") as pr:
        emit_workflow_event(
            run_id="WR-0001-2026", status="RUNNING",
            workflow="MyFlow", definition_version=2,
        )
    assert pr.called
    call = pr.call_args
    assert call.kwargs["doctype"] == "Conductor Workflow Run"
    assert call.kwargs["docname"] == "WR-0001-2026"
    assert call.kwargs["event"] == "conductor:workflow_run:WR-0001-2026"
    payload = call.kwargs["message"]
    assert payload["run_id"] == "WR-0001-2026"
    assert payload["status"] == "RUNNING"
    assert payload["workflow"] == "MyFlow"
    assert payload["definition_version"] == 2


def test_emit_workflow_event_drops_unknown_fields():
    with patch("frappe.publish_realtime") as pr:
        emit_workflow_event(
            run_id="WR-0001-2026", status="RUNNING",
            secret_field="should-not-appear",
        )
    payload = pr.call_args.kwargs["message"]
    assert "secret_field" not in payload
