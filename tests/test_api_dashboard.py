"""Unit tests for conductor.api.dashboard — whitelisted endpoints + perm guards.

Each endpoint MUST cover the matrix from spec §10.1:
  anonymous → 401, Operator allowed → 200, Operator denied destructive → 403,
  System Manager → 200.

These tests use Frappe's test fixtures + role assignment via _as_user(...).
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
import frappe

from conductor.api import dashboard


@contextmanager
def _as_roles(*roles):
    """Patch frappe.get_roles() and frappe.has_permission() to simulate the user."""
    with patch.object(frappe, "get_roles", return_value=list(roles)), \
         patch.object(frappe, "has_permission", return_value=("Conductor Operator" in roles or "System Manager" in roles)):
        yield


def test_require_read_allows_operator():
    with _as_roles("Conductor Operator"):
        dashboard._require_read()  # no raise


def test_require_read_allows_system_manager():
    with _as_roles("System Manager"):
        dashboard._require_read()


def test_require_read_rejects_anonymous():
    with _as_roles(), patch.object(frappe, "has_permission", return_value=False):
        with pytest.raises(frappe.PermissionError):
            dashboard._require_read()


def test_require_destructive_rejects_operator():
    with _as_roles("Conductor Operator"):
        with pytest.raises(frappe.PermissionError):
            dashboard._require_destructive()


def test_require_destructive_allows_system_manager():
    with _as_roles("System Manager"):
        dashboard._require_destructive()
