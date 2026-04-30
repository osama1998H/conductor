"""Unit tests for the cron loop — fire_schedule and one-shot loop iteration.

These exercise the loop body directly rather than spinning a real thread."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from conductor.scheduler_loops import _fire_schedule_once, _cron_loop_iter


@patch("conductor.scheduler_loops.frappe")
@patch("conductor.scheduler_loops.conductor_enqueue")
def test_fire_schedule_calls_enqueue_with_kwargs(mock_enqueue, mock_frappe):
    mock_enqueue.return_value = "job-123"
    doc = MagicMock()
    doc.method = "myapp.tasks.x"
    doc.queue = "default"
    doc.max_attempts = 5
    doc.kwargs = ""  # no kwargs
    mock_frappe.get_doc.return_value = doc

    now = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    _fire_schedule_once("sched-1", now, mock_frappe)

    mock_enqueue.assert_called_once_with("myapp.tasks.x", queue="default", max_attempts=5)
    doc.db_set.assert_any_call("last_status", "DISPATCHED", update_modified=False)
    doc.db_set.assert_any_call("last_job", "job-123", update_modified=False)


@patch("conductor.scheduler_loops.frappe")
@patch("conductor.scheduler_loops.conductor_enqueue")
def test_fire_schedule_handles_enqueue_failure(mock_enqueue, mock_frappe):
    mock_enqueue.side_effect = RuntimeError("redis down")
    doc = MagicMock()
    doc.method = "myapp.tasks.x"
    doc.queue = "default"
    doc.max_attempts = None
    doc.kwargs = ""
    mock_frappe.get_doc.return_value = doc

    now = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    _fire_schedule_once("sched-1", now, mock_frappe)

    doc.db_set.assert_any_call("last_status", "DISPATCH_FAILED", update_modified=False)
    # last_job is NOT set on failure.
    set_calls = [c for c in doc.db_set.call_args_list if c.args[0] == "last_job"]
    assert set_calls == []


@patch("conductor.scheduler_loops.frappe")
@patch("conductor.scheduler_loops._fire_schedule_once")
def test_cron_loop_iter_picks_only_due_rows(mock_fire, mock_frappe):
    now = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    # frappe.db.sql returns due-row dicts.
    mock_frappe.db.sql.return_value = [{"name": "due-1"}, {"name": "due-2"}]
    _cron_loop_iter(now, mock_frappe)
    assert mock_fire.call_count == 2
    fired_names = sorted(c.args[0] for c in mock_fire.call_args_list)
    assert fired_names == ["due-1", "due-2"]


@patch("conductor.scheduler_loops.frappe")
def test_cron_loop_iter_no_due_rows_is_noop(mock_frappe):
    now = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    mock_frappe.db.sql.return_value = []
    # Should not raise.
    _cron_loop_iter(now, mock_frappe)
