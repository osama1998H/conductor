"""Unit tests for conductor.config — reading site_config['conductor']."""

import pytest

from conductor.config import ConductorConfig, load_config


def test_load_config_from_dict_with_all_fields():
    site_config = {
        "redis_queue": "redis://127.0.0.1:11000",
        "conductor": {
            "redis_url": "redis://127.0.0.1:11000/2",
            "default_queue": "default",
            "stream_max_len": 5000,
        },
    }
    cfg = load_config(site_config)
    assert isinstance(cfg, ConductorConfig)
    assert cfg.redis_url == "redis://127.0.0.1:11000/2"
    assert cfg.default_queue == "default"
    assert cfg.stream_max_len == 5000


def test_load_config_falls_back_to_redis_queue_with_db_2():
    site_config = {"redis_queue": "redis://127.0.0.1:11000"}
    cfg = load_config(site_config)
    assert cfg.redis_url == "redis://127.0.0.1:11000/2"


def test_load_config_falls_back_to_redis_queue_when_url_already_has_db():
    site_config = {"redis_queue": "redis://127.0.0.1:11000/1"}
    cfg = load_config(site_config)
    # Override the DB component to 2 regardless of what redis_queue specified.
    assert cfg.redis_url.endswith("/2")


def test_load_config_default_queue_is_default():
    cfg = load_config({"redis_queue": "redis://127.0.0.1:11000"})
    assert cfg.default_queue == "default"


def test_load_config_stream_max_len_default():
    cfg = load_config({"redis_queue": "redis://127.0.0.1:11000"})
    assert cfg.stream_max_len == 10000


def test_load_config_raises_when_no_redis_anywhere():
    with pytest.raises(ValueError, match="redis_url"):
        load_config({})
