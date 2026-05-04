"""Tests for `conductor.api.dashboard` — Plan-3 TZ audit + D4 bulk-action."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def frappe_local_flags():
    """Initialize frappe.local.flags so the whitelist decorator's
    apply_condition() doesn't fail with AttributeError outside a real site.
    Without this, `frappe.whitelist()` → `validate_argument_types`
    checks `local.flags.in_test` on every whitelisted call."""
    import frappe
    frappe.local.flags = frappe._dict(in_test=True)
    yield


def test_get_worker_heartbeat_age_uses_utc_naive_base():
    """Regression for dashboard finding D2: HB age must be computed
    against now_naive() (UTC-naive), matching the heartbeat write path
    in conductor.worker.now_naive. Using local-naive
    frappe.utils.now_datetime would skew age by the host's UTC offset."""
    import inspect
    from conductor.api import dashboard
    src = inspect.getsource(dashboard.get_worker)
    # The age computation must NOT use frappe.utils.now_datetime as the
    # subtraction base (it's local-naive — verified by the controller
    # via grep of frappe/utils/data.py: convert_utc_to_system_timezone(...)
    # then .replace(tzinfo=None)).
    age_lines = [l for l in src.splitlines() if any(
        token in l for token in ("heartbeat_age_seconds", "total_seconds", "last_hb", "delta")
    )]
    blob = "\n".join(age_lines)
    assert "frappe.utils.now_datetime" not in blob, (
        "get_worker still uses frappe.utils.now_datetime (local-naive) "
        "for age computation. Switch to conductor.worker.now_naive."
    )
    assert "now_naive" in blob, "get_worker should call now_naive() in the age computation"


# ---------------------------------------------------------------------------
# D4 bulk-action: dlq_retry + dlq_discard hardening
# ---------------------------------------------------------------------------

def test_dlq_retry_uses_now_naive_for_reviewed_at():
    """Regression: dlq_retry must write reviewed_at via now_naive() (UTC-naive),
    not frappe.utils.now_datetime() (local-naive). Matches the write path
    in the CLI and in get_worker."""
    import inspect
    from conductor.api import dashboard
    src = inspect.getsource(dashboard.dlq_retry)
    assert "frappe.utils.now_datetime" not in src, (
        "dlq_retry still uses frappe.utils.now_datetime for reviewed_at. "
        "Switch to now_naive()."
    )
    assert "now_naive" in src, "dlq_retry should call now_naive() for reviewed_at"


def test_dlq_discard_uses_now_naive_for_reviewed_at():
    """Regression: dlq_discard must write reviewed_at via now_naive()."""
    import inspect
    from conductor.api import dashboard
    src = inspect.getsource(dashboard.dlq_discard)
    assert "frappe.utils.now_datetime" not in src, (
        "dlq_discard still uses frappe.utils.now_datetime for reviewed_at. "
        "Switch to now_naive()."
    )
    assert "now_naive" in src, "dlq_discard should call now_naive() for reviewed_at"


def test_dlq_retry_returns_failed_count_for_nonexistent_names():
    """dlq_retry must not raise for names that don't exist; instead it
    counts them as failed and returns {retried, failed}. Operators issuing
    bulk retries from a stale UI should get useful feedback, not a 500."""
    from conductor.api import dashboard

    enqueued = []
    written = []

    fake_entry = MagicMock()
    fake_entry.status = "PENDING_REVIEW"
    fake_entry.payload = "{}"

    mock_frappe = MagicMock()
    mock_frappe.db.exists.side_effect = lambda doctype, name: name.startswith("DLQE-real-")
    mock_frappe.get_doc.return_value = fake_entry
    mock_frappe.session.user = "Administrator"
    mock_frappe.db.set_value.side_effect = lambda doctype, name, values: written.append(
        (name, values["status"])
    )
    mock_frappe.has_permission.return_value = True
    mock_frappe.get_roles.return_value = ["Conductor Operator"]

    with patch("conductor.api.dashboard._require_read"), \
         patch("conductor.api.dashboard.frappe", mock_frappe), \
         patch("conductor.api.dashboard._dlq_payload_decoded",
               return_value={"method": "x.y", "queue": "default", "kwargs": {}, "args": []}), \
         patch("conductor.api.dashboard._enqueue_for_retry",
               side_effect=lambda method, **kw: enqueued.append(method) or "new-job-id"):
        result = dashboard.dlq_retry(["DLQE-real-001", "nonexistent-x", "nonexistent-y"])

    assert result == {"retried": 1, "failed": 2}
    assert len(enqueued) == 1
    assert written == [("DLQE-real-001", "RETRIED")]


def test_dlq_discard_returns_failed_count_for_nonexistent_names():
    """dlq_discard must not raise for names that don't exist; counts them
    as failed and returns {discarded, failed}."""
    from conductor.api import dashboard

    written = []

    mock_frappe = MagicMock()
    mock_frappe.db.exists.side_effect = lambda doctype, name: name.startswith("DLQE-real-")
    mock_frappe.session.user = "Administrator"
    mock_frappe.db.set_value.side_effect = lambda doctype, name, values: written.append(
        (name, values["status"])
    )

    with patch("conductor.api.dashboard._require_destructive"), \
         patch("conductor.api.dashboard.frappe", mock_frappe):
        result = dashboard.dlq_discard(["DLQE-real-001", "DLQE-real-002", "ghost-entry"])

    assert result == {"discarded": 2, "failed": 1}
    assert written == [
        ("DLQE-real-001", "DISCARDED"),
        ("DLQE-real-002", "DISCARDED"),
    ]
