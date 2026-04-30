"""fanin_decrement Lua script tests against fakeredis."""

import json

from conductor.workflow.keys import wfdeps_key
from conductor.workflow.lua import FANIN_DECREMENT


def _seed(fake_redis, site, run_id, deps: dict[str, int]):
    key = wfdeps_key(site, run_id)
    if deps:
        fake_redis.hset(key, mapping={k: str(v) for k, v in deps.items()})


def _run(fake_redis, site, run_id, completed, downstreams):
    key = wfdeps_key(site, run_id)
    return fake_redis.eval(
        FANIN_DECREMENT, 1, key, completed or "", json.dumps(downstreams)
    )


def test_first_call_returns_roots(fake_redis):
    _seed(fake_redis, "s", "r1", {"a": 0, "b": 1, "c": 1, "d": 2})
    ready = _run(fake_redis, "s", "r1", completed=None, downstreams=[])
    assert sorted([x.decode() if isinstance(x, bytes) else x for x in ready]) == ["a"]


def test_decrement_releases_one_downstream(fake_redis):
    _seed(fake_redis, "s", "r1", {"a": 0, "b": 1, "c": 1, "d": 2})
    ready = _run(fake_redis, "s", "r1", completed="a", downstreams=["b", "c"])
    names = sorted([x.decode() if isinstance(x, bytes) else x for x in ready])
    assert names == ["b", "c"]
    assert int(fake_redis.hget(wfdeps_key("s", "r1"), "d")) == 2


def test_two_siblings_finish_then_d_unblocks(fake_redis):
    _seed(fake_redis, "s", "r1", {"a": 0, "b": 1, "c": 1, "d": 2})
    _run(fake_redis, "s", "r1", completed="a", downstreams=["b", "c"])
    ready1 = _run(fake_redis, "s", "r1", completed="b", downstreams=["d"])
    assert ready1 == []
    ready2 = _run(fake_redis, "s", "r1", completed="c", downstreams=["d"])
    names = [x.decode() if isinstance(x, bytes) else x for x in ready2]
    assert names == ["d"]


def test_double_decrement_is_idempotent_no_extra_dispatch(fake_redis):
    """A re-fired advancer for the same completion shouldn't re-emit the same step."""
    _seed(fake_redis, "s", "r1", {"a": 0, "b": 1})
    _run(fake_redis, "s", "r1", completed="a", downstreams=["b"])
    ready = _run(fake_redis, "s", "r1", completed="a", downstreams=["b"])
    names = [x.decode() if isinstance(x, bytes) else x for x in ready]
    assert names == ["b"]
