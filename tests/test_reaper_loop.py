"""Unit tests for the reaper loop — STALE/GONE transitions + 7d prune.

After Phase 6, `_reaper_loop_iter` first SELECTs the workers about to flip GONE
(so the caller can drift-correct inflight counters), then runs the same three
mutations (GONE update, STALE update, 7d prune)."""

from datetime import datetime
from unittest.mock import MagicMock

from conductor.scheduler_loops import _reaper_loop_iter


def _frappe_with_no_gone_workers():
    """MagicMock frappe whose SELECT returns no rows."""
    frappe = MagicMock()
    frappe.db.sql.return_value = []
    return frappe


def test_reaper_runs_select_then_three_mutations_in_order():
    frappe = _frappe_with_no_gone_workers()
    _reaper_loop_iter("site1", frappe)
    # Expect four sql calls: SELECT (capture just-GONE ids), UPDATE GONE,
    # UPDATE STALE, DELETE — in that order.
    assert frappe.db.sql.call_count == 4
    sql_verbs = [c.args[0].strip().split()[0].upper() for c in frappe.db.sql.call_args_list]
    assert sql_verbs == ["SELECT", "UPDATE", "UPDATE", "DELETE"]


def test_reaper_returns_just_gone_worker_ids():
    frappe = MagicMock()
    frappe.db.sql.return_value = [{"worker_id": "host:1:abc"}, {"worker_id": "host:2:def"}]
    just_gone = _reaper_loop_iter("site1", frappe)
    assert just_gone == ["host:1:abc", "host:2:def"]


def test_reaper_passes_correct_thresholds():
    frappe = _frappe_with_no_gone_workers()
    _reaper_loop_iter("site1", frappe)
    # Inspect the parameters of each call: (site, cutoff[, …]).
    params = [c.args[1] for c in frappe.db.sql.call_args_list]
    for p in params:
        assert p[0] == "site1"
    select_gone_cut = params[0][1]
    update_gone_cut = params[1][1]
    update_stale_cut = params[2][1]
    prune_cut = params[3][1]
    # SELECT and UPDATE GONE share the same gone_cut — same cutoff, same pass.
    assert select_gone_cut == update_gone_cut
    now = datetime.now()
    assert (now - update_gone_cut).total_seconds() >= 119
    assert (now - update_stale_cut).total_seconds() >= 29
    assert (now - prune_cut).total_seconds() >= 7 * 24 * 3600 - 1
