"""Unit tests for conductor.scheduler_lock — singleton lock with Lua-renew/release."""

import time

import fakeredis
import pytest

from conductor.scheduler_lock import (
    acquire,
    lock_redis_key,
    release,
    renew,
)


@pytest.fixture
def r():
    """fakeredis with Lua via lupa."""
    return fakeredis.FakeStrictRedis()


def test_lock_redis_key_format():
    assert lock_redis_key("frappe.localhost") == "conductor:frappe.localhost:scheduler:lock"


def test_acquire_succeeds_on_empty(r):
    assert acquire(r, "site1", "instance-A", ttl=15) is True
    assert r.get("conductor:site1:scheduler:lock") == b"instance-A"


def test_second_acquire_fails(r):
    assert acquire(r, "site1", "instance-A", ttl=15) is True
    assert acquire(r, "site1", "instance-B", ttl=15) is False
    assert r.get("conductor:site1:scheduler:lock") == b"instance-A"


def test_renew_returns_true_while_we_own(r):
    assert acquire(r, "site1", "instance-A", ttl=15) is True
    assert renew(r, "site1", "instance-A", ttl=15) is True


def test_renew_returns_false_after_steal(r):
    assert acquire(r, "site1", "instance-A", ttl=15) is True
    # Simulate someone else owning the key.
    r.set("conductor:site1:scheduler:lock", "instance-B")
    assert renew(r, "site1", "instance-A", ttl=15) is False


def test_renew_returns_false_when_key_missing(r):
    # No prior acquire.
    assert renew(r, "site1", "instance-A", ttl=15) is False


def test_release_deletes_when_we_own(r):
    assert acquire(r, "site1", "instance-A", ttl=15) is True
    assert release(r, "site1", "instance-A") is True
    assert r.get("conductor:site1:scheduler:lock") is None


def test_release_does_not_delete_when_we_dont_own(r):
    assert acquire(r, "site1", "instance-A", ttl=15) is True
    r.set("conductor:site1:scheduler:lock", "instance-B")
    assert release(r, "site1", "instance-A") is False
    assert r.get("conductor:site1:scheduler:lock") == b"instance-B"


def test_double_release_returns_false(r):
    assert acquire(r, "site1", "instance-A", ttl=15) is True
    assert release(r, "site1", "instance-A") is True
    assert release(r, "site1", "instance-A") is False


def test_ttl_expiry_allows_takeover(r):
    assert acquire(r, "site1", "instance-A", ttl=1) is True
    time.sleep(1.2)
    assert acquire(r, "site1", "instance-B", ttl=15) is True
    assert r.get("conductor:site1:scheduler:lock") == b"instance-B"


def test_renew_extends_ttl_for_owner(r):
    assert acquire(r, "site1", "instance-A", ttl=2) is True
    time.sleep(1.0)
    assert renew(r, "site1", "instance-A", ttl=10) is True
    time.sleep(1.5)
    # Original 2s would have expired; renewal extended to 10s, so still alive.
    assert r.get("conductor:site1:scheduler:lock") == b"instance-A"


def test_renew_lua_returns_integer_1_on_success(r):
    """Pin the Lua return-type contract — bool() collapses int/str/bytes alike,
    so this raw-eval test is the only thing that catches a regression where
    the script accidentally returns a non-integer."""
    acquire(r, "site1", "instance-A", ttl=15)
    key = lock_redis_key("site1")
    from conductor.scheduler_lock import _RENEW_LUA
    result = r.eval(_RENEW_LUA, 1, key, "instance-A", 15000)
    assert result == 1  # integer, not truthy str/bytes/table


def test_release_lua_returns_integer_1_on_success(r):
    """Pin the Lua return-type contract for the release script."""
    acquire(r, "site1", "instance-A", ttl=15)
    key = lock_redis_key("site1")
    from conductor.scheduler_lock import _RELEASE_LUA
    result = r.eval(_RELEASE_LUA, 1, key, "instance-A")
    assert result == 1
