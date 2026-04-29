"""Unit tests for conductor.migrate_rq.

Mocks RQ entirely: no rq.Queue instantiation, no real Redis. Asserts the
migration logic — filtering by site, translating queue names, calling
conductor.enqueue, deleting the source RQ job, and the dry-run vs commit
distinction.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fake_rq_jobs():
    """Three RQ jobs: two on the right site, one on a different site (skip)."""
    j1 = MagicMock()
    j1.id = "rq-job-1"
    j1.kwargs = {"site": "alpha.test", "method": "frappe.utils.now", "kwargs": {}}
    j1.delete = MagicMock()

    j2 = MagicMock()
    j2.id = "rq-job-2"
    j2.kwargs = {"site": "alpha.test", "method": "demo.foo", "kwargs": {"x": 1}}
    j2.delete = MagicMock()

    j3 = MagicMock()
    j3.id = "rq-job-other-site"
    j3.kwargs = {"site": "beta.test", "method": "demo.bar", "kwargs": {}}
    j3.delete = MagicMock()

    return [j1, j2, j3]


def test_marker_present_returns_no_op(fake_rq_jobs, fake_redis):
    fake_redis.set("conductor:alpha.test:rq_migrated_at", "2026-04-29T10:00:00")
    from conductor.migrate_rq import migrate_from_rq
    rep = migrate_from_rq(
        "alpha.test",
        queue_map={"default": "default"},
        commit=True,
        force=False,
        _redis_client=fake_redis,
        _rq_pending_jobs=lambda: fake_rq_jobs,
    )
    assert rep.skipped_due_to_marker is True
    assert rep.moved == 0


def test_marker_present_with_force_proceeds(fake_rq_jobs, fake_redis):
    fake_redis.set("conductor:alpha.test:rq_migrated_at", "old")
    enqueued: list = []
    def fake_enqueue(method, *, queue, **kwargs):
        enqueued.append((method, queue, dict(kwargs)))
        return f"new-{len(enqueued)}"
    from conductor.migrate_rq import migrate_from_rq
    rep = migrate_from_rq(
        "alpha.test",
        queue_map={"default": "default"},
        commit=True,
        force=True,
        _redis_client=fake_redis,
        _rq_pending_jobs=lambda: fake_rq_jobs,
        _enqueue=fake_enqueue,
    )
    assert rep.skipped_due_to_marker is False
    assert rep.moved == 2  # j1, j2 — j3 skipped (different site)


def test_dry_run_does_not_call_enqueue_or_delete(fake_rq_jobs, fake_redis):
    enq_called = []
    from conductor.migrate_rq import migrate_from_rq
    rep = migrate_from_rq(
        "alpha.test",
        queue_map={"default": "default"},
        commit=False,
        force=False,
        _redis_client=fake_redis,
        _rq_pending_jobs=lambda: fake_rq_jobs,
        _enqueue=lambda *a, **k: enq_called.append(True) or "x",
    )
    assert enq_called == []
    for j in fake_rq_jobs:
        assert j.delete.call_count == 0
    # The plan rows are populated for the operator to review:
    assert len(rep.plan) == 2  # two on alpha.test
    # Marker not set on dry-run
    assert fake_redis.get("conductor:alpha.test:rq_migrated_at") is None


def test_commit_calls_enqueue_then_delete_then_writes_marker(fake_rq_jobs, fake_redis):
    new_ids = iter(["new-1", "new-2"])
    enqueued = []
    def fake_enq(method, *, queue, **kwargs):
        enqueued.append((method, queue))
        return next(new_ids)
    from conductor.migrate_rq import migrate_from_rq
    rep = migrate_from_rq(
        "alpha.test",
        queue_map={"default": "default"},
        commit=True,
        force=False,
        _redis_client=fake_redis,
        _rq_pending_jobs=lambda: fake_rq_jobs,
        _enqueue=fake_enq,
    )
    assert rep.moved == 2
    assert fake_rq_jobs[0].delete.call_count == 1
    assert fake_rq_jobs[1].delete.call_count == 1
    assert fake_rq_jobs[2].delete.call_count == 0  # other-site, untouched
    assert fake_redis.get("conductor:alpha.test:rq_migrated_at") is not None


def test_callable_method_is_skipped_with_warning(fake_rq_jobs, fake_redis):
    j_callable = MagicMock()
    j_callable.id = "rq-callable"
    j_callable.kwargs = {"site": "alpha.test",
                         "method": lambda: None,  # callable, not str
                         "kwargs": {}}
    j_callable.delete = MagicMock()
    from conductor.migrate_rq import migrate_from_rq
    rep = migrate_from_rq(
        "alpha.test",
        queue_map={"default": "default"},
        commit=True,
        force=False,
        _redis_client=fake_redis,
        _rq_pending_jobs=lambda: [j_callable],
        _enqueue=lambda *a, **k: "new",
    )
    assert rep.moved == 0
    assert rep.skipped_callable_method == 1
    assert j_callable.delete.call_count == 0


def test_unmapped_rq_queue_falls_back_to_default(fake_redis):
    j = MagicMock()
    j.id = "rq-x"
    j.kwargs = {"site": "alpha.test", "method": "x.y", "kwargs": {}}
    j.delete = MagicMock()
    j.origin = "long_q_unmapped"
    enq = []
    from conductor.migrate_rq import migrate_from_rq
    rep = migrate_from_rq(
        "alpha.test",
        queue_map={"short": "short", "default": "default"},
        commit=True,
        force=False,
        _redis_client=fake_redis,
        _rq_pending_jobs=lambda: [(j, "long_q_unmapped")],  # tuple form
        _enqueue=lambda method, *, queue, **k: enq.append((method, queue)) or "x",
    )
    assert rep.moved == 1
    assert enq == [("x.y", "default")]
    assert rep.unmapped_queues_seen == {"long_q_unmapped": 1}
