"""Chaos test: two SEPARATE processes call conductor.enqueue with the same
idempotency_key concurrently. Exactly one Conductor Job row and exactly one
stream entry must result, and both processes must return the same job_id."""

import concurrent.futures as cf
import subprocess
from pathlib import Path

import frappe

BENCH_ROOT = Path("/Users/osamamuhammed/frappe_15")


def _enqueue_via_subprocess(site: str, idem_key: str) -> str:
    """Spawn a fresh Python process that calls conductor.enqueue, prints the
    job_id to stdout. Returns the job_id."""
    code = f"""
import os, sys
os.chdir({str(BENCH_ROOT)!r})
sys.path.insert(0, {str(BENCH_ROOT)!r})
import frappe, conductor
frappe.init(site={site!r}, sites_path={str(BENCH_ROOT / "sites")!r})
frappe.connect()
try:
    jid = conductor.enqueue("conductor.demo.echo", queue="default", idempotency_key={idem_key!r}, x=1)
    print(jid, flush=True)
finally:
    frappe.destroy()
"""
    proc = subprocess.run(
        [str(BENCH_ROOT / "env" / "bin" / "python"), "-c", code],
        cwd=str(BENCH_ROOT),
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"subprocess failed: {proc.stderr}")
    return proc.stdout.strip().splitlines()[-1]


def test_concurrent_dispatch_with_same_key_returns_same_job_id(site):
    from conductor.client import get_redis
    from conductor.config import load_config
    from conductor.idempotency import idem_redis_key
    cfg = load_config(frappe.local.conf)
    r = get_redis(cfg.redis_url)
    r.delete(idem_redis_key(site, "chaos-idem-test"))

    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        futures = [
            ex.submit(_enqueue_via_subprocess, site, "chaos-idem-test"),
            ex.submit(_enqueue_via_subprocess, site, "chaos-idem-test"),
        ]
        results = [f.result() for f in futures]

    assert results[0] == results[1], f"expected same job_id, got {results}"

    frappe.db.rollback()
    rows = frappe.get_all("Conductor Job", filters={"job_id": results[0]})
    assert len(rows) == 1, f"expected 1 row, got {len(rows)}"

    frappe.delete_doc("Conductor Job", results[0], force=True)
