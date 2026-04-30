"""One-shot producer subprocess for KPI 4.

Initializes Frappe in its own process, calls the engine's enqueue once,
prints the job_id (or an error tag) to stdout. Used by KPI 4's
multiprocessing-based concurrent-producer test.
"""

from __future__ import annotations

import os
import sys


def main():
    if len(sys.argv) != 6:
        print("ERR: usage <engine> <site> <method> <idem_key> <counter_name>", file=sys.stderr)
        sys.exit(2)
    engine_name, site, method, idem_key, counter_name = sys.argv[1:6]

    os.chdir("/Users/osamamuhammed/frappe_15")
    sys.path.insert(0, "/Users/osamamuhammed/frappe_15/apps/conductor")
    import frappe
    frappe.init(site=site, sites_path="/Users/osamamuhammed/frappe_15/sites")
    frappe.connect()
    try:
        from tests.comparative.harness import make_engine
        engine = make_engine(engine_name)
        try:
            jid = engine.enqueue(
                method,
                idempotency_key=idem_key,
                timeout=60,
                counter_name=counter_name,
            )
            print(f"OK:{jid}")
        except Exception as e:
            print(f"ERR:{type(e).__name__}: {e}")
    finally:
        try:
            frappe.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    main()
