"""Auth gate for /conductor-dashboard.

Frappe runs `get_context()` for every request to a www/ page. We redirect
Guest users to the login page (with a redirect-back to the dashboard so
they land here after login). Authenticated users see the SPA shell.

Phase 3 spec §6 documented this as the page-level perm: "served to any
authenticated user; the SPA's first call is get_state and a 403 there
shows a 'no access' page". Adding this gate so we never even render the
shell for unauthenticated visitors.
"""

import frappe
from frappe.sessions import get_csrf_token

no_cache = 1


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/conductor-dashboard"
        raise frappe.Redirect
    # Inject csrf_token so the Jinja literal `{{ csrf_token }}` in
    # dashboard/index.html resolves to a usable value. The SPA reads
    # window.csrf_token to send X-Frappe-CSRF-Token on POST calls.
    context.csrf_token = get_csrf_token()
    return context
