"""Structlog configuration for Conductor processes.

JSON output to stdout; bind worker/site context up front so every line carries it.
"""

from __future__ import annotations

import logging
import sys

import structlog


def setup_logging(*, site: str | None = None, worker_id: str | None = None) -> None:
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )
    if site or worker_id:
        ctx = {}
        if site:
            ctx["site"] = site
        if worker_id:
            ctx["worker_id"] = worker_id
        structlog.contextvars.bind_contextvars(**ctx)


def get_logger(name: str = "conductor"):
    return structlog.get_logger(name)
