"""Tests for `conductor.api.dashboard` — Plan-3 TZ audit additions."""

from __future__ import annotations

from unittest.mock import patch


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
