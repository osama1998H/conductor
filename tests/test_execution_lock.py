"""Unit tests for conductor.execution_lock — SET NX on conductor:{site}:lock:{job_id}."""

from conductor.execution_lock import (
    acquire_exec_lock,
    exec_lock_redis_key,
    release_exec_lock,
)


def test_exec_lock_redis_key():
    assert exec_lock_redis_key("frappe.localhost", "abc-123") == "conductor:frappe.localhost:lock:abc-123"


def test_acquire_succeeds_on_free_lock(fake_redis):
    ok = acquire_exec_lock(fake_redis, "frappe.localhost", "job-1", "worker-A", ttl=30)
    assert ok is True
    val = fake_redis.get(exec_lock_redis_key("frappe.localhost", "job-1"))
    assert val == b"worker-A"


def test_acquire_fails_when_held(fake_redis):
    acquire_exec_lock(fake_redis, "frappe.localhost", "job-1", "worker-A", ttl=30)
    ok = acquire_exec_lock(fake_redis, "frappe.localhost", "job-1", "worker-B", ttl=30)
    assert ok is False
    # Original holder unchanged
    assert fake_redis.get(exec_lock_redis_key("frappe.localhost", "job-1")) == b"worker-A"


def test_release_only_when_owner_matches(fake_redis):
    acquire_exec_lock(fake_redis, "frappe.localhost", "job-1", "worker-A", ttl=30)
    # A non-owner cannot release.
    released = release_exec_lock(fake_redis, "frappe.localhost", "job-1", "worker-B")
    assert released is False
    assert fake_redis.get(exec_lock_redis_key("frappe.localhost", "job-1")) == b"worker-A"
    # Owner can release.
    released = release_exec_lock(fake_redis, "frappe.localhost", "job-1", "worker-A")
    assert released is True
    assert fake_redis.get(exec_lock_redis_key("frappe.localhost", "job-1")) is None


def test_release_when_not_held_is_noop(fake_redis):
    released = release_exec_lock(fake_redis, "frappe.localhost", "job-never-acquired", "worker-A")
    assert released is False
