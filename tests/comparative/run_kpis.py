"""Entry point for the Conductor-vs-RQ KPI suite.

Usage (from the bench root):
    /Users/osamamuhammed/frappe_15/env/bin/python \\
        -m tests.comparative.run_kpis [--kpi 1] [--engine conductor|rq|both]

Frappe is initialized once; both engine adapters reuse that connection.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

BENCH_ROOT = Path("/Users/osamamuhammed/frappe_15")
SITE = "frappe.localhost"


def _frappe_init():
    os.chdir(str(BENCH_ROOT))
    sys.path.insert(0, str(BENCH_ROOT / "apps" / "conductor"))
    import frappe
    frappe.init(site=SITE, sites_path=str(BENCH_ROOT / "sites"))
    frappe.connect()
    return frappe


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kpi", type=int, default=1, help="KPI number to run (1..6)")
    parser.add_argument("--engine", default="both", choices=("conductor", "rq", "both"))
    parser.add_argument("--report", default=None, help="path to write JSON report (optional)")
    args = parser.parse_args()

    _frappe_init()
    from tests.comparative.harness import make_engine

    if args.kpi == 1:
        from tests.comparative.kpi_01_transient_recovery import run as run_kpi
    elif args.kpi == 2:
        from tests.comparative.kpi_02_audit_completeness import run as run_kpi
    elif args.kpi == 3:
        from tests.comparative.kpi_03_dlq_visibility import run as run_kpi
    elif args.kpi == 4:
        from tests.comparative.kpi_04_idempotency import run as run_kpi
    elif args.kpi == 5:
        from tests.comparative.kpi_05_throughput import run as run_kpi
    else:
        print(f"KPI {args.kpi} not implemented yet", file=sys.stderr)
        sys.exit(2)

    engines = (
        ("conductor", "rq") if args.engine == "both" else (args.engine,)
    )

    results = []
    for ename in engines:
        engine = make_engine(ename)
        try:
            result = run_kpi(engine)
            results.append(asdict(result))
        finally:
            engine.teardown()

    print("\n=== summary ===")
    for r in results:
        print(json.dumps(r, indent=2, default=str))

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps({"kpi": args.kpi, "results": results}, indent=2, default=str))
        print(f"\nwrote {report_path}")


if __name__ == "__main__":
    main()
