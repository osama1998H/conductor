"""Dispatch idempotency: SET NX EX on a SHA-256-hashed key.

If a caller dispatches twice with the same logical key within the TTL, the
second call gets back the first call's job_id and does NOT enqueue.

The lock is NOT released on terminal status — TTL is the only release. A
duplicate dispatch within the TTL is the entire point of having the lock.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Optional

import redis as redis_mod


def idem_redis_key(site: str, idempotency_key: str) -> str:
    h = sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"conductor:{site}:idem:{h}"


def acquire_idem_lock(
    client: redis_mod.Redis,
    site: str,
    idempotency_key: str,
    job_id: str,
    *,
    ttl: int,
) -> Optional[str]:
    """Try to claim the idempotency slot for `idempotency_key`.

    Returns:
      - None if the lock was newly acquired (caller should proceed with dispatch).
      - The existing job_id (str) if a prior dispatch holds the lock.
      - None if `idempotency_key` is empty (idempotency disabled for this dispatch).
    """
    if not idempotency_key:
        return None
    key = idem_redis_key(site, idempotency_key)
    if client.set(key, job_id, nx=True, ex=ttl):
        return None
    existing = client.get(key)
    return existing.decode("utf-8") if isinstance(existing, bytes) else existing
