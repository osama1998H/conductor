"""Execution lock: defense-in-depth against double-execution under XACK races.

`acquire_exec_lock` does SET NX EX with the worker_id as the value. The TTL is
the job's timeout + 30s — long enough that a healthy worker holding it cannot
have it stolen, short enough that a dead worker's lock expires within a phase
of the job's expected runtime.

`release_exec_lock` uses a Lua check-and-delete so we only release if we still
own the key (avoids deleting a peer's lock that we lost ownership of via TTL).
"""

from __future__ import annotations

import redis as redis_mod

# Lua: delete the key only if its current value equals the supplied value.
# Returns 1 on delete, 0 otherwise.
_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
else
  return 0
end
"""


def exec_lock_redis_key(site: str, job_id: str) -> str:
    return f"conductor:{site}:lock:{job_id}"


def acquire_exec_lock(
    client: redis_mod.Redis,
    site: str,
    job_id: str,
    worker_id: str,
    *,
    ttl: int,
) -> bool:
    """SET NX EX. Returns True if newly acquired, False if held by a peer."""
    return bool(client.set(exec_lock_redis_key(site, job_id), worker_id, nx=True, ex=ttl))


def release_exec_lock(
    client: redis_mod.Redis,
    site: str,
    job_id: str,
    worker_id: str,
) -> bool:
    """Release iff we still own the lock. Returns True if released, False otherwise."""
    result = client.eval(_RELEASE_LUA, 1, exec_lock_redis_key(site, job_id), worker_id)
    return bool(result)
