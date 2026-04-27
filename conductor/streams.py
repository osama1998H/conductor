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
