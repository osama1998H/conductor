"""Unit tests for conductor.site_discovery.

Uses a tmpdir to simulate a Frappe sites_path with several site directories,
each with its own site_config.json. The function should return only the
sites that have 'conductor' in their installed_apps list.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from conductor.site_discovery import discover_installed_sites


def _make_site(sites_path: Path, name: str, *, installed_apps: list[str] | None) -> None:
    """Create sites_path/<name>/site_config.json. installed_apps=None means
    no site_config.json file at all (simulates a half-installed site)."""
    site_dir = sites_path / name
    site_dir.mkdir(parents=True)
    if installed_apps is not None:
        cfg = {"db_name": f"db_{name}", "db_password": "x"}
        (site_dir / "site_config.json").write_text(json.dumps(cfg))


@pytest.fixture
def sites_path(tmp_path):
    return tmp_path


def test_returns_empty_when_no_sites(sites_path):
    with patch("conductor.site_discovery._installed_apps_for_site", return_value=[]):
        out = discover_installed_sites(str(sites_path))
    assert out == []


def test_returns_only_sites_with_conductor_installed(sites_path):
    _make_site(sites_path, "alpha.test",   installed_apps=["frappe", "conductor"])
    _make_site(sites_path, "beta.test",    installed_apps=["frappe"])
    _make_site(sites_path, "gamma.test",   installed_apps=["frappe", "conductor"])

    fake_apps = {
        "alpha.test":  ["frappe", "conductor"],
        "beta.test":   ["frappe"],
        "gamma.test":  ["frappe", "conductor"],
    }
    with patch(
        "conductor.site_discovery._installed_apps_for_site",
        side_effect=lambda site, sp: fake_apps[site],
    ):
        out = discover_installed_sites(str(sites_path))
    assert out == ["alpha.test", "gamma.test"]  # sorted


def test_skips_directories_without_site_config_json(sites_path):
    _make_site(sites_path, "alpha.test", installed_apps=["frappe", "conductor"])
    _make_site(sites_path, "halfdone",   installed_apps=None)

    with patch(
        "conductor.site_discovery._installed_apps_for_site",
        side_effect=lambda site, sp: ["frappe", "conductor"] if site == "alpha.test" else [],
    ):
        out = discover_installed_sites(str(sites_path))
    assert out == ["alpha.test"]


def test_skips_well_known_non_site_directories(sites_path):
    # "assets" is a Frappe convention for built static files; never a site.
    (sites_path / "assets").mkdir()
    (sites_path / "common_site_config.json").write_text("{}")
    (sites_path / "apps.txt").write_text("frappe\nconductor\n")
    _make_site(sites_path, "alpha.test", installed_apps=["frappe", "conductor"])

    with patch(
        "conductor.site_discovery._installed_apps_for_site",
        return_value=["frappe", "conductor"],
    ):
        out = discover_installed_sites(str(sites_path))
    assert out == ["alpha.test"]


def test_init_failure_for_one_site_skips_that_site(sites_path):
    _make_site(sites_path, "alpha.test", installed_apps=["frappe", "conductor"])
    _make_site(sites_path, "broken.test", installed_apps=["frappe", "conductor"])

    def raise_for_broken(site, sp):
        if site == "broken.test":
            raise RuntimeError("fake init failure")
        return ["frappe", "conductor"]

    with patch("conductor.site_discovery._installed_apps_for_site",
               side_effect=raise_for_broken):
        out = discover_installed_sites(str(sites_path))
    assert out == ["alpha.test"]
