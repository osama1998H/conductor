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


def sleep(seconds: float = 0.1, **kwargs: Any) -> None:
    """Sleep for `seconds`, then return. Used by the Phase 6 rate-limit chaos
    test: `time.sleep` cannot be invoked directly because `frappe.get_attr`
    treats the first dotted segment as an app name."""
    import time
    time.sleep(seconds)


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


# Phase 5 chaos demo workflow — must live here so worker subprocesses can
# import the class via frappe.get_attr (the test process cannot give the
# worker a class defined inside a test function).
from conductor.workflow import Step, workflow


@workflow(name="DemoDiamond", queue="default")
class DemoDiamond:
    """Diamond DAG: a → {b, c} → d. Used by Phase 5 chaos tests."""

    _a = Step("a")
    _b = Step("b", depends_on=("a",))
    _c = Step("c", depends_on=("a",))
    _d = Step("d", depends_on=("b", "c"))

    def a(self, **kwargs: Any) -> None:
        pass

    def b(self, **kwargs: Any) -> None:
        pass

    def c(self, **kwargs: Any) -> None:
        pass

    def d(self, **kwargs: Any) -> None:
        pass


@workflow(name="DemoCompensatingDiamond", queue="default")
class DemoCompensatingDiamond:
    """Diamond DAG with compensations on a and b. Step c fails terminally
    after retries. Used by the Phase 5 exit-criterion chaos test (master §4)."""

    _a = Step("a", compensation="undo_a")
    _b = Step("b", depends_on=("a",), compensation="undo_b")
    _c = Step("c", depends_on=("a",))
    _d = Step("d", depends_on=("b", "c"))

    def a(self, **kwargs: Any) -> None:
        pass

    def undo_a(self, **kwargs: Any) -> None:
        import frappe
        frappe.cache().set_value("phase5:undo_a:ran", "1")

    def b(self, **kwargs: Any) -> None:
        pass

    def undo_b(self, **kwargs: Any) -> None:
        import frappe
        frappe.cache().set_value("phase5:undo_b:ran", "1")

    def c(self, **kwargs: Any) -> None:
        raise RuntimeError("forced terminal failure for Phase 5 exit criterion")

    def d(self, **kwargs: Any) -> None:
        pass
