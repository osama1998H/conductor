"""Unit test for the reaper's drift-correction pass on rate-limit and concurrency counters."""

from unittest.mock import MagicMock, patch

import pytest

from conductor.scheduler_loops import _reaper_drift_correction_iter


@pytest.fixture
def fake_frappe(monkeypatch):
    fake = MagicMock()
    fake.db = MagicMock()
    monkeypatch.setattr(
        "conductor.scheduler_loops.frappe", fake, raising=False,
    )
    return fake


def test_no_gone_workers_no_correction(fake_redis, fake_frappe):
    """If no workers were just-marked GONE, the function is a no-op."""
    fake_frappe.db.sql.return_value = []  # no rows
    with patch("conductor.scheduler_loops.correct_drift") as mock_correct:
        _reaper_drift_correction_iter(
            fake_redis, "frappe.localhost", just_gone_worker_ids=[]
        )
    assert mock_correct.call_count == 0


def test_one_gone_worker_with_one_running_job(fake_redis, fake_frappe):
    fake_frappe.db.sql.return_value = [
        {"queue": "default", "running_count": 1},
    ]
    with patch("conductor.scheduler_loops.correct_drift") as mock_correct:
        _reaper_drift_correction_iter(
            fake_redis, "alpha.test",
            just_gone_worker_ids=["host:1234:abc"],
        )
    mock_correct.assert_called_once_with(
        fake_redis, "alpha.test", "default", decrement_by=1,
    )


def test_multiple_workers_grouped_by_queue(fake_redis, fake_frappe):
    fake_frappe.db.sql.return_value = [
        {"queue": "default", "running_count": 3},
        {"queue": "critical", "running_count": 1},
    ]
    with patch("conductor.scheduler_loops.correct_drift") as mock_correct:
        _reaper_drift_correction_iter(
            fake_redis, "alpha.test",
            just_gone_worker_ids=["w1", "w2", "w3"],
        )
    assert mock_correct.call_count == 2
    seen = {(c.args[2], c.kwargs["decrement_by"]) for c in mock_correct.call_args_list}
    assert seen == {("default", 3), ("critical", 1)}


def test_drift_correction_does_not_modify_job_rows(fake_redis, fake_frappe):
    """Critical: status='RUNNING' rows are LEFT ALONE — XAUTOCLAIM owns
    message recovery; we only fix the counter."""
    fake_frappe.db.sql.return_value = [{"queue": "default", "running_count": 2}]
    update_calls = []
    fake_frappe.db.set_value = lambda *a, **k: update_calls.append((a, k))
    with patch("conductor.scheduler_loops.correct_drift"):
        _reaper_drift_correction_iter(
            fake_redis, "alpha.test", just_gone_worker_ids=["w1", "w2"],
        )
    assert update_calls == []
