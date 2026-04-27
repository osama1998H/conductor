"""Conductor stream message schema (frozen, version 1).

A stream message is a flat str→str dict (Redis Streams field values are
ASCII-safe strings). args/kwargs are msgpack-then-base64 encoded.

Phase 1 adds optional retry-policy + idempotency fields. Decoder treats
missing fields as empty/zero defaults — backward-compatible with Phase 0
messages still in queues during a rolling deploy. No schema_version bump.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from conductor.serialization import dumps, loads

SCHEMA_VERSION = 1

# Required only for the original Phase 0 set; Phase 1 fields are optional.
_REQUIRED_FIELDS = {
    "job_id",
    "site",
    "name",
    "queue",
    "args_b64",
    "kwargs_b64",
    "attempt",
    "max_attempts",
    "timeout_seconds",
    "enqueued_at",
    "schema_version",
}


@dataclass(frozen=True)
class JobMessage:
    job_id: str
    site: str
    method: str  # serialized as "name" in the stream
    queue: str
    kwargs: dict[str, Any] = field(default_factory=dict)
    args: list[Any] = field(default_factory=list)
    attempt: int = 1
    max_attempts: int = 1
    timeout_seconds: int = 300
    enqueued_at: datetime | None = None
    deadline: datetime | None = None
    trace_parent: str = ""
    idempotency_key: str = ""
    workflow_run_id: str = ""
    step_id: str = ""
    # Phase 1 retry-policy fields (all optional).
    backoff: str = ""
    base_delay_seconds: int = 0
    max_delay_seconds: int = 0
    jitter: str = ""
    retry_on_names: list[str] = field(default_factory=list)
    no_retry_on_names: list[str] = field(default_factory=list)

    def replace(self, **changes: Any) -> "JobMessage":
        return replace(self, **changes)


def _b64encode(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _b64decode(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def _iso(dt: datetime | None) -> str:
    return dt.isoformat() if dt is not None else ""


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s)


def encode(msg: JobMessage) -> dict[str, str]:
    return {
        "job_id": msg.job_id,
        "site": msg.site,
        "name": msg.method,
        "queue": msg.queue,
        "args_b64": _b64encode(dumps(msg.args)) if msg.args else "",
        "kwargs_b64": _b64encode(dumps(msg.kwargs)) if msg.kwargs else "",
        "attempt": str(msg.attempt),
        "max_attempts": str(msg.max_attempts),
        "timeout_seconds": str(msg.timeout_seconds),
        "enqueued_at": _iso(msg.enqueued_at),
        "deadline": _iso(msg.deadline),
        "trace_parent": msg.trace_parent or "",
        "idempotency_key": msg.idempotency_key or "",
        "workflow_run_id": msg.workflow_run_id or "",
        "step_id": msg.step_id or "",
        "backoff": msg.backoff or "",
        "base_delay_seconds": str(msg.base_delay_seconds or 0),
        "max_delay_seconds": str(msg.max_delay_seconds or 0),
        "jitter": msg.jitter or "",
        "retry_on_names": json.dumps(msg.retry_on_names or []),
        "no_retry_on_names": json.dumps(msg.no_retry_on_names or []),
        "schema_version": str(SCHEMA_VERSION),
    }


def decode(fields_dict: dict[str, str]) -> JobMessage:
    missing = _REQUIRED_FIELDS - fields_dict.keys()
    if missing:
        raise ValueError(f"missing required field(s): {sorted(missing)}")

    schema_version = int(fields_dict["schema_version"])
    if schema_version != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported schema_version: {schema_version} (this build supports {SCHEMA_VERSION})"
        )

    args = loads(_b64decode(fields_dict["args_b64"])) if fields_dict["args_b64"] else []
    kwargs = loads(_b64decode(fields_dict["kwargs_b64"])) if fields_dict["kwargs_b64"] else {}

    def _maybe_int(s: str) -> int:
        return int(s) if s else 0

    def _maybe_list(s: str) -> list:
        return json.loads(s) if s else []

    return JobMessage(
        job_id=fields_dict["job_id"],
        site=fields_dict["site"],
        method=fields_dict["name"],
        queue=fields_dict["queue"],
        args=args,
        kwargs=kwargs,
        attempt=int(fields_dict["attempt"]),
        max_attempts=int(fields_dict["max_attempts"]),
        timeout_seconds=int(fields_dict["timeout_seconds"]),
        enqueued_at=_parse_iso(fields_dict["enqueued_at"]),
        deadline=_parse_iso(fields_dict.get("deadline", "")),
        trace_parent=fields_dict.get("trace_parent", ""),
        idempotency_key=fields_dict.get("idempotency_key", ""),
        workflow_run_id=fields_dict.get("workflow_run_id", ""),
        step_id=fields_dict.get("step_id", ""),
        backoff=fields_dict.get("backoff", ""),
        base_delay_seconds=_maybe_int(fields_dict.get("base_delay_seconds", "")),
        max_delay_seconds=_maybe_int(fields_dict.get("max_delay_seconds", "")),
        jitter=fields_dict.get("jitter", ""),
        retry_on_names=_maybe_list(fields_dict.get("retry_on_names", "")),
        no_retry_on_names=_maybe_list(fields_dict.get("no_retry_on_names", "")),
    )
