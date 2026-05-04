"""Tests for the in-process frappe.enqueue patch.

The v1 frappe_compat shim only catches HTTP /api/method/frappe.enqueue calls.
v2 adds a Python-level patch so that intra-process frappe.enqueue() — used by
bench schedule and by application code that calls frappe.enqueue directly — is
also routed through conductor.enqueue when both:
  - the bench-wide flag `conductor_intercept_frappe_enqueue` is True in
    common_site_config.json (read at call time from frappe.conf), AND
  - the current site has conductor installed.

The bootstrap installs the patch UNCONDITIONALLY at conductor import time —
the flag is checked at every call. This is required because conductor is
typically imported during Frappe's app discovery, before `frappe.init()`
populates `frappe.conf`. Reading the flag at install time would silently see
an empty conf and the patch would never activate.

When the flag is unset, the patched function transparently calls the original
frappe.enqueue — zero behavior change for users who haven't enabled v2 routing.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from conductor import frappe_compat


# ---------------------------------------------------------------------------
# Install / uninstall mechanics
# ---------------------------------------------------------------------------


def test_install_is_idempotent():
    """Calling install_inprocess_patch twice does not double-wrap."""
    fake_frappe = MagicMock()
    original = MagicMock(return_value="rq-job-id")
    fake_frappe.enqueue = original

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        frappe_compat.install_inprocess_patch()
        first = fake_frappe.enqueue
        frappe_compat.install_inprocess_patch()
        second = fake_frappe.enqueue
        assert first is second, "install_inprocess_patch must be idempotent"


def test_uninstall_restores_original():
    """uninstall_inprocess_patch restores the pre-patch frappe.enqueue."""
    fake_frappe = MagicMock()
    original = MagicMock(return_value="rq-job-id")
    fake_frappe.enqueue = original

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        frappe_compat.install_inprocess_patch()
        assert fake_frappe.enqueue is not original
        frappe_compat.uninstall_inprocess_patch()
        assert fake_frappe.enqueue is original


# ---------------------------------------------------------------------------
# _intercept_enabled (the bench-wide flag check)
# ---------------------------------------------------------------------------


def test_intercept_enabled_returns_false_when_no_flag():
    """No flag → intercept disabled."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {}

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        assert frappe_compat._intercept_enabled() is False


def test_intercept_enabled_returns_true_when_flag_set():
    """Flag set to True → intercept enabled."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {"conductor_intercept_frappe_enqueue": True}

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        assert frappe_compat._intercept_enabled() is True


def test_intercept_enabled_returns_false_when_conf_access_raises():
    """Pathological frappe state must not crash producers."""
    fake_frappe = MagicMock()
    type(fake_frappe).conf = property(
        lambda self: (_ for _ in ()).throw(RuntimeError("conf gone"))
    )

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        assert frappe_compat._intercept_enabled() is False


# ---------------------------------------------------------------------------
# _site_has_conductor branches
# ---------------------------------------------------------------------------


def test_site_has_conductor_returns_false_when_no_current_site():
    fake_frappe = MagicMock()
    fake_frappe.local.site = None

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        assert frappe_compat._site_has_conductor() is False


def test_site_has_conductor_returns_false_when_get_installed_apps_raises():
    fake_frappe = MagicMock()
    fake_frappe.local.site = "alpha"
    fake_frappe.get_installed_apps = MagicMock(side_effect=RuntimeError("db not connected"))

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        assert frappe_compat._site_has_conductor() is False


def test_site_has_conductor_returns_true_when_app_installed():
    fake_frappe = MagicMock()
    fake_frappe.local.site = "alpha"
    fake_frappe.get_installed_apps = MagicMock(return_value=["frappe", "conductor", "erpnext"])

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        assert frappe_compat._site_has_conductor() is True


def test_site_has_conductor_returns_false_when_app_not_installed():
    fake_frappe = MagicMock()
    fake_frappe.local.site = "alpha"
    fake_frappe.get_installed_apps = MagicMock(return_value=["frappe", "erpnext"])

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        assert frappe_compat._site_has_conductor() is False


# ---------------------------------------------------------------------------
# Patched-enqueue routing — flag=True path
# ---------------------------------------------------------------------------


def test_patched_call_routes_to_conductor_when_flag_and_site_have_conductor():
    """Flag set + site has conductor → call diverts to conductor.enqueue."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {"conductor_intercept_frappe_enqueue": True}
    fake_frappe.local.site = "alpha"
    fake_frappe.enqueue = MagicMock()

    with patch.object(frappe_compat, "_frappe_module", fake_frappe), \
         patch.object(frappe_compat, "_site_has_conductor", return_value=True), \
         patch.object(frappe_compat, "_conductor_enqueue", return_value="cnd-1") as cnd:
        frappe_compat.install_inprocess_patch()
        result = fake_frappe.enqueue("foo.bar", queue="default", x=1)

    assert result == "cnd-1"
    cnd.assert_called_once_with("foo.bar", queue="default", x=1)


def test_patched_call_falls_back_when_site_lacks_conductor():
    """Flag set but site lacks conductor → call original frappe.enqueue."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {"conductor_intercept_frappe_enqueue": True}
    fake_frappe.local.site = "beta"
    original = MagicMock(return_value="rq-job-id")
    fake_frappe.enqueue = original

    with patch.object(frappe_compat, "_frappe_module", fake_frappe), \
         patch.object(frappe_compat, "_site_has_conductor", return_value=False):
        frappe_compat.install_inprocess_patch()
        result = fake_frappe.enqueue("foo.bar", queue="default", x=1)

    assert result == "rq-job-id"
    original.assert_called_once_with("foo.bar", queue="default", x=1)


def test_patched_call_falls_back_when_conductor_raises_importerror():
    """If conductor's dispatcher cannot be imported at call time, fall back."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {"conductor_intercept_frappe_enqueue": True}
    fake_frappe.local.site = "alpha"
    original = MagicMock(return_value="rq-job-id")
    fake_frappe.enqueue = original

    with patch.object(frappe_compat, "_frappe_module", fake_frappe), \
         patch.object(frappe_compat, "_site_has_conductor", return_value=True), \
         patch.object(frappe_compat, "_conductor_enqueue", side_effect=ImportError):
        frappe_compat.install_inprocess_patch()
        result = fake_frappe.enqueue("foo.bar", queue="default")

    assert result == "rq-job-id"
    original.assert_called_once_with("foo.bar", queue="default")


def test_patched_call_signals_dispatch_failure_loudly():
    """Conductor dispatch errors propagate — no silent fallback for arbitrary errors."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {"conductor_intercept_frappe_enqueue": True}
    fake_frappe.local.site = "alpha"
    fake_frappe.enqueue = MagicMock()

    with patch.object(frappe_compat, "_frappe_module", fake_frappe), \
         patch.object(frappe_compat, "_site_has_conductor", return_value=True), \
         patch.object(frappe_compat, "_conductor_enqueue", side_effect=RuntimeError("redis down")):
        frappe_compat.install_inprocess_patch()
        with pytest.raises(RuntimeError, match="redis down"):
            fake_frappe.enqueue("foo.bar")


def test_patched_call_forwards_timeout_and_arbitrary_kwargs_on_divert():
    """timeout and arbitrary kwargs reach conductor.enqueue verbatim."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {"conductor_intercept_frappe_enqueue": True}
    fake_frappe.local.site = "alpha"
    fake_frappe.enqueue = MagicMock()

    with patch.object(frappe_compat, "_frappe_module", fake_frappe), \
         patch.object(frappe_compat, "_site_has_conductor", return_value=True), \
         patch.object(frappe_compat, "_conductor_enqueue", return_value="cnd-1") as cnd:
        frappe_compat.install_inprocess_patch()
        fake_frappe.enqueue("foo.bar", queue="q", timeout=600, job_name="x", arg1=1)

    cnd.assert_called_once_with("foo.bar", queue="q", timeout=600, job_name="x", arg1=1)


def test_patched_call_forwards_timeout_and_arbitrary_kwargs_on_fallback():
    """timeout and arbitrary kwargs reach the original frappe.enqueue verbatim."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {"conductor_intercept_frappe_enqueue": True}
    fake_frappe.local.site = "beta"
    original = MagicMock(return_value="rq-job-id")
    fake_frappe.enqueue = original

    with patch.object(frappe_compat, "_frappe_module", fake_frappe), \
         patch.object(frappe_compat, "_site_has_conductor", return_value=False):
        frappe_compat.install_inprocess_patch()
        fake_frappe.enqueue("foo.bar", queue="q", timeout=600, job_name="x", arg1=1)

    original.assert_called_once_with("foo.bar", queue="q", timeout=600, job_name="x", arg1=1)


# ---------------------------------------------------------------------------
# Patched-enqueue routing — flag unset (transparent fallback)
# ---------------------------------------------------------------------------


def test_patched_call_falls_back_when_flag_unset():
    """No flag → call original frappe.enqueue. Critical: zero behavior change for users who haven't opted in."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {}
    fake_frappe.local.site = "alpha"
    original = MagicMock(return_value="rq-job-id")
    fake_frappe.enqueue = original

    with patch.object(frappe_compat, "_frappe_module", fake_frappe), \
         patch.object(frappe_compat, "_site_has_conductor", return_value=True), \
         patch.object(frappe_compat, "_conductor_enqueue", return_value="cnd-1") as cnd:
        frappe_compat.install_inprocess_patch()
        result = fake_frappe.enqueue("foo.bar", queue="default", x=1)

    assert result == "rq-job-id"
    original.assert_called_once_with("foo.bar", queue="default", x=1)
    cnd.assert_not_called()


def test_patched_call_falls_back_when_conf_access_raises():
    """If frappe.conf access raises at call time, fall back to original — must not crash producers."""
    fake_frappe = MagicMock()
    type(fake_frappe).conf = property(
        lambda self: (_ for _ in ()).throw(RuntimeError("conf gone"))
    )
    fake_frappe.local.site = "alpha"
    original = MagicMock(return_value="rq-job-id")
    fake_frappe.enqueue = original

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        frappe_compat.install_inprocess_patch()
        result = fake_frappe.enqueue("foo.bar", queue="default")

    assert result == "rq-job-id"
    original.assert_called_once_with("foo.bar", queue="default")


# ---------------------------------------------------------------------------
# Bootstrap (now unconditional install)
# ---------------------------------------------------------------------------


def test_bootstrap_installs_unconditionally_when_flag_unset():
    """Bootstrap installs the patch even when the flag is unset.

    The patched function is responsible for the per-call flag check, not the
    bootstrap. This makes the patch resilient to import-order timing where
    conductor loads before `frappe.init()` populates `frappe.conf`.
    """
    fake_frappe = MagicMock()
    fake_frappe.conf = {}
    original = MagicMock()
    fake_frappe.enqueue = original

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        frappe_compat.maybe_install_inprocess_patch()
        assert getattr(fake_frappe.enqueue, frappe_compat._PATCH_MARKER, False)
        frappe_compat.uninstall_inprocess_patch()


def test_bootstrap_installs_unconditionally_when_flag_set():
    fake_frappe = MagicMock()
    fake_frappe.conf = {"conductor_intercept_frappe_enqueue": True}
    original = MagicMock()
    fake_frappe.enqueue = original

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        frappe_compat.maybe_install_inprocess_patch()
        assert getattr(fake_frappe.enqueue, frappe_compat._PATCH_MARKER, False)
        frappe_compat.uninstall_inprocess_patch()


def test_bootstrap_swallows_install_failure_silently():
    """If install_inprocess_patch raises, maybe_install_inprocess_patch does not propagate."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {"conductor_intercept_frappe_enqueue": True}
    original = MagicMock()
    fake_frappe.enqueue = original

    with patch.object(frappe_compat, "_frappe_module", fake_frappe), \
         patch.object(frappe_compat, "install_inprocess_patch", side_effect=RuntimeError("kaboom")):
        frappe_compat.maybe_install_inprocess_patch()

    assert fake_frappe.enqueue is original


def test_bootstrap_logs_warning_on_install_failure():
    """When install_inprocess_patch raises, the bootstrap routes the failure through frappe.logger."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {"conductor_intercept_frappe_enqueue": True}
    fake_frappe.enqueue = MagicMock()

    with patch.object(frappe_compat, "_frappe_module", fake_frappe), \
         patch.object(frappe_compat, "install_inprocess_patch", side_effect=RuntimeError("kaboom")):
        frappe_compat.maybe_install_inprocess_patch()

    fake_frappe.logger.assert_called_with("conductor")
    fake_frappe.logger.return_value.warning.assert_called_once()
