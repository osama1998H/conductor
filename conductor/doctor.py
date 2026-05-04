"""Health-check + acceptance demo for Conductor.

Steps 1–4 run without --demo (suitable for CI/liveness probes). Steps 5–6 add a
real round-trip dispatch via `conductor.demo.echo`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import frappe

from conductor.frappe_scheduled_loop import (
    ACTIVATION_FLAG,
    DEFAULT_QUEUE_MAP,
    QUEUE_MAP_KEY,
)

import conductor
from conductor.client import get_redis
from conductor.config import load_config
from conductor.streams import CONSUMER_GROUP, ensure_consumer_group, stream_key
from conductor.worker import run_worker_once

WORKER_FRESHNESS_SECONDS = 90  # heartbeat window — must be > one heartbeat tick


@dataclass
class CheckResult:
    ok: bool
    detail: str


OK = "\033[32mOK\033[0m"
FAIL = "\033[31mFAIL\033[0m"


def _step(label: str, fn: Callable[[], str]) -> bool:
    line = f"{label}".ljust(70, ".")
    try:
        detail = fn()
        print(f"{line} {OK}  ({detail})")
        return True
    except Exception as e:
        print(f"{line} {FAIL} ({e})")
        return False


def _fetch_fresh_workers() -> list[dict]:
    """Return Conductor Worker rows whose `last_heartbeat` is within the
    freshness window. Each row carries `queues` as the raw JSON string from
    the underlying Long Text field plus a `stale` boolean for tests that
    want to inject staleness without seeding wall-clock data.

    `last_heartbeat` is written as UTC-naive by `conductor.worker._now_naive`,
    so the threshold is computed in the same timezone. Using `datetime.now()`
    (local) instead would be wrong by the host's UTC offset on any non-UTC
    bench."""
    threshold = (
        datetime.now(timezone.utc).replace(tzinfo=None)
        - timedelta(seconds=WORKER_FRESHNESS_SECONDS)
    )
    rows = frappe.get_all(
        "Conductor Worker",
        fields=["name", "queues", "last_heartbeat"],
        filters={"last_heartbeat": [">=", threshold]},
        order_by="last_heartbeat desc",
    )
    return [{"name": r["name"], "queues": r["queues"], "stale": False} for r in rows]


def _parse_queues(field_value: str) -> set[str]:
    """`Conductor Worker.queues` is a JSON-encoded list. Return the set of
    queue names. Tolerate empty/None/malformed values by returning an
    empty set — a malformed worker row should not crash doctor."""
    if not field_value:
        return set()
    try:
        parsed = json.loads(field_value)
    except (TypeError, ValueError):
        return set()
    if not isinstance(parsed, list):
        return set()
    return {str(q) for q in parsed}


def check_takeover_queue_coverage(
    *,
    takeover_enabled: bool,
    queue_map: dict[str, str],
) -> CheckResult:
    """Verify every queue the takeover loop dispatches to has at least one
    heartbeat-fresh worker listening. No-op when the takeover flag is unset.

    Pure function: takes the activation flag and the merged queue-map as
    arguments so unit tests can exercise it without seeding site config."""
    if not takeover_enabled:
        return CheckResult(ok=True, detail="takeover disabled — skipped")

    required_queues = set(queue_map.values()) or {"default"}
    fresh = [w for w in _fetch_fresh_workers() if not w.get("stale")]
    covered: set[str] = set()
    for w in fresh:
        covered |= _parse_queues(w.get("queues") or "")

    missing = required_queues - covered
    if missing:
        missing_csv = ", ".join(sorted(missing))
        covered_csv = ", ".join(sorted(covered)) or "none"
        return CheckResult(
            ok=False,
            detail=(
                f"takeover dispatches to {{{', '.join(sorted(required_queues))}}} but "
                f"workers cover {{{covered_csv}}} — uncovered: {missing_csv}. "
                f"Add `--queue {missing_csv}` to a `bench conductor worker` Procfile entry."
            ),
        )
    return CheckResult(
        ok=True,
        detail=f"all takeover queues covered ({', '.join(sorted(required_queues))})",
    )


def run(*, demo: bool = False) -> int:
    site = frappe.local.site
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)

    ok = True

    def check_redis() -> str:
        r.ping()
        return cfg.redis_url

    def check_queues() -> str:
        names = [q.name for q in frappe.get_all("Conductor Queue", filters={"enabled": 1})]
        if not names:
            raise RuntimeError("no enabled queues")
        return ", ".join(sorted(names))

    def check_groups() -> str:
        for q in frappe.get_all("Conductor Queue", filters={"enabled": 1}, pluck="name"):
            ensure_consumer_group(r, stream_key(site, q))
        return "groups created/verified"

    def check_round_trip() -> str:
        skey = stream_key(site, "doctor")
        ensure_consumer_group(r, skey)
        msg_id = r.xadd(skey, {"probe": "1"})
        msgs = r.xreadgroup(CONSUMER_GROUP, "doctor-consumer", {skey: ">"}, count=1, block=1000)
        if not msgs:
            raise RuntimeError("XREADGROUP returned nothing")
        sname, entries = msgs[0]
        for mid, _ in entries:
            r.xack(skey, CONSUMER_GROUP, mid)
        r.delete(skey)
        return "round-trip OK"

    ok &= _step("[1/7] Redis connectivity", check_redis)
    ok &= _step("[2/7] Default queues seeded", check_queues)
    ok &= _step("[3/7] Consumer groups exist", check_groups)
    ok &= _step("[4/7] XADD/XREADGROUP/XACK round-trip", check_round_trip)

    def check_takeover_coverage() -> str:
        conf = frappe.local.conf or {}
        takeover_enabled = bool(conf.get(ACTIVATION_FLAG, False))
        merged = dict(DEFAULT_QUEUE_MAP)
        merged.update(conf.get(QUEUE_MAP_KEY) or {})
        result = check_takeover_queue_coverage(
            takeover_enabled=takeover_enabled, queue_map=merged,
        )
        if not result.ok:
            raise RuntimeError(result.detail)
        return result.detail

    ok &= _step("[5/7] Takeover queue coverage", check_takeover_coverage)

    if demo:
        job_id_holder = {}

        def step_dispatch() -> str:
            jid = conductor.enqueue("conductor.demo.echo", queue="default", k=42, ts=datetime.now(timezone.utc))
            job_id_holder["id"] = jid
            run_worker_once(queues=["default"], concurrency=2, site=site, block_ms=2000)
            end = time.time() + 10
            while time.time() < end:
                frappe.db.rollback()
                status = frappe.db.get_value("Conductor Job", jid, "status")
                if status in ("SUCCEEDED", "FAILED", "TIMED_OUT"):
                    if status != "SUCCEEDED":
                        raise RuntimeError(f"demo job ended {status}")
                    return f"job_id={jid} succeeded"
                time.sleep(0.2)
            raise RuntimeError("demo job did not terminate within 10s")

        def step_result() -> str:
            jid = job_id_holder.get("id")
            if not jid:
                raise RuntimeError("no demo job to inspect")
            preview = frappe.db.get_value("Conductor Job", jid, "result_preview") or ""
            if "echo" not in preview:
                raise RuntimeError("result_preview missing echo")
            frappe.delete_doc("Conductor Job", jid, force=True)
            frappe.db.commit()
            return "round-trip preserved"

        ok &= _step("[6/7] End-to-end demo dispatch (conductor.demo.echo)", step_dispatch)
        ok &= _step("[7/7] Result round-trip", step_result)

    if ok:
        print("\n\033[32mAll checks passed. Conductor is healthy.\033[0m")
        return 0
    print("\n\033[31mOne or more checks failed.\033[0m")
    return 1
