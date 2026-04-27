"""Unit tests for conductor.context — thread-local job context + watchdog."""

import threading
import time
from datetime import datetime, timedelta, timezone

from conductor.context import context, set_context, start_watchdog


def test_default_context_is_empty():
    assert context.job_id is None
    assert context.attempt is None
    assert context.deadline is None
    assert context.should_cancel() is False


def test_set_context_restores_on_exit():
    with set_context(job_id="abc", attempt=1, deadline=None):
        assert context.job_id == "abc"
        assert context.attempt == 1
    assert context.job_id is None
    assert context.attempt is None


def test_context_is_thread_local():
    seen = {}

    def worker(name: str):
        with set_context(job_id=name, attempt=1, deadline=None):
            time.sleep(0.05)
            seen[name] = context.job_id

    t1 = threading.Thread(target=worker, args=("A",))
    t2 = threading.Thread(target=worker, args=("B",))
    t1.start(); t2.start(); t1.join(); t2.join()

    assert seen == {"A": "A", "B": "B"}


def test_watchdog_flips_should_cancel_after_deadline():
    cancel = threading.Event()
    deadline = datetime.now(timezone.utc) + timedelta(milliseconds=50)
    wd = start_watchdog(deadline, cancel)
    try:
        time.sleep(0.15)
        assert cancel.is_set() is True
    finally:
        wd.cancel()


def test_watchdog_cancel_prevents_flip():
    cancel = threading.Event()
    deadline = datetime.now(timezone.utc) + timedelta(milliseconds=200)
    wd = start_watchdog(deadline, cancel)
    wd.cancel()
    time.sleep(0.3)
    assert cancel.is_set() is False


def test_should_cancel_reflects_event_in_context():
    cancel = threading.Event()
    with set_context(job_id="x", attempt=1, deadline=None, cancel_event=cancel):
        assert context.should_cancel() is False
        cancel.set()
        assert context.should_cancel() is True
