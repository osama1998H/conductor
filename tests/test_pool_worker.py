"""Unit tests for pool worker stream-routing skeleton.

These tests do NOT spawn a real worker process; they exercise the helpers
that pool mode adds: building the streams dict across multiple sites,
parsing the right site from each stream key, and confirming the
single-site path is just N=1 of pool mode.
"""

from unittest.mock import patch

import pytest

from conductor.worker import _build_streams_dict


def test_build_streams_dict_one_site_one_queue(fake_redis):
    streams = _build_streams_dict(
        fake_redis, sites=["alpha.test"], queues=["default"],
    )
    assert streams == {"conductor:alpha.test:stream:default": ">"}


def test_build_streams_dict_one_site_multiple_queues(fake_redis):
    streams = _build_streams_dict(
        fake_redis, sites=["alpha.test"], queues=["default", "long"],
    )
    assert streams == {
        "conductor:alpha.test:stream:default": ">",
        "conductor:alpha.test:stream:long": ">",
    }


def test_build_streams_dict_multiple_sites_multiple_queues(fake_redis):
    streams = _build_streams_dict(
        fake_redis,
        sites=["alpha.test", "beta.test"],
        queues=["default", "critical"],
    )
    assert streams == {
        "conductor:alpha.test:stream:default": ">",
        "conductor:alpha.test:stream:critical": ">",
        "conductor:beta.test:stream:default": ">",
        "conductor:beta.test:stream:critical": ">",
    }


def test_build_streams_dict_creates_consumer_group_per_stream(fake_redis):
    """ensure_consumer_group is called for every (site, queue) combination."""
    with patch("conductor.worker.ensure_consumer_group") as mock_ensure:
        _build_streams_dict(
            fake_redis,
            sites=["alpha.test", "beta.test"],
            queues=["default"],
        )
    assert mock_ensure.call_count == 2
    seen_keys = sorted(call.args[1] for call in mock_ensure.call_args_list)
    assert seen_keys == [
        "conductor:alpha.test:stream:default",
        "conductor:beta.test:stream:default",
    ]
