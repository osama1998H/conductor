"""Health-check + acceptance demo for Conductor.

Steps 1–4 run without --demo (suitable for CI/liveness probes). Steps 5–6 add a
real round-trip dispatch via `conductor.demo.echo`.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable

import frappe

import conductor
from conductor.client import get_redis
from conductor.config import load_config
from conductor.streams import CONSUMER_GROUP, ensure_consumer_group, stream_key
from conductor.worker import run_worker_once

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

    ok &= _step("[1/6] Redis connectivity", check_redis)
    ok &= _step("[2/6] Default queues seeded", check_queues)
    ok &= _step("[3/6] Consumer groups exist", check_groups)
    ok &= _step("[4/6] XADD/XREADGROUP/XACK round-trip", check_round_trip)

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
            return "round-trip preserved"

        ok &= _step("[5/6] End-to-end demo dispatch (conductor.demo.echo)", step_dispatch)
        ok &= _step("[6/6] Result round-trip", step_result)

    if ok:
        print("\n\033[32mAll checks passed. Conductor is healthy.\033[0m")
        return 0
    print("\n\033[31mOne or more checks failed.\033[0m")
    return 1
