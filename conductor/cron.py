"""Cron expression evaluation in a per-Schedule timezone, returning UTC.

Skip-and-resume catch-up is implicit: get_next(base) returns a time strictly
after base = now, so missed runs are silently dropped.
"""

from __future__ import annotations

import logging
import zoneinfo
from datetime import datetime, timezone

from croniter import croniter

_log = logging.getLogger(__name__)


def compute_next_run_at(
    cron_expression: str,
    tz_name: str = "UTC",
    base: datetime | None = None,
) -> datetime:
    """Return the next fire time strictly after `base` (default: now), as UTC-aware.

    `base` may be naive (treated as UTC) or tz-aware. `tz_name` is the schedule's
    declared timezone; cron is evaluated in that local time. Unknown timezones
    fall back to UTC. Raises whatever `croniter` raises on malformed expressions
    (typically `croniter.CroniterBadCronError`)."""
    if base is None:
        base = datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    try:
        tz = zoneinfo.ZoneInfo(tz_name or "UTC")
    except zoneinfo.ZoneInfoNotFoundError:
        _log.warning("compute_next_run_at: unknown tz %r, falling back to UTC", tz_name)
        tz = zoneinfo.ZoneInfo("UTC")
    base_local = base.astimezone(tz)
    itr = croniter(cron_expression, base_local)
    next_local = itr.get_next(datetime)
    return next_local.astimezone(timezone.utc)
