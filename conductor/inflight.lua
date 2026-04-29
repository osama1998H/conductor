-- Inflight counter scripts for the concurrency cap.
--
-- This file holds three scripts; the Python wrapper splits on the
-- "-- @SCRIPT name" marker and registers each independently. Keeping all
-- three in one file makes the policy obvious to readers; splitting at
-- import time keeps each script single-key and EVAL-cacheable.

-- @SCRIPT acquire
-- KEYS[1] = inflight_key
-- ARGV    = max_concurrent
-- returns: {acquired (0|1), current_count}
local cur = tonumber(redis.call("GET", KEYS[1]) or "0")
local cap = tonumber(ARGV[1])
if cur < cap then
    local new = redis.call("INCR", KEYS[1])
    redis.call("EXPIRE", KEYS[1], 86400)
    return {1, new}
else
    return {0, cur}
end

-- @SCRIPT release
-- KEYS[1] = inflight_key
-- returns: new_count (always >= 0)
local new = redis.call("DECR", KEYS[1])
if new < 0 then
    redis.call("SET", KEYS[1], 0)
    return 0
end
return new

-- @SCRIPT correct_drift
-- KEYS[1] = inflight_key
-- ARGV    = decrement_by
-- returns: new_count (always >= 0)
local cur = tonumber(redis.call("GET", KEYS[1]) or "0")
local new = cur - tonumber(ARGV[1])
if new < 0 then new = 0 end
redis.call("SET", KEYS[1], new)
return new
