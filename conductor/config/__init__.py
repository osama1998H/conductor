"""Reads conductor configuration from a Frappe site_config dict.

This module deliberately does not import frappe — it accepts a plain dict so
unit tests can run without a Frappe site.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

DEFAULT_DB = 2
DEFAULT_QUEUE = "default"
DEFAULT_STREAM_MAX_LEN = 10000


@dataclass(frozen=True)
class ConductorConfig:
    redis_url: str
    default_queue: str
    stream_max_len: int


def _force_db(url: str, db: int) -> str:
    parsed = urlparse(url)
    new_path = f"/{db}"
    return urlunparse(parsed._replace(path=new_path))


def load_config(site_config: dict) -> ConductorConfig:
    conductor_section = site_config.get("conductor") or {}
    redis_url = conductor_section.get("redis_url")
    if not redis_url:
        base = site_config.get("redis_queue")
        if not base:
            raise ValueError(
                "redis_url not configured: set site_config['conductor']['redis_url'] "
                "or site_config['redis_queue']"
            )
        redis_url = _force_db(base, DEFAULT_DB)

    return ConductorConfig(
        redis_url=redis_url,
        default_queue=conductor_section.get("default_queue", DEFAULT_QUEUE),
        stream_max_len=int(conductor_section.get("stream_max_len", DEFAULT_STREAM_MAX_LEN)),
    )
