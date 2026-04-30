"""ZSET-backed scheduled-message store.

A retry/scheduled-dispatch ZADDs the encoded JobMessage (as a JSON string)
with score = run_at_unix_ms. The scheduler process polls ZRANGEBYSCORE,
pops due items, and XADDs them to their target stream.
"""

from __future__ import annotations

import json
import time

import redis as redis_mod

from conductor.logging import get_logger

log = get_logger("conductor.scheduled")


def scheduled_redis_key(site: str) -> str:
    return f"conductor:{site}:scheduled"


def schedule_message(
    client: redis_mod.Redis,
    site: str,
    encoded_message: dict[str, str],
    run_at_ms: int,
) -> None:
    """ZADD the encoded message (as JSON string) with score = run_at_ms."""
    member = json.dumps(encoded_message)
    client.zadd(scheduled_redis_key(site), {member: run_at_ms})


def drain_due_messages(
    client: redis_mod.Redis,
    site: str,
    *,
    now_ms: int | None = None,
    batch: int = 100,
) -> list[dict[str, str]]:
    """Return all due messages and remove them from the ZSET. Atomicity is per-member."""
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    skey = scheduled_redis_key(site)
    members = client.zrangebyscore(skey, "-inf", now_ms, start=0, num=batch)
    out: list[dict[str, str]] = []
    for member in members:
        # ZREM ensures we don't double-process — concurrent scheduler loops
        # lose the race idempotently.
        if client.zrem(skey, member):
            try:
                out.append(json.loads(member.decode("utf-8") if isinstance(member, bytes) else member))
            except Exception as e:
                log.error("scheduled_decode_failed", error=str(e))
    return out
