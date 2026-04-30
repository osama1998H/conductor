"""Launcher for an RQ worker on a queue name not registered in
get_queues_timeout(). `bench worker` rejects unknown queue names via
validate_queue; this script bypasses that by going direct to rq.

Usage:
    python -m tests.comparative._rq_worker_launcher <qname> <site>

The worker process initializes Frappe once at boot; per-job Frappe
context is set up by `frappe.utils.background_jobs.execute_job` itself
when called with `is_async=True`.
"""

from __future__ import annotations

import logging
import sys


def main(qname: str, site: str) -> None:
    import frappe

    frappe.init(site=site)
    frappe.connect()
    try:
        from frappe.utils.background_jobs import get_redis_conn
        from rq import Queue, Worker

        conn = get_redis_conn()
        queue = Queue(qname, connection=conn)
        worker = Worker([queue], connection=conn)
        logging.basicConfig(level=logging.WARNING)
        worker.work(logging_level="WARNING")
    finally:
        try:
            frappe.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: rq_worker_launcher.py <qname> <site>", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1], sys.argv[2])
