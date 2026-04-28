"""Unit tests for conductor.api.dashboard — whitelisted endpoints + perm guards.

Each endpoint MUST cover the matrix from spec §10.1:
  anonymous → 401, Operator allowed → 200, Operator denied destructive → 403,
  System Manager → 200.

These tests use Frappe's test fixtures + role assignment via _as_user(...).
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
import frappe

from conductor.api import dashboard


def _has_site() -> bool:
    try:
        return bool(frappe.local.site)
    except Exception:
        return False


@contextmanager
def _as_roles(*roles):
    """Patch frappe.get_roles() and frappe.has_permission() to simulate the user."""
    with patch.object(frappe, "get_roles", return_value=list(roles)), \
         patch.object(frappe, "has_permission", return_value=("Conductor Operator" in roles or "System Manager" in roles)):
        yield


def test_require_read_allows_operator():
    with _as_roles("Conductor Operator"):
        dashboard._require_read()  # no raise


def test_require_read_allows_system_manager():
    with _as_roles("System Manager"):
        dashboard._require_read()


def test_require_read_rejects_anonymous():
    with _as_roles(), patch.object(frappe, "has_permission", return_value=False):
        with pytest.raises(frappe.PermissionError):
            dashboard._require_read()


def test_require_destructive_rejects_operator():
    with _as_roles("Conductor Operator"):
        with pytest.raises(frappe.PermissionError):
            dashboard._require_destructive()


def test_require_destructive_allows_system_manager():
    with _as_roles("System Manager"):
        dashboard._require_destructive()


def _seed_jobs():
    """Insert a few Conductor Job rows for snapshot tests."""
    frappe.get_doc({
        "doctype": "Conductor Job", "name": "j1", "job_id": "j1",
        "queue": "default", "method": "x.y", "status": "SUCCEEDED",
        "enqueued_at": "2026-04-28 10:00:00",
    }).insert(ignore_permissions=True)
    frappe.get_doc({
        "doctype": "Conductor Job", "name": "j2", "job_id": "j2",
        "queue": "default", "method": "x.y", "status": "FAILED",
        "enqueued_at": "2026-04-28 10:01:00",
    }).insert(ignore_permissions=True)
    frappe.db.commit()


@pytest.mark.skipif(not _has_site(), reason="needs a Frappe site context")
def test_get_state_shape(monkeypatch):
    """get_state returns the snapshot shape per spec §7.1."""
    with _as_roles("Conductor Operator"):
        monkeypatch.setattr(dashboard, "_redis_queue_depth", lambda site, queue: 0)
        monkeypatch.setattr(dashboard, "_redis_scheduled_count", lambda site: 0)
        state = dashboard.get_state()
    assert "queues" in state
    assert "worker_summary" in state
    assert "dlq_summary" in state
    assert "schedule_summary" in state
    assert "feed_recent" in state
    assert "config" in state
    assert state["config"]["poll_interval_ms"] >= 500


@pytest.mark.skipif(not _has_site(), reason="needs a Frappe site context")
def test_get_state_includes_recent_jobs(monkeypatch):
    _seed_jobs()
    with _as_roles("Conductor Operator"):
        monkeypatch.setattr(dashboard, "_redis_queue_depth", lambda site, queue: 0)
        monkeypatch.setattr(dashboard, "_redis_scheduled_count", lambda site: 0)
        state = dashboard.get_state()
    job_ids = {row["job_id"] for row in state["feed_recent"]}
    assert "j1" in job_ids and "j2" in job_ids


def test_get_state_rejects_anonymous(monkeypatch):
    # @frappe.whitelist() reads frappe.local.flags.in_test before the function
    # body runs; set a minimal stub so the decorator doesn't crash outside a site.
    from frappe.types.frappedict import _dict
    monkeypatch.setattr(frappe.local, "flags", _dict(in_test=False), raising=False)
    with _as_roles(), patch.object(frappe, "has_permission", return_value=False):
        with pytest.raises(frappe.PermissionError):
            dashboard.get_state()


@pytest.mark.skipif(not _has_site(), reason="needs Frappe site context")
def test_get_job_returns_full_detail():
    frappe.get_doc({
        "doctype": "Conductor Job", "name": "jX", "job_id": "jX",
        "queue": "default", "method": "x.y", "status": "FAILED",
        "last_error_type": "ValueError", "last_error_message": "boom",
        "last_traceback": "Traceback…\n  File \"x.py\"\n",
    }).insert(ignore_permissions=True)
    frappe.db.commit()

    with _as_roles("Conductor Operator"):
        result = dashboard.get_job("jX")
    assert result["job_id"] == "jX"
    assert result["last_traceback"].startswith("Traceback")
    assert "runs" in result  # Conductor Job Run rows


def test_retry_job_requires_operator(monkeypatch):
    from frappe.types.frappedict import _dict
    monkeypatch.setattr(frappe.local, "flags", _dict(in_test=False), raising=False)
    with _as_roles(), patch.object(frappe, "has_permission", return_value=False):
        with pytest.raises(frappe.PermissionError):
            dashboard.retry_job("jX")


@pytest.mark.skipif(not _has_site(), reason="needs Frappe site context")
def test_retry_job_calls_enqueue(monkeypatch):
    """retry_job re-dispatches via conductor.enqueue with the original method/kwargs."""
    captured = {}

    def fake_enqueue(method, **kwargs):
        captured["method"] = method
        captured["kwargs"] = kwargs
        return "new-job-id"

    monkeypatch.setattr(dashboard, "_enqueue_for_retry", fake_enqueue)
    with _as_roles("Conductor Operator"):
        new_id = dashboard.retry_job("jX")
    assert new_id == "new-job-id"
    assert captured["method"] == "x.y"


def test_cancel_job_calls_cancellation(monkeypatch):
    from conductor import cancellation as cancel_mod
    from frappe.types.frappedict import _dict
    monkeypatch.setattr(frappe.local, "flags", _dict(in_test=False), raising=False)
    with _as_roles("Conductor Operator"), \
         patch.object(cancel_mod, "cancel", return_value=True) as mock_cancel:
        result = dashboard.cancel_job("jX")
    mock_cancel.assert_called_once_with("jX")
    assert result is True
