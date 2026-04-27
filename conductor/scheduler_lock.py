"""Singleton scheduler lock: SET NX EX + Lua check-and-PEXPIRE / check-and-DEL.

All three operations are single-key (master §3 #15 cluster-compat).
"""

from __future__ import annotations

import redis as redis_mod

# GET == ARGV[1] ? PEXPIRE KEYS[1] ARGV[2] : 0
_RENEW_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
else
  return 0
end
"""

# GET == ARGV[1] ? DEL KEYS[1] : 0
_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
else
  return 0
end
"""


def lock_redis_key(site: str) -> str:
    return f"conductor:{site}:scheduler:lock"


def acquire(client: redis_mod.Redis, site: str, instance_id: str, *, ttl: int = 15) -> bool:
    """SET NX EX ttl. Returns True on win, False if held by a peer."""
    return bool(client.set(lock_redis_key(site), instance_id, nx=True, ex=ttl))


def renew(client: redis_mod.Redis, site: str, instance_id: str, *, ttl: int = 15) -> bool:
    """Lua: GET == self ? PEXPIRE ttl*1000 : 0. Returns True iff still ours."""
    pttl_ms = ttl * 1000
    result = client.eval(_RENEW_LUA, 1, lock_redis_key(site), instance_id, pttl_ms)
    return bool(result)


def release(client: redis_mod.Redis, site: str, instance_id: str) -> bool:
    """Lua: GET == self ? DEL : 0. Returns True iff we deleted our own lock."""
    result = client.eval(_RELEASE_LUA, 1, lock_redis_key(site), instance_id)
    return bool(result)
