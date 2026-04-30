-- take_token: atomic refill bucket.
-- KEYS[1] = "conductor:{site}:rate:{queue}"
-- ARGV    = max_tokens, refill_per_sec, now_ms, n
-- returns: {allowed (0|1), retry_after_ms}

local max_tokens     = tonumber(ARGV[1])
local refill_per_sec = tonumber(ARGV[2])
local now_ms         = tonumber(ARGV[3])
local n              = tonumber(ARGV[4])

local state    = redis.call("HMGET", KEYS[1], "tokens", "last_refill_ms")
local tokens   = tonumber(state[1])
local last_ms  = tonumber(state[2])

-- First call (key missing): start full.
if tokens == nil then
    tokens  = max_tokens
    last_ms = now_ms
end

local elapsed_ms = now_ms - last_ms
if elapsed_ms < 0 then elapsed_ms = 0 end

local refill = (elapsed_ms * refill_per_sec) / 1000.0
tokens = tokens + refill
if tokens > max_tokens then tokens = max_tokens end

if tokens >= n then
    tokens = tokens - n
    redis.call("HMSET", KEYS[1], "tokens", tostring(tokens), "last_refill_ms", tostring(now_ms))
    redis.call("PEXPIRE", KEYS[1], 60000)
    return {1, 0}
else
    local missing  = n - tokens
    local retry_ms = math.ceil((missing * 1000.0) / refill_per_sec)
    redis.call("HMSET", KEYS[1], "tokens", tostring(tokens), "last_refill_ms", tostring(now_ms))
    redis.call("PEXPIRE", KEYS[1], 60000)
    return {0, retry_ms}
end
