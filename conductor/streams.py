"""Redis Streams helpers for Conductor: key namespacing and consumer-group setup."""

from __future__ import annotations

import redis as redis_mod

CONSUMER_GROUP = "conductor"


def stream_key(site: str, queue: str) -> str:
    return f"conductor:{site}:stream:{queue}"


def dlq_key(site: str, queue: str) -> str:
    return f"conductor:{site}:dlq:{queue}"


def scheduled_key(site: str) -> str:
    return f"conductor:{site}:scheduled"


def workers_key(site: str) -> str:
    return f"conductor:{site}:workers"


def parse_site_from_stream_key(stream: str) -> str:
    """Inverse of stream_key — extract site name from `conductor:{site}:stream:{queue}`.

    Pool worker mode reads multiple streams and must route each message to
    the correct site context. We trust the **stream key** (operator-controlled
    Redis key namespace), never the message fields (caller-controlled, possibly
    forged), to decide which site's MariaDB to connect to.

    Raises:
        TypeError: if `stream` is not a str.
        ValueError: if `stream` does not match `conductor:<site>:stream:<queue>`.
    """
    if not isinstance(stream, str):
        raise TypeError(f"stream key must be str, got {type(stream).__name__}")
    marker = ":stream:"
    if not stream.startswith("conductor:") or marker not in stream:
        raise ValueError(f"not a conductor stream key: {stream!r}")
    # Slice between "conductor:" and ":stream:".
    head = stream[len("conductor:"):]
    idx = head.find(marker)
    if idx <= 0:
        raise ValueError(f"not a conductor stream key: {stream!r}")
    return head[:idx]


def ensure_consumer_group(client: redis_mod.Redis, stream: str) -> None:
    """Create the conductor consumer group on `stream`, idempotently.

    Uses XGROUP CREATE … MKSTREAM so the stream is created on first call.
    Swallows BUSYGROUP (group already exists) only; re-raises everything else.
    """
    try:
        client.xgroup_create(name=stream, groupname=CONSUMER_GROUP, id="0", mkstream=True)
    except redis_mod.exceptions.ResponseError as e:
        if "BUSYGROUP" in str(e):
            return
        raise
