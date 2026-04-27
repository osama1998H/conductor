"""Unit tests for the sweeper loop — delegates to existing sweep_orphans()."""

from unittest.mock import MagicMock, patch

import pytest

from conductor.scheduler_loops import _sweeper_loop_iter


@patch("conductor.scheduler_loops.sweep_orphans")
def test_sweeper_iter_calls_sweep_orphans(mock_sweep):
    mock_sweep.return_value = 3
    redis_client = MagicMock()
    _sweeper_loop_iter(redis_client, "site1")
    mock_sweep.assert_called_once_with(redis_client, "site1")


@patch("conductor.scheduler_loops.sweep_orphans")
def test_sweeper_iter_propagates_exceptions(mock_sweep):
    mock_sweep.side_effect = RuntimeError("DB blew up")
    redis_client = MagicMock()
    with pytest.raises(RuntimeError):
        _sweeper_loop_iter(redis_client, "site1")
