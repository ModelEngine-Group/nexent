# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared, byte-bounded query state with atomic LRU eviction and fixed entry lifetimes."""

import json

from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

# isort: split
from contracts.errors.trajectory import QueryError

# All keys use the same Redis Cluster hash tag. Expiration belongs to each entry;
# refreshing the namespace lifetime never extends an existing reference's lifetime.
_CACHE = """
local op, member = ARGV[1], ARGV[2]
local ttl, budget = tonumber(ARGV[3]), tonumber(ARGV[4])
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local used = tonumber(redis.call('GET', KEYS[5]) or '0')
local function drop(key)
    used = math.max(0, used - tonumber(redis.call('HGET', KEYS[2], key) or '0'))
    redis.call('HDEL', KEYS[1], key)
    redis.call('HDEL', KEYS[2], key)
    redis.call('HDEL', KEYS[3], key)
    redis.call('ZREM', KEYS[4], key)
end
local function touch(key)
    redis.call('ZADD', KEYS[4], redis.call('INCR', KEYS[6]), key)
end
local result = false
if op == 'put' then
    local size = tonumber(ARGV[5])
    if size > budget then return 0 end
    drop(member)
    redis.call('HSET', KEYS[1], member, ARGV[6])
    redis.call('HSET', KEYS[2], member, size)
    redis.call('HSET', KEYS[3], member, now + ttl)
    used = used + size
    touch(member)
    while used > budget do
        local oldest = redis.call('ZRANGE', KEYS[4], 0, 0)[1]
        if not oldest then break end
        drop(oldest)
    end
    result = 1
else
    local expires = tonumber(redis.call('HGET', KEYS[3], member) or '0')
    if expires <= now then
        drop(member)
    else
        result = redis.call('HGET', KEYS[1], member)
        touch(member)
    end
end
redis.call('SET', KEYS[5], used)
for _, key in ipairs(KEYS) do redis.call('EXPIRE', key, ttl) end
return result
"""


class RedisByteCache:
    """Preserve ByteCache's get/put contract across operations service processes."""

    def __init__(self, client, *, namespace, max_bytes=16 * 1024 * 1024, ttl=1800):
        self.client, self.max_bytes, self.ttl = client, max_bytes, ttl
        prefix = "nexent:trajectory:{v1:" + namespace + "}:"
        self.keys = [
            prefix + name
            for name in ("values", "sizes", "expires", "lru", "bytes", "sequence")
        ]

    def _call(self, operation, key, *args):
        try:
            return self.client.eval(
                _CACHE,
                len(self.keys),
                *self.keys,
                operation,
                key,
                self.ttl,
                self.max_bytes,
                *args,
            )
        except RedisError as error:
            raise QueryError(
                "trajectory_cache_unavailable", 503, retry_after=2
            ) from error

    def put(self, key, value, size):
        if size > self.max_bytes:
            return False
        raw = json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        return bool(self._call("put", key, size, raw))

    def get(self, key):
        raw = self._call("get", key)
        return json.loads(raw) if raw is not None else None


def shared_caches(url):
    """Use deployment configuration supplied by the caller; never fall back locally."""
    if not url:
        raise QueryError("trajectory_cache_unavailable", 503, retry_after=2)
    try:
        client = Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            max_connections=50,
            retry=Retry(NoBackoff(), 0),
        )
    except ValueError as error:
        raise QueryError("trajectory_configuration_invalid", 503) from error
    return (
        client,
        RedisByteCache(client, namespace="references"),
        RedisByteCache(client, namespace="queries"),
    )
