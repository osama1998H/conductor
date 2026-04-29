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
