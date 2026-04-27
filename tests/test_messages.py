"""Unit tests for conductor.messages — stream message encode/decode."""

from datetime import datetime, timezone

import pytest

from conductor.messages import (
    SCHEMA_VERSION,
    JobMessage,
    decode,
    encode,
)


def _sample_message(**overrides) -> JobMessage:
    base = JobMessage(
        job_id="11111111-1111-1111-1111-111111111111",
        site="frappe.localhost",
        method="conductor.demo.echo",
        queue="default",
        kwargs={"x": 1, "ts": datetime(2026, 4, 27, tzinfo=timezone.utc)},
        attempt=1,
        max_attempts=1,
        timeout_seconds=60,
        enqueued_at=datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc),
        deadline=None,
        trace_parent="",
        idempotency_key="",
        workflow_run_id="",
        step_id="",
    )
    return base.replace(**overrides) if overrides else base


def test_roundtrip_full_message():
    msg = _sample_message()
    encoded = encode(msg)
    decoded = decode(encoded)
    assert decoded == msg


def test_encoded_fields_are_str_to_str():
    encoded = encode(_sample_message())
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in encoded.items())


def test_schema_version_is_present():
    encoded = encode(_sample_message())
    assert encoded["schema_version"] == str(SCHEMA_VERSION)


def test_decode_unknown_schema_version_raises():
    encoded = encode(_sample_message())
    encoded["schema_version"] = "999"
    with pytest.raises(ValueError, match="unsupported schema_version"):
        decode(encoded)


def test_decode_missing_required_field_raises():
    encoded = encode(_sample_message())
    encoded.pop("job_id")
    with pytest.raises(ValueError, match="missing required field"):
        decode(encoded)


def test_optional_fields_default_to_empty_string_or_none():
    msg = _sample_message(idempotency_key="", workflow_run_id="", step_id="", deadline=None)
    encoded = encode(msg)
    assert encoded["idempotency_key"] == ""
    assert encoded["workflow_run_id"] == ""
    assert encoded["step_id"] == ""
    assert encoded["deadline"] == ""
    decoded = decode(encoded)
    assert decoded.idempotency_key == ""
    assert decoded.workflow_run_id == ""
    assert decoded.step_id == ""
    assert decoded.deadline is None
