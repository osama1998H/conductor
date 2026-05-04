"""Fixtures shared across the campaign harness."""
from __future__ import annotations

import pytest
import frappe


@pytest.fixture()
def frappe_site():
    """Yield the configured Frappe site name and ensure connect/destroy book-ends."""
    site = "frappe.localhost"
    frappe.init(site=site)
    frappe.connect()
    try:
        yield site
    finally:
        frappe.destroy()
