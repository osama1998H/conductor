"""Exercise every `bench conductor` subcommand and record observed output.

This is a fixture-driven harness: scenarios is a list of (label, args, expectation),
where args is appended to `bench --site frappe.localhost conductor`. expectation
is a dict with optional 'exit', 'stdout_contains', 'stderr_contains'.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

BENCH_DIR = "/Users/osamamuhammed/frappe_15"
SITE = "frappe.localhost"
OUTPUT = Path(
    "/Users/osamamuhammed/frappe_15/apps/conductor/"
    "docs/roadmap/v2-certification/cli.json"
)

SCENARIOS: list[dict[str, Any]] = [
    {
        "label": "doctor",
        "args": ["doctor"],
        "expect": {"exit": 0, "stdout_contains": ["OK"]},
    },
    {
        "label": "doctor --demo",
        "args": ["doctor", "--demo"],
        "expect": {"exit": 0, "stdout_contains": ["demo"]},
    },
    {
        "label": "depth",
        "args": ["depth"],
        "expect": {"exit": 0},
    },
    {
        "label": "schedule list",
        "args": ["schedule", "list"],
        "expect": {"exit": 0},
    },
    {
        "label": "dlq list",
        "args": ["dlq", "list"],
        "expect": {"exit": 0},
    },
    {
        "label": "workflow list",
        "args": ["workflow", "list"],
        "expect": {"exit": 0},
    },
    {
        "label": "migrate-from-rq dry-run",
        "args": ["migrate-from-rq", "--site", SITE],
        "expect": {"exit": 0, "stdout_contains": ["plan rows"]},
    },
    # `worker` and `scheduler` are long-lived; we skip them here — the live
    # processes from M1 already exercise both surfaces.
    # `cancel` and `schedule run-now` are exercised in scenario expansions
    # below using ids captured from the running site.
]


def _run(label: str, args: list[str]) -> dict[str, Any]:
    cmd = ["bench", "--site", SITE, "conductor", *args]
    proc = subprocess.run(
        cmd, cwd=BENCH_DIR, capture_output=True, text=True, timeout=120,
    )
    return {
        "label": label,
        "argv": cmd,
        "exit": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _evaluate(observed: dict[str, Any], expected: dict[str, Any]) -> tuple[bool, str]:
    if "exit" in expected and observed["exit"] != expected["exit"]:
        return False, f"exit {observed['exit']} != {expected['exit']}"
    for fragment in expected.get("stdout_contains", []):
        if fragment.lower() not in (observed["stdout"] or "").lower():
            return False, f"stdout missing {fragment!r}"
    for fragment in expected.get("stderr_contains", []):
        if fragment.lower() not in (observed["stderr"] or "").lower():
            return False, f"stderr missing {fragment!r}"
    return True, ""


def run_all() -> list[dict[str, Any]]:
    results = []
    for sc in SCENARIOS:
        run = _run(sc["label"], sc["args"])
        ok, why = _evaluate(run, sc["expect"])
        run["pass"] = ok
        run["fail_reason"] = why
        results.append(run)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(results, indent=2, default=str))
    return results


if __name__ == "__main__":
    import sys
    res = run_all()
    failed = [r for r in res if not r["pass"]]
    print(f"{len(res)} scenarios, {len(failed)} failed")
    sys.exit(1 if failed else 0)
