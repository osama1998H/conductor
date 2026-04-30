"""Workflow Redis key helpers."""

from conductor.workflow.keys import wfdeps_key, wfidem_key


def test_wfdeps_key_format():
    assert wfdeps_key("frappe.localhost", "abc-123") == "conductor:frappe.localhost:wfdeps:abc-123"


def test_wfidem_key_is_sha256_hashed():
    k = wfidem_key("frappe.localhost", "ord-42-fulfill")
    assert k.startswith("conductor:frappe.localhost:wfidem:")
    h = k.rsplit(":", 1)[-1]
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
