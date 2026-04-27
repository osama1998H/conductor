"""Unit tests for the reaper loop — STALE/GONE transitions + 7d prune."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from conductor.scheduler_loops import _reaper_loop_iter


def test_reaper_runs_three_sql_updates_in_order():
    frappe = MagicMock()
    site = "site1"
    _reaper_loop_iter(site, frappe)
    # Expect three sql calls: GONE, STALE, DELETE — in that order.
    assert frappe.db.sql.call_count == 3
    sql_texts = [c.args[0].strip().split()[0].upper() for c in frappe.db.sql.call_args_list]
    assert sql_texts == ["UPDATE", "UPDATE", "DELETE"]


def test_reaper_passes_correct_thresholds():
    frappe = MagicMock()
    _reaper_loop_iter("site1", frappe)
    # Inspect the parameters of each call.
    params = [c.args[1] for c in frappe.db.sql.call_args_list]
    # Each call's params is (site, cutoff[, …]).
    for p in params:
        assert p[0] == "site1"
    # GONE cutoff (≥ 120 s ago), STALE cutoff (≥ 30 s ago, < 120 s).
    gone_cut = params[0][1]
    stale_cut = params[1][1]
    prune_cut = params[2][1]
    now = datetime.now()
    assert (now - gone_cut).total_seconds() >= 119
    assert (now - stale_cut).total_seconds() >= 29
    assert (now - prune_cut).total_seconds() >= 7 * 24 * 3600 - 1
