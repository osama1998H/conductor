"""Unit tests for pool worker stream-routing skeleton.

These tests do NOT spawn a real worker process; they exercise the helpers
that pool mode adds: building the streams dict across multiple sites,
parsing the right site from each stream key, and confirming the
single-site path is just N=1 of pool mode.
"""

from unittest.mock import patch

import pytest

from conductor.worker import _build_streams_dict


def test_build_streams_dict_one_site_one_queue(fake_redis):
    streams = _build_streams_dict(
        fake_redis, sites=["alpha.test"], queues=["default"],
    )
    assert streams == {"conductor:alpha.test:stream:default": ">"}


def test_build_streams_dict_one_site_multiple_queues(fake_redis):
    streams = _build_streams_dict(
        fake_redis, sites=["alpha.test"], queues=["default", "long"],
    )
    assert streams == {
        "conductor:alpha.test:stream:default": ">",
        "conductor:alpha.test:stream:long": ">",
    }


def test_build_streams_dict_multiple_sites_multiple_queues(fake_redis):
    streams = _build_streams_dict(
        fake_redis,
        sites=["alpha.test", "beta.test"],
        queues=["default", "critical"],
    )
    assert streams == {
        "conductor:alpha.test:stream:default": ">",
        "conductor:alpha.test:stream:critical": ">",
        "conductor:beta.test:stream:default": ">",
        "conductor:beta.test:stream:critical": ">",
    }


def test_build_streams_dict_creates_consumer_group_per_stream(fake_redis):
    """ensure_consumer_group is called for every (site, queue) combination."""
    with patch("conductor.worker.ensure_consumer_group") as mock_ensure:
        _build_streams_dict(
            fake_redis,
            sites=["alpha.test", "beta.test"],
            queues=["default"],
        )
    assert mock_ensure.call_count == 2
    seen_keys = sorted(call.args[1] for call in mock_ensure.call_args_list)
    assert seen_keys == [
        "conductor:alpha.test:stream:default",
        "conductor:beta.test:stream:default",
    ]


def test_register_worker_pool_inserts_one_row_per_site(monkeypatch):
    """The pool worker registers itself in every site it serves so that each
    site's Conductor Worker list (and reaper) sees it."""
    from types import SimpleNamespace

    seen_inserts: list[dict] = []

    import frappe
    monkeypatch.setattr(frappe, "init", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(frappe, "connect", lambda: None, raising=False)
    monkeypatch.setattr(frappe, "destroy", lambda: None, raising=False)

    # frappe.db is a werkzeug LocalProxy; outside a real site it's unbound.
    # Replace the whole attribute with a plain stub so attribute access works.
    stub_db = SimpleNamespace(
        exists=lambda *a, **k: False,
        commit=lambda: None,
    )
    monkeypatch.setattr(frappe, "db", stub_db, raising=False)

    class _DocStub:
        def __init__(self, payload):
            self._payload = payload
        def insert(self, **_):
            return self
    def capturing_get_doc(payload, *a, **k):
        if isinstance(payload, dict) and payload.get("doctype") == "Conductor Worker":
            seen_inserts.append(payload)
            return _DocStub(payload)
        raise AssertionError(f"unexpected get_doc payload: {payload!r}")
    monkeypatch.setattr(frappe, "get_doc", capturing_get_doc, raising=False)

    from conductor.worker import _register_worker_pool
    _register_worker_pool(
        "host:1234:abc",
        queues=["default"],
        sites=["alpha.test", "beta.test"],
        sites_path="/tmp/sites",
        primary_site="alpha.test",
    )
    assert len(seen_inserts) == 2
    sites_seen = {row["site"] for row in seen_inserts}
    assert sites_seen == {"alpha.test", "beta.test"}
    assert all(row["worker_id"] == "host:1234:abc" for row in seen_inserts)


def test_heartbeat_pool_updates_every_site(monkeypatch):
    """_heartbeat_pool should fanout one set_value per site, all with the
    same worker_id."""
    from types import SimpleNamespace

    seen_calls: list[tuple[str | None, str, dict]] = []
    current_site_holder: dict = {"v": None}

    import frappe
    def fake_init(*, site, **_):
        current_site_holder["v"] = site
    monkeypatch.setattr(frappe, "init", fake_init, raising=False)
    monkeypatch.setattr(frappe, "connect", lambda: None, raising=False)
    monkeypatch.setattr(frappe, "destroy", lambda: None, raising=False)

    def fake_set_value(doctype, name, payload, update_modified=False):
        seen_calls.append((current_site_holder["v"], name, dict(payload)))
    stub_db = SimpleNamespace(commit=lambda: None, set_value=fake_set_value)
    monkeypatch.setattr(frappe, "db", stub_db, raising=False)

    from conductor.worker import _heartbeat_pool
    _heartbeat_pool(
        "host:1234:abc",
        sites=["alpha.test", "beta.test", "gamma.test"],
        sites_path="/tmp/sites",
        primary_site="alpha.test",
    )

    # Three set_value calls (one per site)
    assert len(seen_calls) == 3
    by_site = {c[0] for c in seen_calls}
    assert by_site == {"alpha.test", "beta.test", "gamma.test"}
    # All addressed to same worker_id, all status=ALIVE
    for site, name, payload in seen_calls:
        assert name == "host:1234:abc"
        assert payload["status"] == "ALIVE"
        assert "last_heartbeat" in payload


def test_resolve_queue_limits_returns_zero_for_unlimited(monkeypatch):
    """A Conductor Queue with max_rps=0 and max_concurrent=0 must short-circuit
    the throttle gate — no Redis calls should fire."""
    class FakeQueue:
        max_rps = 0
        max_concurrent = 0

    import frappe
    monkeypatch.setattr(frappe, "get_cached_doc",
                        lambda doctype, name: FakeQueue(), raising=False)

    from conductor.worker import _resolve_queue_limits
    rps, conc = _resolve_queue_limits("default")
    assert rps == 0
    assert conc == 0


def test_resolve_queue_limits_reads_int_fields(monkeypatch):
    class FakeQueue:
        max_rps = 25
        max_concurrent = 7
    import frappe
    monkeypatch.setattr(frappe, "get_cached_doc",
                        lambda doctype, name: FakeQueue(), raising=False)
    from conductor.worker import _resolve_queue_limits
    rps, conc = _resolve_queue_limits("default")
    assert rps == 25
    assert conc == 7


def test_throttle_gate_inflight_denied_reschedules_without_consuming_token(monkeypatch, fake_redis):
    """When max_concurrent is exceeded, the throttle gate must re-ZADD to
    the delay set and NOT call take_token — token is preserved for callers
    that actually run."""
    from types import SimpleNamespace

    take_token_called = []

    def spy_take_token(*a, **k):
        take_token_called.append(True)
        return (True, 0)
    monkeypatch.setattr("conductor.worker.take_token", spy_take_token, raising=False)

    # Pre-fill inflight at cap
    from conductor.inflight import acquire
    for _ in range(2):
        acquire(fake_redis, "alpha.test", "default", max_concurrent=2)

    schedule_calls = []
    def spy_schedule_message(client, site, encoded, run_at_ms):
        schedule_calls.append((site, run_at_ms, dict(encoded)))
    monkeypatch.setattr("conductor.worker.schedule_message",
                        spy_schedule_message, raising=False)

    db_calls = []
    import frappe
    stub_db = SimpleNamespace(
        set_value=lambda *a, **k: db_calls.append((a, k)),
        commit=lambda: None,
    )
    monkeypatch.setattr(frappe, "db", stub_db, raising=False)
    monkeypatch.setattr("conductor.worker.emit_job_event",
                        lambda *a, **k: None, raising=False)

    from conductor.messages import JobMessage
    from datetime import datetime, timezone
    msg = JobMessage(
        job_id="job-A", site="alpha.test", method="m", queue="default",
        args=[], kwargs={}, attempt=1, max_attempts=3, timeout_seconds=60,
        enqueued_at=datetime.now(timezone.utc),
        deadline=datetime.now(timezone.utc),
    )

    from conductor.worker import _apply_throttle_gate
    allowed = _apply_throttle_gate(
        fake_redis, msg, site="alpha.test",
        rps=10, conc=2, now_ms=1_700_000_000_000,
    )
    assert allowed is False
    assert take_token_called == []  # rate limit NOT consulted
    assert len(schedule_calls) == 1
    site, _run_at_ms, encoded = schedule_calls[0]
    assert site == "alpha.test"
    # attempt unchanged (throttling, not retry)
    assert encoded.get("attempt") == "1"


def test_throttle_gate_rate_limit_denied_releases_inflight_and_reschedules(monkeypatch, fake_redis):
    """Inflight acquired, then rate-limit rejects — the inflight slot must
    be released so we don't leak it."""
    from types import SimpleNamespace

    monkeypatch.setattr("conductor.worker.take_token",
                        lambda *a, **k: (False, 250), raising=False)
    monkeypatch.setattr("conductor.worker.schedule_message",
                        lambda *a, **k: None, raising=False)
    import frappe
    stub_db = SimpleNamespace(
        set_value=lambda *a, **k: None,
        commit=lambda: None,
    )
    monkeypatch.setattr(frappe, "db", stub_db, raising=False)
    monkeypatch.setattr("conductor.worker.emit_job_event",
                        lambda *a, **k: None, raising=False)

    from conductor.inflight import get_count
    from conductor.messages import JobMessage
    from datetime import datetime, timezone
    msg = JobMessage(
        job_id="job-A", site="s", method="m", queue="default",
        args=[], kwargs={}, attempt=1, max_attempts=3, timeout_seconds=60,
        enqueued_at=datetime.now(timezone.utc),
        deadline=datetime.now(timezone.utc),
    )

    from conductor.worker import _apply_throttle_gate
    allowed = _apply_throttle_gate(
        fake_redis, msg, site="s",
        rps=10, conc=5, now_ms=1_700_000_000_000,
    )
    assert allowed is False
    # Inflight was acquired (1) then released (back to 0)
    assert get_count(fake_redis, "s", "default") == 0


def test_throttle_gate_both_pass_returns_true_and_holds_inflight_slot(monkeypatch, fake_redis):
    monkeypatch.setattr("conductor.worker.take_token",
                        lambda *a, **k: (True, 0), raising=False)
    from conductor.messages import JobMessage
    from datetime import datetime, timezone
    msg = JobMessage(
        job_id="job-A", site="s", method="m", queue="default",
        args=[], kwargs={}, attempt=1, max_attempts=3, timeout_seconds=60,
        enqueued_at=datetime.now(timezone.utc),
        deadline=datetime.now(timezone.utc),
    )
    from conductor.worker import _apply_throttle_gate
    from conductor.inflight import get_count
    allowed = _apply_throttle_gate(
        fake_redis, msg, site="s",
        rps=10, conc=3, now_ms=1_700_000_000_000,
    )
    assert allowed is True
    assert get_count(fake_redis, "s", "default") == 1


def test_throttle_gate_short_circuits_when_both_limits_zero(monkeypatch, fake_redis):
    """When max_rps=0 and max_concurrent=0, no Redis calls should fire."""
    take_token_called = []
    monkeypatch.setattr("conductor.worker.take_token",
                        lambda *a, **k: take_token_called.append(True) or (True, 0),
                        raising=False)
    from conductor.messages import JobMessage
    from datetime import datetime, timezone
    msg = JobMessage(
        job_id="job-A", site="s", method="m", queue="default",
        args=[], kwargs={}, attempt=1, max_attempts=3, timeout_seconds=60,
        enqueued_at=datetime.now(timezone.utc),
        deadline=datetime.now(timezone.utc),
    )
    from conductor.worker import _apply_throttle_gate
    allowed = _apply_throttle_gate(
        fake_redis, msg, site="s",
        rps=0, conc=0, now_ms=1_700_000_000_000,
    )
    assert allowed is True
    assert take_token_called == []


def test_pool_cancel_pollers_one_per_site_share_event_map():
    """Pool mode runs N CancelPoller threads, all writing into the same
    process-global cancel_events map. Construction is what we test here;
    the live polling is verified by the chaos suite."""
    from conductor.worker import _make_pool_cancel_pollers, _cancel_events, _cancel_events_lock
    pollers = _make_pool_cancel_pollers(
        worker_id="host:1234:abc",
        sites=["alpha.test", "beta.test", "gamma.test"],
        sites_path="/tmp/sites",
    )
    try:
        assert len(pollers) == 3
        # Same shared map and lock referenced by every poller
        for p in pollers:
            assert p._cancel_events is _cancel_events
            assert p._lock is _cancel_events_lock
        # Sites all distinct
        seen_sites = {p._site for p in pollers}
        assert seen_sites == {"alpha.test", "beta.test", "gamma.test"}
    finally:
        # Don't actually start them in the test -- the start() side-effect
        # would try to talk to Frappe on those non-existent sites.
        pass
