"""Tests for scheduler_driver.

These run without bench / without a real site — they patch frappe.* into
in-memory fakes. The driver's correctness is verified at the orchestration
level; full end-to-end behavior is exercised by `run_all` in M2.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests.v2_certification import scheduler_driver as sd


def test_list_scheduled_job_types_filters_stopped():
    """Only non-stopped rows are returned."""
    fake_frappe = MagicMock()
    fake_frappe.get_all.return_value = [{"name": "a", "method": "m", "frequency": "Daily", "stopped": 0}]
    with patch.object(sd, "frappe", fake_frappe):
        rows = sd._list_scheduled_job_types()
    fake_frappe.get_all.assert_called_once_with(
        "Scheduled Job Type",
        fields=["name", "method", "frequency", "stopped"],
        filters={"stopped": 0},
        order_by="method",
    )
    assert rows == [{"name": "a", "method": "m", "frequency": "Daily", "stopped": 0}]


def test_trigger_one_records_conductor_job_id_when_dispatched():
    fake_frappe = MagicMock()
    fake_frappe.get_doc.return_value = MagicMock()
    fake_frappe.get_all.return_value = [{
        "name": "CND-JOB-1", "status": "QUEUED", "attempt": 0,
        "creation": "2026-04-30", "modified": "2026-04-30",
    }]
    fake_frappe.db.get_value.return_value = {"status": "SUCCEEDED", "attempt": 1, "modified": "2026-04-30"}
    sjt = {"name": "x", "method": "x.run", "frequency": "Daily"}
    with patch.object(sd, "frappe", fake_frappe):
        result = sd.trigger_one(sjt)
    assert result["conductor_job_id"] == "CND-JOB-1"
    assert result["status"] == "SUCCEEDED"
    assert result["attempt"] == 1
    assert result["error"] is None


def test_trigger_one_reports_error_when_no_conductor_job_appears():
    fake_frappe = MagicMock()
    fake_frappe.get_doc.return_value = MagicMock()
    fake_frappe.get_all.return_value = []
    sjt = {"name": "x", "method": "x.run", "frequency": "Daily"}
    with patch.object(sd, "frappe", fake_frappe):
        result = sd.trigger_one(sjt)
    assert result["conductor_job_id"] is None
    assert "no Conductor Job row" in (result["error"] or "")


def test_trigger_one_reports_error_when_dispatch_raises():
    fake_frappe = MagicMock()
    fake_frappe.get_doc.side_effect = RuntimeError("kaboom")
    sjt = {"name": "x", "method": "x.run", "frequency": "Daily"}
    with patch.object(sd, "frappe", fake_frappe):
        result = sd.trigger_one(sjt)
    assert result["error"] is not None
    assert "kaboom" in result["error"]


def test_run_all_writes_output_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "OUTPUT_PATH", tmp_path / "out.json")
    fake_frappe = MagicMock()
    fake_frappe.get_all.side_effect = [
        [{"name": "a", "method": "a.run", "frequency": "Daily", "stopped": 0}],
        [{"name": "CND-1", "status": "QUEUED", "attempt": 0, "creation": "2026-04-30", "modified": "2026-04-30"}],
    ]
    fake_frappe.get_doc.return_value = MagicMock()
    fake_frappe.db.get_value.return_value = {"status": "SUCCEEDED", "attempt": 1, "modified": "2026-04-30"}
    with patch.object(sd, "frappe", fake_frappe):
        results = sd.run_all()
    assert len(results) == 1
    assert (tmp_path / "out.json").exists()
