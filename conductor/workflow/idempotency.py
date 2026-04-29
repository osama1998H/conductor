"""Workflow-run idempotency: SET NX EX on conductor:{site}:wfidem:{hash}.

Mirrors conductor.idempotency.acquire_idem_lock for jobs (TTL is the only
release; duplicate within TTL is the entire point of the lock).
"""

from __future__ import annotations

from typing import Optional

import redis as redis_mod

from conductor.workflow.keys import wfidem_key


def acquire_wfidem_lock(
    client: redis_mod.Redis,
    site: str,
    idempotency_key: str,
    run_id: str,
    *,
    ttl: int,
) -> Optional[str]:
    """Try to claim the idempotency slot. Returns:
      - None if newly acquired (or idempotency disabled by empty key)
      - existing run_id if a prior call holds the slot
    """
    if not idempotency_key:
        return None
    key = wfidem_key(site, idempotency_key)
    if client.set(key, run_id, nx=True, ex=ttl):
        return None
    existing = client.get(key)
    return existing.decode("utf-8") if isinstance(existing, bytes) else existing
