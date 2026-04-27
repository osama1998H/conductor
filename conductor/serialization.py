"""Msgpack-based (de)serialization for Conductor stream payloads.

Frappe code commonly relies on Python types JSON drops (datetime, Decimal),
so we use msgpack with extension types for losslessness.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import msgpack

DEFAULT_MAX_BYTES = 1024 * 1024  # 1 MiB

_EXT_DATETIME = 1
_EXT_DECIMAL = 2


def _default(obj: Any) -> msgpack.ExtType:
    if isinstance(obj, datetime):
        if obj.tzinfo is None:
            obj = obj.replace(tzinfo=timezone.utc)
        return msgpack.ExtType(_EXT_DATETIME, obj.isoformat().encode("utf-8"))
    if isinstance(obj, Decimal):
        return msgpack.ExtType(_EXT_DECIMAL, str(obj).encode("utf-8"))
    raise TypeError(f"unserializable type: {type(obj).__name__}")


def _ext_hook(code: int, data: bytes) -> Any:
    if code == _EXT_DATETIME:
        return datetime.fromisoformat(data.decode("utf-8"))
    if code == _EXT_DECIMAL:
        return Decimal(data.decode("utf-8"))
    return msgpack.ExtType(code, data)


def dumps(obj: Any, *, max_bytes: int = DEFAULT_MAX_BYTES) -> bytes:
    """Pack `obj` to msgpack bytes; raise ValueError if it exceeds `max_bytes`."""
    out = msgpack.packb(obj, default=_default, use_bin_type=True)
    if len(out) > max_bytes:
        raise ValueError(f"payload too large: {len(out)} bytes > {max_bytes} bytes")
    return out


def loads(data: bytes) -> Any:
    return msgpack.unpackb(data, ext_hook=_ext_hook, raw=False)
