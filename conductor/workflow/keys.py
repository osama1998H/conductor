"""Redis key namespacing for Phase 5 workflow state.

All keys follow master §8 / spec §9: conductor:{site}:<purpose>:<scope>.
Lua scripts touch the wfdeps key only — single-key per master §3 #15.
"""

from __future__ import annotations

from hashlib import sha256


def wfdeps_key(site: str, run_id: str) -> str:
    return f"conductor:{site}:wfdeps:{run_id}"


def wfidem_key(site: str, idempotency_key: str) -> str:
    h = sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"conductor:{site}:wfidem:{h}"
