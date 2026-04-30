"""Tests for the in-process frappe.enqueue patch.

The v1 frappe_compat shim only catches HTTP /api/method/frappe.enqueue calls.
v2 adds a Python-level patch so that intra-process frappe.enqueue() — used by
bench schedule and by application code that calls frappe.enqueue directly — is
also routed through conductor.enqueue when the bench-wide flag is set.

Activation rules:
- Bench flag `conductor_intercept_frappe_enqueue=True` in common_site_config.json
  turns the patch ON for the whole process.
- The patched function checks at call time whether the current site has
  conductor installed; if not, it falls back to the original frappe.enqueue.
- The patch is idempotent (installing twice is a no-op).
- The patch records the original function so it can be uninstalled in tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from conductor import frappe_compat


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


def test_patched_call_routes_to_conductor_when_site_has_conductor():
    """When the current site has conductor installed, the patch diverts."""
    fake_frappe = MagicMock()
    fake_frappe.local.site = "alpha"
    fake_frappe.enqueue = MagicMock(return_value="rq-job-id")

    with patch.object(frappe_compat, "_frappe_module", fake_frappe), \
         patch.object(frappe_compat, "_site_has_conductor", return_value=True), \
         patch.object(frappe_compat, "_conductor_enqueue", return_value="cnd-1") as cnd:
        frappe_compat.install_inprocess_patch()
        result = fake_frappe.enqueue("foo.bar", queue="default", x=1)

    assert result == "cnd-1"
    cnd.assert_called_once_with("foo.bar", queue="default", x=1)


def test_patched_call_falls_back_when_site_lacks_conductor():
    """When the current site does NOT have conductor, the patch falls back to the original."""
    fake_frappe = MagicMock()
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
    """If conductor cannot be imported at call time, fall back to original."""
    fake_frappe = MagicMock()
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
    """Conductor dispatch errors propagate — they do NOT silently fall back."""
    fake_frappe = MagicMock()
    fake_frappe.local.site = "alpha"
    fake_frappe.enqueue = MagicMock(return_value="rq-job-id")

    with patch.object(frappe_compat, "_frappe_module", fake_frappe), \
         patch.object(frappe_compat, "_site_has_conductor", return_value=True), \
         patch.object(frappe_compat, "_conductor_enqueue", side_effect=RuntimeError("redis down")):
        frappe_compat.install_inprocess_patch()
        with pytest.raises(RuntimeError, match="redis down"):
            fake_frappe.enqueue("foo.bar")


def test_patched_call_forwards_timeout_and_arbitrary_kwargs_on_divert():
    """The patched function passes timeout and arbitrary kwargs through to conductor."""
    fake_frappe = MagicMock()
    fake_frappe.local.site = "alpha"
    fake_frappe.enqueue = MagicMock(return_value="rq-job-id")

    with patch.object(frappe_compat, "_frappe_module", fake_frappe), \
         patch.object(frappe_compat, "_site_has_conductor", return_value=True), \
         patch.object(frappe_compat, "_conductor_enqueue", return_value="cnd-1") as cnd:
        frappe_compat.install_inprocess_patch()
        fake_frappe.enqueue("foo.bar", queue="q", timeout=600, job_name="x", arg1=1)

    cnd.assert_called_once_with("foo.bar", queue="q", timeout=600, job_name="x", arg1=1)


def test_patched_call_forwards_timeout_and_arbitrary_kwargs_on_fallback():
    """The patched function passes timeout and arbitrary kwargs through to the original on fallback."""
    fake_frappe = MagicMock()
    fake_frappe.local.site = "beta"
    original = MagicMock(return_value="rq-job-id")
    fake_frappe.enqueue = original

    with patch.object(frappe_compat, "_frappe_module", fake_frappe), \
         patch.object(frappe_compat, "_site_has_conductor", return_value=False):
        frappe_compat.install_inprocess_patch()
        fake_frappe.enqueue("foo.bar", queue="q", timeout=600, job_name="x", arg1=1)

    original.assert_called_once_with("foo.bar", queue="q", timeout=600, job_name="x", arg1=1)


def test_site_has_conductor_returns_false_when_no_current_site():
    """_site_has_conductor returns False when frappe has no site bound."""
    fake_frappe = MagicMock()
    fake_frappe.local.site = None

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        assert frappe_compat._site_has_conductor() is False


def test_site_has_conductor_returns_false_when_get_installed_apps_raises():
    """_site_has_conductor swallows exceptions and returns False so the patch can fall back safely."""
    fake_frappe = MagicMock()
    fake_frappe.local.site = "alpha"
    fake_frappe.get_installed_apps = MagicMock(side_effect=RuntimeError("db not connected"))

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        assert frappe_compat._site_has_conductor() is False


def test_site_has_conductor_returns_true_when_app_installed():
    """_site_has_conductor returns True when the current site has conductor in get_installed_apps()."""
    fake_frappe = MagicMock()
    fake_frappe.local.site = "alpha"
    fake_frappe.get_installed_apps = MagicMock(return_value=["frappe", "conductor", "erpnext"])

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        assert frappe_compat._site_has_conductor() is True


def test_site_has_conductor_returns_false_when_app_not_installed():
    """_site_has_conductor returns False when the current site exists but conductor is not in get_installed_apps()."""
    fake_frappe = MagicMock()
    fake_frappe.local.site = "alpha"
    fake_frappe.get_installed_apps = MagicMock(return_value=["frappe", "erpnext"])

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        assert frappe_compat._site_has_conductor() is False


def test_bootstrap_skips_when_flag_unset():
    """maybe_install_inprocess_patch with no flag in frappe.conf does not patch frappe.enqueue."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {}
    original = MagicMock()
    fake_frappe.enqueue = original

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        frappe_compat.maybe_install_inprocess_patch()

    assert fake_frappe.enqueue is original


def test_bootstrap_installs_when_flag_set():
    """maybe_install_inprocess_patch with the flag set installs the patch."""
    fake_frappe = MagicMock()
    fake_frappe.conf = {"conductor_intercept_frappe_enqueue": True}
    original = MagicMock()
    fake_frappe.enqueue = original

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        frappe_compat.maybe_install_inprocess_patch()
        assert getattr(fake_frappe.enqueue, frappe_compat._PATCH_MARKER, False)
        # Clean up so other tests are unaffected — uninstall against the same seam.
        frappe_compat.uninstall_inprocess_patch()


def test_bootstrap_swallows_exceptions_silently():
    """If the conf check itself raises, the bootstrap does not propagate."""
    fake_frappe = MagicMock()
    type(fake_frappe).conf = property(lambda self: (_ for _ in ()).throw(RuntimeError("kaboom")))
    original = MagicMock()
    fake_frappe.enqueue = original

    with patch.object(frappe_compat, "_frappe_module", fake_frappe):
        # Must not raise.
        frappe_compat.maybe_install_inprocess_patch()

    assert fake_frappe.enqueue is original
