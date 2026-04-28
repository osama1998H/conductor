"""Unit tests for emit_job_event — the per-job realtime emit helper."""

from unittest.mock import patch

from conductor.messages import emit_job_event


def test_emit_event_name_is_per_job():
    with patch("frappe.publish_realtime") as mock_pub:
        emit_job_event("abc-123", "RUNNING")
    args, kwargs = mock_pub.call_args
    assert kwargs["event"] == "conductor:job:abc-123"


def test_emit_payload_carries_status_and_job_id():
    with patch("frappe.publish_realtime") as mock_pub:
        emit_job_event("abc-123", "RUNNING")
    msg = mock_pub.call_args.kwargs["message"]
    assert msg["job_id"] == "abc-123"
    assert msg["status"] == "RUNNING"


def test_emit_payload_includes_extra_fields():
    with patch("frappe.publish_realtime") as mock_pub:
        emit_job_event(
            "abc-123",
            "FAILED",
            attempt=3,
            max_attempts=3,
            queue="default",
            method="x.y.z",
            last_error_type="TimeoutError",
            last_error_message="boom",
        )
    msg = mock_pub.call_args.kwargs["message"]
    assert msg["attempt"] == 3
    assert msg["last_error_type"] == "TimeoutError"


def test_emit_payload_has_unix_ts():
    with patch("frappe.publish_realtime") as mock_pub:
        emit_job_event("abc-123", "QUEUED")
    msg = mock_pub.call_args.kwargs["message"]
    assert isinstance(msg["ts"], int)
    assert msg["ts"] > 0


def test_emit_uses_after_commit():
    with patch("frappe.publish_realtime") as mock_pub:
        emit_job_event("abc-123", "QUEUED")
    assert mock_pub.call_args.kwargs["after_commit"] is True


def test_emit_targets_doctype_and_docname():
    """Per spec §8.6.1: delivery scope is doctype/docname; event= is just a label."""
    with patch("frappe.publish_realtime") as mock_pub:
        emit_job_event("abc-123", "RUNNING")
    kwargs = mock_pub.call_args.kwargs
    assert kwargs["doctype"] == "Conductor Job"
    assert kwargs["docname"] == "abc-123"


def test_emit_does_not_include_traceback():
    """Tracebacks can be tens of KB; not in the realtime payload."""
    with patch("frappe.publish_realtime") as mock_pub:
        emit_job_event("abc-123", "FAILED", last_traceback="x" * 10_000)
    msg = mock_pub.call_args.kwargs["message"]
    assert "last_traceback" not in msg
