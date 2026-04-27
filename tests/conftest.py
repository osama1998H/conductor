"""Shared pytest fixtures for Conductor pure-Python tests (no Frappe site needed)."""

import pytest
import fakeredis


@pytest.fixture
def fake_redis():
    """A fakeredis instance with Stream support, fresh per test."""
    return fakeredis.FakeStrictRedis(server=fakeredis.FakeServer(), decode_responses=False)
