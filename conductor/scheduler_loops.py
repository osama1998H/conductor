"""Aggregator for the four scheduler loops. Each Task 6-9 fills in one loop."""

from __future__ import annotations

import threading

import redis as redis_mod


def start_all_loops(
    *,
    redis_client: redis_mod.Redis,
    site: str,
    sites_path: str | None,
    stop_event: threading.Event,
    lost_lock_event: threading.Event,
) -> list[threading.Thread]:
    """Start delay, cron, reaper, sweeper as daemon threads. Returns the list."""
    threads: list[threading.Thread] = []
    # Filled in by Tasks 6 (cron), 7 (delay), 8 (reaper), 9 (sweeper).
    return threads
