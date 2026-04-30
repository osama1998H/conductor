"""Per-(site, queue) concurrency-cap counter, Lua-backed and single-key.

Three scripts live in inflight.lua, separated by `-- @SCRIPT <name>` markers.
We parse them at import time so each call site uses the right registered
Script object. All three are single-key (cluster-safe per master §3 #15).
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

import redis as redis_mod

_SCRIPT_PATH = Path(__file__).with_name("inflight.lua")
_SOURCES: dict[str, str] | None = None
_SOURCES_LOCK = threading.Lock()
_REGISTERED: dict[tuple[int, str], "redis_mod.client.Script"] = {}


def inflight_key(site: str, queue: str) -> str:
    return f"conductor:{site}:inflight:{queue}"


def _load_scripts() -> dict[str, str]:
    """Parse inflight.lua into {script_name: source}. Splits on '-- @SCRIPT'
    headers; each section is one standalone single-key script."""
    text = _SCRIPT_PATH.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    current_name: str | None = None
    current_lines: list[str] = []
    header_re = re.compile(r"^--\s*@SCRIPT\s+(\w+)\s*$")
    for line in text.splitlines():
        m = header_re.match(line)
        if m:
            if current_name is not None:
                out[current_name] = "\n".join(current_lines).strip() + "\n"
            current_name = m.group(1)
            current_lines = []
        else:
            if current_name is not None:
                current_lines.append(line)
    if current_name is not None:
        out[current_name] = "\n".join(current_lines).strip() + "\n"
    return out


def _get_script(client: redis_mod.Redis, name: str) -> "redis_mod.client.Script":
    global _SOURCES
    if _SOURCES is None:
        with _SOURCES_LOCK:
            if _SOURCES is None:
                _SOURCES = _load_scripts()
    cid = (id(client.connection_pool), name)
    script = _REGISTERED.get(cid)
    if script is None:
        script = client.register_script(_SOURCES[name])
        _REGISTERED[cid] = script
    return script


def acquire(client: redis_mod.Redis, site: str, queue: str, *, max_concurrent: int) -> tuple[bool, int]:
    """Try to acquire one inflight slot. Returns (acquired, current_count).
    On rejection, current_count is the cap (== max_concurrent)."""
    out = _get_script(client, "acquire")(
        keys=[inflight_key(site, queue)],
        args=[max_concurrent],
    )
    return bool(int(out[0])), int(out[1])


def release(client: redis_mod.Redis, site: str, queue: str) -> int:
    """Release one inflight slot. Returns new count (floored at 0)."""
    out = _get_script(client, "release")(keys=[inflight_key(site, queue)])
    return int(out)


def correct_drift(client: redis_mod.Redis, site: str, queue: str, *, decrement_by: int) -> int:
    """Used by the reaper after marking N workers GONE — subtract N from
    the counter atomically and floor at 0. Returns new count."""
    out = _get_script(client, "correct_drift")(
        keys=[inflight_key(site, queue)],
        args=[decrement_by],
    )
    return int(out)


def get_count(client: redis_mod.Redis, site: str, queue: str) -> int:
    """Read the counter. Used by `bench conductor depth` and the reaper.
    Single-key GET; not Lua-wrapped."""
    val = client.get(inflight_key(site, queue))
    if val is None:
        return 0
    return int(val)
