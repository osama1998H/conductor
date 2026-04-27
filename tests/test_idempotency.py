"""Unit tests for conductor.idempotency — dispatch idempotency via SET NX EX."""

import time

from conductor.idempotency import acquire_idem_lock, idem_redis_key


def test_idem_redis_key_uses_sha256_hex():
    key = idem_redis_key("frappe.localhost", "invoice:INV-001:email")
    # 64 hex chars after the prefix
    assert key.startswith("conductor:frappe.localhost:idem:")
    assert len(key) == len("conductor:frappe.localhost:idem:") + 64
    # Same input → same hash
    assert key == idem_redis_key("frappe.localhost", "invoice:INV-001:email")
    # Different input → different hash
    assert key != idem_redis_key("frappe.localhost", "invoice:INV-002:email")


def test_acquire_returns_none_on_first_call(fake_redis):
    out = acquire_idem_lock(fake_redis, "frappe.localhost", "k1", "job-A", ttl=60)
    assert out is None


def test_acquire_returns_existing_job_id_on_dup(fake_redis):
    acquire_idem_lock(fake_redis, "frappe.localhost", "k1", "job-A", ttl=60)
    out = acquire_idem_lock(fake_redis, "frappe.localhost", "k1", "job-B", ttl=60)
    assert out == "job-A"


def test_acquire_with_empty_key_skips_lock(fake_redis):
    """Empty idempotency_key means: no idempotency, always allow dispatch."""
    out = acquire_idem_lock(fake_redis, "frappe.localhost", "", "job-A", ttl=60)
    assert out is None
    out = acquire_idem_lock(fake_redis, "frappe.localhost", "", "job-B", ttl=60)
    assert out is None  # would have collided, but empty key bypasses lock


def test_acquire_after_ttl_expiry_allows_reuse(fake_redis):
    acquire_idem_lock(fake_redis, "frappe.localhost", "k1", "job-A", ttl=1)
    time.sleep(1.2)  # let it expire (fakeredis honors EX)
    out = acquire_idem_lock(fake_redis, "frappe.localhost", "k1", "job-B", ttl=60)
    assert out is None  # newly acquired
