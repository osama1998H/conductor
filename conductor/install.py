"""Install/uninstall hooks for the Conductor app.

`after_install` is invoked once when `bench install-app conductor` is run on a
site. It seeds the four default queues and the Conductor Operator role.
"""

from __future__ import annotations

import frappe

DEFAULT_QUEUES = [
    {"queue_name": "default",  "concurrency": 4, "default_max_attempts": 3, "default_timeout": 300},
    {"queue_name": "short",    "concurrency": 4, "default_max_attempts": 3, "default_timeout": 60},
    {"queue_name": "long",     "concurrency": 2, "default_max_attempts": 3, "default_timeout": 3600},
    {"queue_name": "critical", "concurrency": 8, "default_max_attempts": 10, "default_timeout": 300},
]


def after_install():
    _ensure_role()
    _seed_queues()
    _add_indexes()
    frappe.db.commit()


def _ensure_role():
    if not frappe.db.exists("Role", "Conductor Operator"):
        frappe.get_doc(
            {"doctype": "Role", "role_name": "Conductor Operator", "desk_access": 1}
        ).insert(ignore_permissions=True)


def _seed_queues():
    for q in DEFAULT_QUEUES:
        if frappe.db.exists("Conductor Queue", q["queue_name"]):
            continue
        frappe.get_doc({"doctype": "Conductor Queue", **q}).insert(ignore_permissions=True)


def _add_indexes():
    # Composite indexes on Conductor Job for status-based queue scans.
    frappe.db.add_index("Conductor Job", ["status", "queue", "scheduled_at"])
    frappe.db.add_index("Conductor Job", ["status", "queue", "enqueued_at"])
    frappe.db.add_index("Conductor Job", ["idempotency_key"])
