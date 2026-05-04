"""Tests for `conductor.api.workflows` — Plan-3 Phase B.1 (D3 fix)."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.types.frappedict import _dict


def _stub_frappe_local(monkeypatch):
    """Set the minimal frappe.local.flags stub needed when calling
    @frappe.whitelist()-wrapped functions outside a site context.
    The decorator's in_request_or_test lambda reads local.flags.in_test."""
    monkeypatch.setattr(frappe.local, "flags", _dict(in_test=False), raising=False)


def test_list_runs_treats_string_null_as_none(monkeypatch):
    """Defensive against frontend serialization mishaps. The dashboard's
    JS used to ship `?workflow=null` (literal string) when no workflow
    was selected; the backend would then filter by workflow named "null"
    and return nothing. The frontend now omits the parameter entirely,
    but the backend defense remains so future analogous mishaps
    (`"undefined"`, etc.) don't silently break the runs table."""
    _stub_frappe_local(monkeypatch)
    from conductor.api import workflows

    captured = {}

    def fake_get_all(doctype, filters=None, **kwargs):
        captured["filters"] = filters or {}
        return []

    with patch("conductor.api.workflows.frappe.get_all", side_effect=fake_get_all), \
         patch("conductor.api.workflows._require_read"):
        workflows.list_runs(workflow="null", limit=50)

    # The literal string "null" must be stripped from the filter.
    assert "workflow" not in captured["filters"], (
        "list_runs(workflow='null') must omit the workflow filter, "
        "not pass workflow='null' to frappe.get_all."
    )


def test_list_runs_treats_string_undefined_as_none(monkeypatch):
    """Belt-and-suspenders for 'undefined' — different JS serializers
    emit different sentinels for missing values."""
    _stub_frappe_local(monkeypatch)
    from conductor.api import workflows

    captured = {}

    def fake_get_all(doctype, filters=None, **kwargs):
        captured["filters"] = filters or {}
        return []

    with patch("conductor.api.workflows.frappe.get_all", side_effect=fake_get_all), \
         patch("conductor.api.workflows._require_read"):
        workflows.list_runs(workflow="undefined", status="undefined", limit=50)

    assert "workflow" not in captured["filters"]
    assert "status" not in captured["filters"]


def test_list_runs_passes_real_workflow_filter(monkeypatch):
    """Sanity: an actual workflow name still gets passed through."""
    _stub_frappe_local(monkeypatch)
    from conductor.api import workflows

    captured = {}

    def fake_get_all(doctype, filters=None, **kwargs):
        captured["filters"] = filters or {}
        return []

    with patch("conductor.api.workflows.frappe.get_all", side_effect=fake_get_all), \
         patch("conductor.api.workflows._require_read"):
        workflows.list_runs(workflow="DemoDiamond", limit=50)

    assert captured["filters"].get("workflow") == "DemoDiamond"
