"""Per-job execution context exposed to user code.

The `context` object is thread-local; one job per thread (we use a
ThreadPoolExecutor in the worker, one job pinned to one thread for its lifetime).
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import datetime, timezone


class _Context(threading.local):
    job_id: str | None = None
    attempt: int | None = None
    deadline: datetime | None = None
    cancel_event: threading.Event | None = None

    def should_cancel(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()


context = _Context()


@contextmanager
def set_context(
    *,
    job_id: str,
    attempt: int,
    deadline: datetime | None,
    cancel_event: threading.Event | None = None,
):
    prev = (context.job_id, context.attempt, context.deadline, context.cancel_event)
    context.job_id = job_id
    context.attempt = attempt
    context.deadline = deadline
    context.cancel_event = cancel_event
    try:
        yield
    finally:
        context.job_id, context.attempt, context.deadline, context.cancel_event = prev


def start_watchdog(deadline: datetime, cancel_event: threading.Event) -> threading.Timer:
    """Schedule `cancel_event.set()` at `deadline`. Returns the Timer (call .cancel() to stop)."""
    now = datetime.now(timezone.utc)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    delay = max(0.0, (deadline - now).total_seconds())
    timer = threading.Timer(delay, cancel_event.set)
    timer.daemon = True
    timer.start()
    return timer
