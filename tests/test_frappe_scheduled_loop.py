"""Unit tests for conductor.frappe_scheduled_loop.

These run without a live bench — frappe is patched into in-memory mocks.
The loop's correctness is verified at the orchestration level. End-to-end
behavior (real bench, real `Scheduled Job Type` rows, real conductor
worker picking up the dispatch) is exercised in M2 of the v2 campaign.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from conductor import frappe_scheduled_loop as fsl


def _make_due_doc(name: str, method: str, frequency: str = "Daily") -> MagicMock:
    """Build a fake Scheduled Job Type doc that is_event_due() reports as due."""
    doc = MagicMock()
    doc.name = name
    doc.method = method
    doc.frequency = frequency
    doc.is_event_due = MagicMock(return_value=True)
    return doc


def _make_not_due_doc(name: str, method: str, frequency: str = "Daily") -> MagicMock:
    doc = MagicMock()
    doc.name = name
    doc.method = method
    doc.frequency = frequency
    doc.is_event_due = MagicMock(return_value=False)
    return doc


def test_loop_iter_is_noop_when_takeover_flag_unset():
    """Loop exits immediately on every tick when flag is False."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {}

    fired = fsl._frappe_scheduled_loop_iter(fake_frappe)

    assert fired == 0
    fake_frappe.get_all.assert_not_called()


def test_loop_iter_dispatches_due_row():
    """Flag set + one due row → conductor_enqueue called once with mapped queue."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {fsl.ACTIVATION_FLAG: True}
    fake_frappe.get_all.return_value = [{"name": "x.run"}]
    doc = _make_due_doc("x.run", "x.method.run", "Daily")
    fake_frappe.get_doc.return_value = doc

    with patch.object(fsl, "conductor_enqueue", return_value="cnd-1") as cnd:
        fired = fsl._frappe_scheduled_loop_iter(fake_frappe)

    assert fired == 1
    cnd.assert_called_once_with("x.method.run", queue="long", max_attempts=1)
    doc.db_set.assert_called_once()
    assert doc.db_set.call_args[0][0] == "last_execution"


def test_loop_iter_skips_not_due_row():
    """Not-due row → no dispatch, no last_execution mutation."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {fsl.ACTIVATION_FLAG: True}
    fake_frappe.get_all.return_value = [{"name": "x.run"}]
    doc = _make_not_due_doc("x.run", "x.method.run")
    fake_frappe.get_doc.return_value = doc

    with patch.object(fsl, "conductor_enqueue") as cnd:
        fired = fsl._frappe_scheduled_loop_iter(fake_frappe)

    assert fired == 0
    cnd.assert_not_called()
    doc.db_set.assert_not_called()


def test_loop_iter_handles_mixed_frequencies_with_correct_queue_map():
    """Three due rows with different frequencies map to expected queues."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {fsl.ACTIVATION_FLAG: True}
    fake_frappe.get_all.return_value = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
    doc_a = _make_due_doc("a", "m.a", "Hourly")
    doc_b = _make_due_doc("b", "m.b", "Daily")
    doc_c = _make_due_doc("c", "m.c", "Weekly Long")
    fake_frappe.get_doc.side_effect = [doc_a, doc_a, doc_b, doc_b, doc_c, doc_c]

    with patch.object(fsl, "conductor_enqueue", return_value="cnd") as cnd:
        fired = fsl._frappe_scheduled_loop_iter(fake_frappe)

    assert fired == 3
    queues_called = [call.kwargs["queue"] for call in cnd.call_args_list]
    assert queues_called == ["default", "long", "long"]


def test_loop_iter_does_not_set_last_execution_on_dispatch_failure():
    """If conductor_enqueue raises, last_execution stays unchanged so we retry next tick."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {fsl.ACTIVATION_FLAG: True}
    fake_frappe.get_all.return_value = [{"name": "x.run"}]
    doc = _make_due_doc("x.run", "x.method.run", "Daily")
    fake_frappe.get_doc.return_value = doc

    with patch.object(fsl, "conductor_enqueue", side_effect=RuntimeError("redis down")):
        fired = fsl._frappe_scheduled_loop_iter(fake_frappe)

    assert fired == 1  # we counted it as fired (attempted) — see note in test below
    doc.db_set.assert_not_called()


def test_loop_iter_isolates_per_row_failures():
    """A failure on one row does not stop the loop from processing others."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {fsl.ACTIVATION_FLAG: True}
    fake_frappe.get_all.return_value = [{"name": "a"}, {"name": "b"}]
    doc_a = _make_due_doc("a", "m.a")
    doc_b = _make_due_doc("b", "m.b")
    # First get_doc call succeeds (in iter), second raises.
    # The loop calls get_doc twice per row (once for is_event_due, once in _fire_one).
    fake_frappe.get_doc.side_effect = [doc_a, doc_a, RuntimeError("doc gone")]

    with patch.object(fsl, "conductor_enqueue", return_value="cnd"):
        fired = fsl._frappe_scheduled_loop_iter(fake_frappe)

    # Row a fired successfully; row b raised before is_event_due was reached.
    assert fired == 1


def test_loop_iter_filters_stopped_rows_at_query_level():
    """get_all is called with the stopped=0 filter — stopped rows never reach the loop body."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {fsl.ACTIVATION_FLAG: True}
    fake_frappe.get_all.return_value = []

    fsl._frappe_scheduled_loop_iter(fake_frappe)

    fake_frappe.get_all.assert_called_once_with(
        "Scheduled Job Type",
        fields=["name"],
        filters={"stopped": 0},
        order_by="method",
    )


def test_resolve_queue_uses_default_map_when_no_override():
    assert fsl._resolve_queue("Daily", None) == "long"
    assert fsl._resolve_queue("Hourly", None) == "default"
    assert fsl._resolve_queue("Cron", None) == "default"


def test_resolve_queue_unknown_frequency_falls_back_to_default():
    assert fsl._resolve_queue("Yearly Sometime", None) == "default"


def test_resolve_queue_site_config_override_wins():
    override = {"Daily": "critical"}
    assert fsl._resolve_queue("Daily", override) == "critical"
    # Non-overridden keys still come from the default map.
    assert fsl._resolve_queue("Hourly", override) == "default"


def test_is_takeover_enabled_reads_conf_at_call_time():
    fake_frappe = MagicMock()
    fake_frappe.conf = {fsl.ACTIVATION_FLAG: True}
    assert fsl._is_takeover_enabled(fake_frappe) is True

    fake_frappe.conf = {fsl.ACTIVATION_FLAG: False}
    assert fsl._is_takeover_enabled(fake_frappe) is False

    fake_frappe.conf = {}
    assert fsl._is_takeover_enabled(fake_frappe) is False


def test_is_takeover_enabled_returns_false_when_conf_access_raises():
    fake_frappe = MagicMock()
    type(fake_frappe).conf = property(
        lambda self: (_ for _ in ()).throw(RuntimeError("conf gone"))
    )
    assert fsl._is_takeover_enabled(fake_frappe) is False
