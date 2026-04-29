"""Rate-limit token bucket — Lua-backed, single-key, cluster-safe.

The Lua script is loaded once per Redis connection-pool via SCRIPT LOAD
(redis-py's `register_script`); subsequent calls are EVALSHA. The wrapper
keeps the call site simple: pass site, queue, and bucket parameters; get
back `(allowed, retry_after_ms)`.

Time is provided as `now_ms` explicitly (rather than reading from Redis's
TIME) so unit tests can drive the clock deterministically. Production
callers pass `int(time.time() * 1000)`.
"""

from __future__ import annotations

import threading
from pathlib import Path

import redis as redis_mod

_SCRIPT_PATH = Path(__file__).with_name("rate_limit.lua")
_LUA_SOURCE: str | None = None
_LUA_LOCK = threading.Lock()
# Per-Redis-client `Script` cache — re-using the same registered Script object
# across calls means redis-py reuses its SHA1 and only EVALSHAs.
_REGISTERED: dict[int, "redis_mod.client.Script"] = {}


def rate_key(site: str, queue: str) -> str:
    return f"conductor:{site}:rate:{queue}"


def _get_script(client: redis_mod.Redis) -> "redis_mod.client.Script":
    global _LUA_SOURCE
    if _LUA_SOURCE is None:
        with _LUA_LOCK:
            if _LUA_SOURCE is None:
                _LUA_SOURCE = _SCRIPT_PATH.read_text(encoding="utf-8")
    cid = id(client.connection_pool)
    script = _REGISTERED.get(cid)
    if script is None:
        script = client.register_script(_LUA_SOURCE)
        _REGISTERED[cid] = script
    return script


def take_token(
    client: redis_mod.Redis,
    site: str,
    queue: str,
    *,
    max_tokens: int,
    refill_per_sec: float,
    now_ms: int,
    n: int = 1,
) -> tuple[bool, int]:
    """Try to consume `n` tokens. Returns (allowed, retry_after_ms).
    If allowed is False, retry_after_ms is the minimum wait before this
    many tokens will be available."""
    script = _get_script(client)
    out = script(
        keys=[rate_key(site, queue)],
        args=[max_tokens, refill_per_sec, now_ms, n],
    )
    # redis-py returns Lua tables as Python lists.
    allowed = bool(int(out[0]))
    retry_ms = int(out[1])
    return allowed, retry_ms
