"""Drop-in shim with the same call signature as frappe.enqueue.

Client apps opt in via:
    override_whitelisted_methods = {"frappe.enqueue": "conductor.frappe_compat.enqueue"}
in their `hooks.py`.
"""

from __future__ import annotations

from typing import Any

import conductor


def enqueue(method: str, queue: str = "default", timeout: int | None = None, **kwargs: Any) -> str:
    """frappe.enqueue-shaped wrapper around conductor.enqueue."""
    return conductor.enqueue(method, queue=queue, timeout=timeout, **kwargs)
