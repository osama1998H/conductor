"""Drop-in shim with the same call signature as frappe.enqueue.

There are two layers here:

1. **HTTP shim** (v1).  Client apps opt in via:
       override_whitelisted_methods = {"frappe.enqueue": "conductor.frappe_compat.enqueue"}
   in their `hooks.py`. The override rewrites HTTP `/api/method/frappe.enqueue`
   calls so they land here.

2. **In-process patch** (v2).  `install_inprocess_patch()` runs on conductor
   import and replaces `frappe.enqueue` at the Python level unconditionally.
   The patched function checks the bench-wide flag
       conductor_intercept_frappe_enqueue: true
   from `frappe.conf` (built by Frappe from common_site_config.json + the
   active site's site_config.json) AT CALL TIME — not at install time. This
   is essential because conductor is typically imported during Frappe's app
   discovery, before `frappe.init()` populates `frappe.conf`. Reading the
   flag at install time would silently see an empty conf and never enable
   the patch.

   When the flag is unset, the patched function transparently calls the
   original `frappe.enqueue` — zero behavior change for users who haven't
   enabled v2 routing. When the flag is set AND the current site has
   conductor installed, the call diverts to `conductor.enqueue`.
"""

from __future__ import annotations

from typing import Any, Callable

import frappe

import conductor

# Module-level handles for testability — tests patch these to inject fakes.
_frappe_module = frappe
_conductor_enqueue: Callable[..., str] = conductor.enqueue

# Sentinel attribute set on the patched function so install is idempotent
# and uninstall can restore the original cleanly.
_PATCH_MARKER = "__conductor_inprocess_patch__"
_ORIGINAL_ATTR = "__conductor_original_enqueue__"


@frappe.whitelist()
def enqueue(method: str, queue: str = "default", timeout: int | None = None, **kwargs: Any) -> str:
    """frappe.enqueue-shaped wrapper around conductor.enqueue (HTTP shim entry)."""
    return conductor.enqueue(method, queue=queue, timeout=timeout, **kwargs)


def _intercept_enabled() -> bool:
    """True when the bench-wide flag is set right now."""
    try:
        conf = getattr(_frappe_module, "conf", None) or {}
        return bool(conf.get("conductor_intercept_frappe_enqueue", False))
    except Exception:
        return False


def _site_has_conductor() -> bool:
    """True when the currently-initialized Frappe site has conductor installed."""
    try:
        site = getattr(_frappe_module.local, "site", None)
        if not site:
            return False
        installed = _frappe_module.get_installed_apps()
        return "conductor" in installed
    except Exception:
        return False


def _make_patched_enqueue(original: Callable[..., Any]) -> Callable[..., Any]:
    """Build the replacement frappe.enqueue."""

    def patched(method: str, queue: str = "default", timeout: int | None = None, **kwargs: Any):
        # Build call arguments: only include timeout if it was explicitly provided (not None).
        call_kwargs = {"queue": queue, **kwargs}
        if timeout is not None:
            call_kwargs["timeout"] = timeout

        if not _intercept_enabled():
            return original(method, **call_kwargs)
        if not _site_has_conductor():
            return original(method, **call_kwargs)
        try:
            return _conductor_enqueue(method, **call_kwargs)
        except ImportError:
            return original(method, **call_kwargs)

    setattr(patched, _PATCH_MARKER, True)
    setattr(patched, _ORIGINAL_ATTR, original)
    return patched


def install_inprocess_patch() -> None:
    """Replace frappe.enqueue with a Conductor-aware version.

    Idempotent: a second call is a no-op. Tests may call uninstall_inprocess_patch()
    to restore the original.
    """
    current = getattr(_frappe_module, "enqueue", None)
    if current is None:
        return
    if getattr(current, _PATCH_MARKER, False):
        return
    _frappe_module.enqueue = _make_patched_enqueue(current)


def uninstall_inprocess_patch() -> None:
    """Restore the un-patched frappe.enqueue (test helper)."""
    current = getattr(_frappe_module, "enqueue", None)
    if current is None:
        return
    if not getattr(current, _PATCH_MARKER, False):
        return
    original = getattr(current, _ORIGINAL_ATTR, None)
    if original is not None:
        _frappe_module.enqueue = original


def maybe_install_inprocess_patch() -> None:
    """Install the in-process patch unconditionally on conductor import.

    Always-install + per-call flag check is the timing-robust pattern: if we
    only installed when the flag was set at import time, conductor's import
    during Frappe app discovery (which typically precedes `frappe.init()`)
    would see an empty `frappe.conf` and silently skip — leaving the patch
    permanently inactive even after the flag is set.

    By installing unconditionally and checking the flag inside the patched
    function, every later call sees the current `frappe.conf` and routes
    correctly. Calls when the flag is unset transparently fall through to
    the original `frappe.enqueue`.

    Failures here MUST NOT break import: the v1 HTTP shim still works
    without this bootstrap. Failures emit a best-effort warning via
    frappe.logger so operators have a breadcrumb.
    """
    try:
        install_inprocess_patch()
    except Exception as exc:
        try:
            _frappe_module.logger("conductor").warning(
                "conductor: bootstrap of in-process frappe.enqueue patch failed: %s",
                exc,
            )
        except Exception:
            pass
