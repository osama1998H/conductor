"""Tests for cli_runner._evaluate.

The full run_all() invokes subprocess against a live bench and is exercised in
M3 / Task 13. _evaluate is pure logic and worth pinning here.
"""
from __future__ import annotations

from tests.v2_certification.cli_runner import _evaluate


def test_evaluate_pass_when_exit_and_stdout_match():
    observed = {"exit": 0, "stdout": "OK something", "stderr": ""}
    expected = {"exit": 0, "stdout_contains": ["OK"]}
    ok, why = _evaluate(observed, expected)
    assert ok is True
    assert why == ""


def test_evaluate_fail_on_exit_mismatch():
    observed = {"exit": 1, "stdout": "OK", "stderr": ""}
    expected = {"exit": 0}
    ok, why = _evaluate(observed, expected)
    assert ok is False
    assert "exit" in why and "1" in why


def test_evaluate_fail_on_missing_stdout_fragment():
    observed = {"exit": 0, "stdout": "running", "stderr": ""}
    expected = {"exit": 0, "stdout_contains": ["finished"]}
    ok, why = _evaluate(observed, expected)
    assert ok is False
    assert "stdout missing" in why


def test_evaluate_fail_on_missing_stderr_fragment():
    observed = {"exit": 0, "stdout": "", "stderr": "info: something"}
    expected = {"exit": 0, "stderr_contains": ["error"]}
    ok, why = _evaluate(observed, expected)
    assert ok is False
    assert "stderr missing" in why


def test_evaluate_case_insensitive_match():
    observed = {"exit": 0, "stdout": "ok", "stderr": ""}
    expected = {"exit": 0, "stdout_contains": ["OK"]}
    ok, why = _evaluate(observed, expected)
    assert ok is True
