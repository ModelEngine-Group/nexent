# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Atomic checkpoint updates shared by the two Redis stream protocols."""

import json


APPEND_COMPACT_REPLAY = """
    if ARGV[1] ~= '' and redis.call('HGET', KEYS[1], 'generation') ~= ARGV[1] then return false end
    if ARGV[8] ~= '' then
        local previous = tonumber(redis.call('HGET', KEYS[3], 'sequence') or '0')
        if previous + 1 ~= tonumber(ARGV[8]) then
            redis.call('HSET', KEYS[1], 'replay_incomplete', '1')
            return false
        end
    end
    local payload = cjson.decode(ARGV[6])
    local field = 'part:' .. ARGV[5]
    if ARGV[7] == '1' then
        local old = redis.call('HGET', KEYS[3], field)
        if not old then return redis.error_reply('Replay checkpoint prefix missing') end
        old = cjson.decode(old)
        payload.content = old.content .. payload.content
    end
    local id = redis.call('XADD', KEYS[2], 'MAXLEN', '~', ARGV[2], '*', 'chunk', ARGV[3])
    redis.call('HSET', KEYS[3], field, cjson.encode(payload), 'cursor', id,
        'count', tonumber(ARGV[5]) + 1, 'generation', ARGV[1])
    if ARGV[8] ~= '' then redis.call('HSET', KEYS[3], 'sequence', ARGV[8]) end
    redis.call('EXPIRE', KEYS[2], ARGV[4])
    redis.call('EXPIRE', KEYS[3], ARGV[4])
    return id
"""


def compact_replay_args(update):
    return (
        update["slot"], json.dumps(update["payload"], ensure_ascii=False),
        "1" if update["append"] else "0", str(update.get("sequence", "")),
    )


def decode_replay_checkpoint(data):
    if not data:
        return None
    return {
        "entries": [json.loads(data[f"part:{index}"]) for index in range(int(data["count"]))],
        "cursor": data["cursor"], "generation": data.get("generation", ""),
    }
