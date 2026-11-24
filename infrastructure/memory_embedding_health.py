# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Circuit breaker for the embedding configuration used by automatic memory."""

import hashlib
import json
import logging
import threading
import time
import uuid
from collections import OrderedDict
from functools import lru_cache

import redis

from infrastructure.memory_io import run_memory_io

from contracts.constants.environment import (
    MEMORY_EMBEDDING_COOLDOWN_SECONDS, REDIS_BACKEND_URL, RUNTIME_STATE_REDIS_URL,
)

logger = logging.getLogger(__name__)

_PROBE_SECONDS = 15
_MAX_LOCAL_CIRCUITS = 1024
_local_lock = threading.Lock()
_local: OrderedDict[str, tuple[float, float]] = OrderedDict()


@lru_cache(maxsize=1)
def _client():
    redis_url = REDIS_BACKEND_URL or RUNTIME_STATE_REDIS_URL
    if not redis_url:
        return None
    return redis.Redis.from_url(
        redis_url, socket_connect_timeout=0.15, socket_timeout=0.15,
        max_connections=16, retry_on_timeout=False,
    )


def embedding_circuit_key(tenant_id, info):
    identity = [tenant_id, info.model_id, info.revision, info.dimension]
    digest = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    return f"nexent:memory:embedding-health:{digest}"


def _admit_local(key):
    with _local_lock:
        state = _local.get(key)
        if state is None:
            return ""
        now = time.monotonic()
        cooldown_until, probe_until = state
        if now < max(cooldown_until, probe_until):
            return None
        _local[key] = (cooldown_until, now + _PROBE_SECONDS)
        return "local"


def admit_embedding(key, *, shared=True):
    """Return a probe token, an empty token for normal traffic, or None if open."""
    if not MEMORY_EMBEDDING_COOLDOWN_SECONDS:
        return ""
    if not shared:
        return _admit_local(key)
    with _local_lock:
        state = _local.get(key)
        if state is not None and time.monotonic() < state[0]:
            return None
    try:
        client = _client()
        if client is None:
            return _admit_local(key)
        open_until = client.get(key)
        if open_until is None:
            return ""
        if time.time() < float(open_until):
            return None
        token = uuid.uuid4().hex
        if client.set(f"{key}:probe", token, nx=True, ex=_PROBE_SECONDS):
            return token
        return None
    except (redis.RedisError, ValueError):
        return _admit_local(key)


def record_embedding_failure(key, *, shared=True):
    cooldown = MEMORY_EMBEDDING_COOLDOWN_SECONDS
    if not cooldown:
        return
    with _local_lock:
        _local[key] = (time.monotonic() + cooldown, 0)
        _local.move_to_end(key)
        if len(_local) > _MAX_LOCAL_CIRCUITS:
            _local.popitem(last=False)
    if not shared:
        return
    try:
        client = _client()
        if client is not None:
            client.set(key, str(time.time() + cooldown), ex=cooldown + _PROBE_SECONDS * 4)
    except redis.RedisError:
        logger.debug("event=memory_circuit_shared_unavailable")


def record_embedding_success(key, token, *, shared=True):
    if not token:
        return
    if shared and token != "local":
        try:
            client = _client()
            if client is not None:
                client.eval(
                    "if redis.call('get', KEYS[2]) == ARGV[1] then "
                    "redis.call('del', KEYS[1], KEYS[2]); return 1 else return 0 end",
                    2, key, f"{key}:probe", token,
                )
        except redis.RedisError:
            logger.debug("event=memory_circuit_shared_unavailable")
    with _local_lock:
        _local.pop(key, None)


async def run_embedding_health(operation, *args, deadline):
    """Bound shared health I/O on managed workers, falling back to local state."""
    try:
        return await run_memory_io(
            "memory-embedding-health", operation, *args,
            deadline=min(deadline, time.monotonic() + 0.2), lane="control-io",
        )
    except Exception:
        logger.debug("event=memory_circuit_shared_unavailable")
        return operation(*args, shared=False)
