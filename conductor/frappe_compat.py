"""Drop-in shim with the same call signature as frappe.enqueue.

Client apps opt in via:
    override_whitelisted_methods = {"frappe.enqueue": "conductor.frappe_compat.enqueue"}
in their `hooks.py`. The override rewrites HTTP `/api/method/frappe.enqueue`
calls so they land here. NOTE: intra-process Python `frappe.enqueue(...)`
calls bypass the override and still go to RQ.
"""

from __future__ import annotations

from typing import Any

import frappe

import conductor


@frappe.whitelist()
def enqueue(method: str, queue: str = "default", timeout: int | None = None, **kwargs: Any) -> str:
    """frappe.enqueue-shaped wrapper around conductor.enqueue."""
    return conductor.enqueue(method, queue=queue, timeout=timeout, **kwargs)
