"""Redis client factory. One pool per (process, redis_url)."""

from __future__ import annotations

import threading

import redis

_lock = threading.Lock()
_pools: dict[str, redis.ConnectionPool] = {}


def get_redis(redis_url: str) -> redis.Redis:
    """Return a Redis client backed by a process-global pool keyed by URL."""
    with _lock:
        pool = _pools.get(redis_url)
        if pool is None:
            pool = redis.ConnectionPool.from_url(redis_url, decode_responses=False)
            _pools[redis_url] = pool
    return redis.Redis(connection_pool=pool)
