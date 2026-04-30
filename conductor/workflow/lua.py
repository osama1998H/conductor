"""Lua script for atomic fan-in deps decrement.

Single-key (KEYS[1] = wfdeps:{run_id}) per master §3 #15.

Semantics:
  - If ARGV[1] is empty: scan the hash, return all step ids whose value is "0".
  - Else: for each downstream id in JSON-decoded ARGV[2], HINCRBY -1.
    Collect those whose new value is <= 0. Return them.

Re-fires of the same completion are tolerated by the script (count goes
negative); the dispatcher side de-dupes via Step Run row state.
"""

FANIN_DECREMENT = """
local key = KEYS[1]
local completed = ARGV[1]
local downstreams_json = ARGV[2]
local ready = {}

if completed == nil or completed == '' then
  local all = redis.call('HGETALL', key)
  for i = 1, #all, 2 do
    if all[i + 1] == '0' then
      table.insert(ready, all[i])
    end
  end
  return ready
end

local downstreams = cjson.decode(downstreams_json)
for _, step in ipairs(downstreams) do
  local newval = redis.call('HINCRBY', key, step, -1)
  if newval <= 0 then
    table.insert(ready, step)
  end
end
return ready
"""
