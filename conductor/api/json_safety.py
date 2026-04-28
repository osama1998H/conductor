"""JSON-safety gate for DLQ edit-and-retry (spec §9.4).

Master §3 #17 chose msgpack over JSON because msgpack preserves types JSON
drops (datetime, Decimal, bytes). DLQ edit-and-retry exposes the payload to
operators as JSON; allowing edits on payloads containing non-JSON-native
types would silently coerce those types on save. This module gates such
payloads: they are read-only in the SPA and rejected server-side.
"""

from __future__ import annotations

from typing import Any

_SAFE_PRIMITIVE_TYPES = (str, int, float, bool, type(None))


def is_json_safe(value: Any) -> bool:
    if isinstance(value, _SAFE_PRIMITIVE_TYPES):
        return True
    if isinstance(value, list):
        return all(is_json_safe(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(k, str) and is_json_safe(v)
            for k, v in value.items()
        )
    return False
