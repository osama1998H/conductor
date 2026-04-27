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
