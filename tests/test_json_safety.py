"""Unit tests for is_json_safe — the gate for DLQ edit-and-retry."""

from datetime import datetime, timezone
from decimal import Decimal

from conductor.api.json_safety import is_json_safe


def test_plain_str_int_dict_is_safe():
    assert is_json_safe({"a": 1, "b": "x", "c": True, "d": None}) is True
    assert is_json_safe([1, 2, 3]) is True
    assert is_json_safe("hello") is True


def test_nested_str_int_dict_is_safe():
    assert is_json_safe({"a": [1, {"b": "x"}]}) is True


def test_datetime_is_unsafe():
    assert is_json_safe({"ts": datetime(2026, 4, 28, tzinfo=timezone.utc)}) is False


def test_decimal_is_unsafe():
    assert is_json_safe({"amount": Decimal("1.23")}) is False


def test_bytes_is_unsafe():
    assert is_json_safe({"blob": b"abc"}) is False


def test_unsafe_inside_nested_list_is_detected():
    assert is_json_safe({"a": [{"ts": datetime.now()}]}) is False


def test_custom_class_is_unsafe():
    class Foo:
        pass
    assert is_json_safe({"x": Foo()}) is False


def test_float_is_safe():
    assert is_json_safe({"x": 1.5}) is True
