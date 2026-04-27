"""ZSET-backed scheduled-message store + the in-worker delay drainer.

A retry/scheduled-dispatch ZADDs the encoded JobMessage (as a JSON string)
with score = run_at_unix_ms. The drainer thread polls ZRANGEBYSCORE every 1s,
pops due items, and XADDs them to their target stream. Phase 2's scheduler
process subsumes this thread; the contract here is forward-compatible.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Iterable

import redis as redis_mod

from conductor.logging import get_logger
from conductor.streams import ensure_consumer_group, stream_key

log = get_logger("conductor.scheduled")

DRAIN_INTERVAL_SECONDS = 1.0


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
    """Return all due messages and remove them from the ZSET. Atomicity is per-member.

    Used both by the in-worker drainer thread and by tests.
    """
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    skey = scheduled_redis_key(site)
    members = client.zrangebyscore(skey, "-inf", now_ms, start=0, num=batch)
    out: list[dict[str, str]] = []
    for member in members:
        # ZREM ensures we don't double-process — concurrent drainers (Phase 2 scheduler
        # vs the in-worker thread during the transition) lose the race idempotently.
        if client.zrem(skey, member):
            try:
                out.append(json.loads(member.decode("utf-8") if isinstance(member, bytes) else member))
            except Exception as e:
                log.error("scheduled_decode_failed", error=str(e))
    return out


class DelayDrainer:
    """Thread that drains due messages and XADDs them to their target streams."""

    def __init__(self, client: redis_mod.Redis, site: str):
        self._client = client
        self._site = site
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="conductor-drainer")

    def start(self) -> None:
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        self._thread.join(timeout=timeout)

    def _run(self) -> None:
        log.info("drainer_started", site=self._site)
        while not self._stop.is_set():
            try:
                due = drain_due_messages(self._client, self._site)
                for encoded in due:
                    queue = encoded.get("queue") or ""
                    if not queue:
                        log.warning("drainer_skipped_empty_queue", encoded=encoded)
                        continue
                    target = stream_key(self._site, queue)
                    ensure_consumer_group(self._client, target)
                    self._client.xadd(target, encoded, maxlen=10000, approximate=True)
            except Exception as e:
                log.error("drainer_iteration_failed", error=str(e))
            self._stop.wait(DRAIN_INTERVAL_SECONDS)
        log.info("drainer_stopped", site=self._site)
