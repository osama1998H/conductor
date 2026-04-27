"""Unit tests for conductor.serialization."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from conductor.serialization import dumps, loads


def test_roundtrip_basic_types():
    payload = {"a": 1, "b": "hello", "c": [1, 2, 3], "d": None, "e": True}
    assert loads(dumps(payload)) == payload


def test_roundtrip_datetime_aware():
    dt = datetime(2026, 4, 27, 15, 30, 0, tzinfo=timezone.utc)
    out = loads(dumps({"when": dt}))
    assert out["when"] == dt
    assert out["when"].tzinfo is not None


def test_roundtrip_datetime_naive_becomes_utc():
    naive = datetime(2026, 1, 1, 12, 0, 0)  # no tzinfo
    out = loads(dumps({"dt": naive}))
    assert out["dt"] == naive.replace(tzinfo=timezone.utc)
    assert out["dt"].tzinfo == timezone.utc


def test_roundtrip_decimal():
    out = loads(dumps({"amount": Decimal("123.45")}))
    assert out["amount"] == Decimal("123.45")
    assert isinstance(out["amount"], Decimal)


def test_oversize_payload_raises():
    too_big = {"data": "x" * (2 * 1024 * 1024)}  # 2 MiB > our 1 MiB cap
    with pytest.raises(ValueError, match="payload too large"):
        dumps(too_big, max_bytes=1024 * 1024)


def test_default_size_limit_is_1mib():
    near_limit = {"data": "x" * (900 * 1024)}
    dumps(near_limit)  # must not raise

    over_limit = {"data": "x" * (1100 * 1024)}
    with pytest.raises(ValueError):
        dumps(over_limit)
