"""Click integration tests for `bench conductor dlq` group.

Uses Click's CliRunner so we don't need a real bench process; the dispatch
into Frappe ORM is mocked out per test.
"""

from unittest.mock import patch

from click.testing import CliRunner


def _fake_dlq_rows():
    return [
        {
            "name": "DLQE-001", "job": "job-A", "queue": "default",
            "moved_at": "2026-04-29 12:00:00",
            "last_error_type": "RuntimeError",
            "last_error_message": "boom",
        },
        {
            "name": "DLQE-002", "job": "job-B", "queue": "critical",
            "moved_at": "2026-04-29 12:01:00",
            "last_error_type": "TimeoutError",
            "last_error_message": "deadline",
        },
    ]


def test_dlq_list_renders_rows():
    from conductor.commands.dlq import dlq_group
    runner = CliRunner()
    with patch("conductor.commands.dlq._fetch_dlq_rows", return_value=_fake_dlq_rows()), \
         patch("conductor.commands.dlq._connect_to_site"), \
         patch("conductor.commands.dlq._disconnect"):
        result = runner.invoke(dlq_group, ["list", "--site", "frappe.localhost"])
    assert result.exit_code == 0, result.output
    assert "DLQE-001" in result.output
    assert "DLQE-002" in result.output
    assert "RuntimeError" in result.output


def test_dlq_list_filter_by_queue():
    from conductor.commands.dlq import dlq_group
    runner = CliRunner()
    captured = {}
    def fake_fetch(filters, limit):
        captured["filters"] = filters
        captured["limit"] = limit
        return [_fake_dlq_rows()[0]]
    with patch("conductor.commands.dlq._fetch_dlq_rows", side_effect=fake_fetch), \
         patch("conductor.commands.dlq._connect_to_site"), \
         patch("conductor.commands.dlq._disconnect"):
        result = runner.invoke(dlq_group, [
            "list", "--site", "frappe.localhost", "--queue", "default",
        ])
    assert result.exit_code == 0, result.output
    assert captured["filters"] == {"queue": "default"}


def test_dlq_list_filter_by_status():
    from conductor.commands.dlq import dlq_group
    runner = CliRunner()
    captured = {}
    def fake_fetch(filters, limit):
        captured["filters"] = filters
        return _fake_dlq_rows()
    with patch("conductor.commands.dlq._fetch_dlq_rows", side_effect=fake_fetch), \
         patch("conductor.commands.dlq._connect_to_site"), \
         patch("conductor.commands.dlq._disconnect"):
        result = runner.invoke(dlq_group, [
            "list", "--site", "frappe.localhost", "--status", "RETRIED",
        ])
    assert result.exit_code == 0
    assert captured["filters"] == {"status": "RETRIED"}
