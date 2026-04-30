"""Workflow-run idempotency lock — wraps Redis SET NX EX, mirrors job idem."""

from conductor.workflow.idempotency import acquire_wfidem_lock


def test_first_call_acquires_lock(fake_redis):
    existing = acquire_wfidem_lock(
        fake_redis,
        site="frappe.localhost",
        idempotency_key="run-once",
        run_id="run-1",
        ttl=60,
    )
    assert existing is None


def test_second_call_with_same_key_returns_first_run_id(fake_redis):
    acquire_wfidem_lock(
        fake_redis, site="frappe.localhost",
        idempotency_key="run-once", run_id="run-1", ttl=60,
    )
    existing = acquire_wfidem_lock(
        fake_redis, site="frappe.localhost",
        idempotency_key="run-once", run_id="run-2", ttl=60,
    )
    assert existing == "run-1"


def test_empty_key_returns_none_no_state_change(fake_redis):
    existing = acquire_wfidem_lock(
        fake_redis, site="frappe.localhost",
        idempotency_key="", run_id="run-1", ttl=60,
    )
    assert existing is None
    keys = fake_redis.keys("conductor:*")
    assert keys == []
