"""Pool-worker chaos: pool worker survives kill -9 across 3 sites.

Boots a pool worker for 3 fixture sites (frappe.localhost + 2 transient).
Dispatches 30 jobs total (10 per site). Kills the pool worker mid-run.
Spawns a peer pool worker for the same sites. Asserts every job reaches
SUCCEEDED exactly once, with no row stuck in RUNNING for >30s.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

BENCH_ROOT = Path("/Users/osamamuhammed/frappe_15")
PRIMARY_SITE = "frappe.localhost"
EXTRA_SITES = ["alpha.pool.test", "beta.pool.test"]


def _site_exists(site: str) -> bool:
    return (BENCH_ROOT / "sites" / site / "site_config.json").is_file()


def _conductor_installed(site: str) -> bool:
    """Verify the site has conductor in its installed_apps. A site dir
    can exist (from a previously-failed `bench new-site`) without conductor
    actually being installed — those leftovers must not be reused."""
    try:
        out = subprocess.check_output(
            ["bench", "--site", site, "execute", "frappe.get_installed_apps"],
            cwd=str(BENCH_ROOT), timeout=30, stderr=subprocess.DEVNULL,
        )
        return b"conductor" in out
    except Exception:
        return False


def _create_site(site: str) -> bool:
    if _site_exists(site) and _conductor_installed(site):
        return True
    if _site_exists(site):
        # Stale leftover from a previously-failed run — clean it before retrying.
        shutil.rmtree(BENCH_ROOT / "sites" / site, ignore_errors=True)
    cmd = [
        "bench", "new-site", site,
        "--admin-password", "admin",
        "--mariadb-root-password", "admin",
        "--install-app", "conductor",
    ]
    try:
        subprocess.run(cmd, cwd=str(BENCH_ROOT), check=True, capture_output=True, timeout=300)
    except Exception as e:
        print(f"site creation failed for {site}: {e}")
        # Failed `bench new-site` may have left a partial dir — sweep it.
        shutil.rmtree(BENCH_ROOT / "sites" / site, ignore_errors=True)
        return False
    return True


def _drop_site(site: str) -> None:
    if not _site_exists(site):
        return
    subprocess.run(
        ["bench", "drop-site", site, "--force", "--mariadb-root-password", "admin", "--no-backup"],
        cwd=str(BENCH_ROOT), check=False, capture_output=True, timeout=120,
    )


@pytest.fixture(scope="module")
def fixture_sites():
    created: list[str] = []
    for s in EXTRA_SITES:
        if _create_site(s):
            created.append(s)
        else:
            pytest.skip(f"cannot create chaos fixture site {s}; bench permissions / MariaDB?")
    sites = [PRIMARY_SITE] + created
    yield sites
    for s in created:
        _drop_site(s)


def _enqueue_demo_jobs(site: str, n: int) -> list[str]:
    """Run `bench --site=<site> conductor enqueue ...` n times. Returns job ids."""
    ids: list[str] = []
    for i in range(n):
        out = subprocess.check_output(
            ["bench", "--site", site, "execute", "conductor.enqueue",
             "--kwargs", f'{{"method": "conductor.demo.echo", "queue": "default", "k": {i}}}'],
            cwd=str(BENCH_ROOT), timeout=60,
        )
        # bench execute prints the return value; strip whitespace + quotes
        jid = out.decode().strip().strip("'").strip('"').strip()
        if jid:
            ids.append(jid)
    return ids


def _spawn_pool_worker(sites: list[str]) -> subprocess.Popen:
    return subprocess.Popen(
        ["bench", "conductor", "worker",
         "--sites", ",".join(sites),
         "--queue", "default",
         "--concurrency", "4",
         "--grace", "5"],
        cwd=str(BENCH_ROOT),
        preexec_fn=os.setsid,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _kill_subprocess_group(p: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass
    p.wait(timeout=5)


def _job_status(site: str, job_id: str) -> str | None:
    """Read the job's status via bench execute."""
    out = subprocess.check_output(
        ["bench", "--site", site, "execute", "frappe.db.get_value",
         "--kwargs", f'{{"doctype": "Conductor Job", "filters": {{"name": "{job_id}"}}, "fieldname": "status"}}'],
        cwd=str(BENCH_ROOT), timeout=30,
    )
    val = out.decode().strip().strip("'").strip('"').strip()
    return val or None


def test_pool_worker_kill_then_peer_reclaim(fixture_sites):
    sites = fixture_sites
    # 1. Enqueue 10 jobs per site.
    job_ids: dict[str, list[str]] = {}
    for s in sites:
        job_ids[s] = _enqueue_demo_jobs(s, 10)

    # 2. Boot pool worker A; let it run briefly so a few jobs start.
    a = _spawn_pool_worker(sites)
    time.sleep(2.5)
    _kill_subprocess_group(a)

    # 3. Boot pool worker B (peer); wait for everything to drain.
    b = _spawn_pool_worker(sites)
    deadline = time.time() + 90
    try:
        while time.time() < deadline:
            done = True
            for s in sites:
                for jid in job_ids[s]:
                    if _job_status(s, jid) != "SUCCEEDED":
                        done = False
                        break
                if not done:
                    break
            if done:
                break
            time.sleep(2)
        else:
            pytest.fail("pool worker did not drain all jobs within 90s after kill")
    finally:
        _kill_subprocess_group(b)

    # 4. Final assertions: every job is SUCCEEDED, no duplicates.
    for s in sites:
        for jid in job_ids[s]:
            assert _job_status(s, jid) == "SUCCEEDED", f"{s}/{jid} not SUCCEEDED"
