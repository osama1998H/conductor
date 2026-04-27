"""Demo functions used by `bench conductor doctor --demo` and tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def echo(**kwargs: Any) -> dict:
    """Return a dict echoing what was sent in, plus a server timestamp."""
    return {"echo": kwargs, "now": datetime.now(timezone.utc).isoformat()}


def boom(**kwargs: Any) -> None:
    """Always raises — used for failure tests."""
    raise RuntimeError(f"intentional failure (kwargs={kwargs!r})")


def slow_chaos(**kwargs: Any) -> dict:
    """Sleeps long enough for a kill -9 to interrupt mid-execution.

    Used by the chaos test `test_kill_during_run` (Task 16). Returns
    ``{"completed": True}`` when the peer worker reclaims and finishes.

    Must be a top-level function in this module so subprocess workers can
    import it fresh (``frappe.get_attr("conductor.demo.slow_chaos")``).
    """
    import time
    time.sleep(8)
    return {"completed": True}
