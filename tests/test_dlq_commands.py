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
        result = runner.invoke(
            dlq_group,
            ["list", "--site", "frappe.localhost"],
            obj={"sites": ["frappe.localhost"], "profile": False},
        )
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
        result = runner.invoke(
            dlq_group,
            ["list", "--site", "frappe.localhost", "--queue", "default"],
            obj={"sites": ["frappe.localhost"], "profile": False},
        )
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
        result = runner.invoke(
            dlq_group,
            ["list", "--site", "frappe.localhost", "--status", "RETRIED"],
            obj={"sites": ["frappe.localhost"], "profile": False},
        )
    assert result.exit_code == 0
    assert captured["filters"] == {"status": "RETRIED"}


def test_dlq_retry_re_enqueues_pending_rows():
    from conductor.commands.dlq import dlq_group
    runner = CliRunner()
    rows = [
        {
            "name": "DLQE-001", "job": "job-A", "queue": "default",
            "method": "conductor.demo.echo", "args_b64": "", "kwargs_b64": "",
            "status": "PENDING_REVIEW",
        },
    ]
    enqueued: list[tuple[str, str, dict]] = []
    flipped: list[tuple[str, str, dict]] = []
    def fake_enqueue(method, *, queue, **kwargs):
        enqueued.append((method, queue, dict(kwargs)))
        return "new-job-id"
    def fake_flip(name, payload):
        flipped.append((name, payload["status"], dict(payload)))
    with patch("conductor.commands.dlq._fetch_pending_rows", return_value=rows), \
         patch("conductor.commands.dlq._enqueue_from_dlq_row", side_effect=fake_enqueue), \
         patch("conductor.commands.dlq._mark_dlq_row", side_effect=fake_flip), \
         patch("conductor.commands.dlq._connect_to_site"), \
         patch("conductor.commands.dlq._disconnect"):
        result = runner.invoke(
            dlq_group,
            ["retry", "--site", "frappe.localhost"],
            obj={"sites": ["frappe.localhost"], "profile": False},
        )
    assert result.exit_code == 0, result.output
    assert enqueued == [("conductor.demo.echo", "default", {})]
    # Tolerant payload assertion: status RETRIED, reviewed_by present, reviewed_at present.
    assert len(flipped) == 1
    assert flipped[0][0] == "DLQE-001"
    assert flipped[0][1] == "RETRIED"
    payload = flipped[0][2]
    assert payload["status"] == "RETRIED"
    assert "reviewed_by" in payload
    assert "reviewed_at" in payload


def test_dlq_retry_skips_non_pending_rows():
    from conductor.commands.dlq import dlq_group
    runner = CliRunner()
    enq_called = []
    with patch("conductor.commands.dlq._fetch_pending_rows", return_value=[]), \
         patch("conductor.commands.dlq._enqueue_from_dlq_row",
               side_effect=lambda *a, **k: enq_called.append(True) or "x"), \
         patch("conductor.commands.dlq._connect_to_site"), \
         patch("conductor.commands.dlq._disconnect"):
        result = runner.invoke(
            dlq_group,
            ["retry", "--site", "frappe.localhost"],
            obj={"sites": ["frappe.localhost"], "profile": False},
        )
    assert result.exit_code == 0
    assert enq_called == []


def test_dlq_discard_marks_row():
    from conductor.commands.dlq import dlq_group
    runner = CliRunner()
    rows = [{
        "name": "DLQE-001", "job": "job-A", "queue": "default",
        "method": "x", "status": "PENDING_REVIEW",
    }]
    flipped = []
    with patch("conductor.commands.dlq._fetch_pending_rows", return_value=rows), \
         patch("conductor.commands.dlq._mark_dlq_row",
               side_effect=lambda name, payload: flipped.append((name, payload["status"]))), \
         patch("conductor.commands.dlq._connect_to_site"), \
         patch("conductor.commands.dlq._disconnect"):
        result = runner.invoke(
            dlq_group,
            ["discard", "--site", "frappe.localhost"],
            obj={"sites": ["frappe.localhost"], "profile": False},
        )
    assert result.exit_code == 0
    assert flipped == [("DLQE-001", "DISCARDED")]


def test_dlq_list_inherits_site_from_bench_context():
    """Regression for M7 Finding 3: `bench --site X conductor dlq list` (no
    explicit `--site` after the subcommand) must succeed by inheriting the
    site from the bench Click context, mirroring `conductor depth`'s
    behavior. See docs/roadmap/v2-certification/cli.md Finding 1."""
    from conductor.commands.dlq import dlq_group
    runner = CliRunner()
    captured = {}

    def fake_connect(site):
        captured["site"] = site

    with patch("conductor.commands.dlq._fetch_dlq_rows", return_value=_fake_dlq_rows()), \
         patch("conductor.commands.dlq._connect_to_site", side_effect=fake_connect), \
         patch("conductor.commands.dlq._disconnect"):
        # No --site after the subcommand. The bench context provides it
        # via frappe.commands.pass_context, which reads ctx.obj["sites"][0].
        result = runner.invoke(
            dlq_group,
            ["list"],
            obj={"sites": ["frappe.localhost"], "profile": False},
        )
    assert result.exit_code == 0, result.output
    assert captured.get("site") == "frappe.localhost"


def test_dlq_list_explicit_site_overrides_context():
    """Explicit --site must win over the bench context's sites[0]. Pins
    the `or` semantics in `site = site or get_site(ctx)`."""
    from conductor.commands.dlq import dlq_group
    runner = CliRunner()
    captured = {}

    def fake_connect(site):
        captured["site"] = site

    with patch("conductor.commands.dlq._fetch_dlq_rows", return_value=_fake_dlq_rows()), \
         patch("conductor.commands.dlq._connect_to_site", side_effect=fake_connect), \
         patch("conductor.commands.dlq._disconnect"):
        result = runner.invoke(
            dlq_group,
            ["list", "--site", "explicit.site"],
            obj={"sites": ["context.site"], "profile": False},
        )
    assert result.exit_code == 0, result.output
    assert captured.get("site") == "explicit.site"
