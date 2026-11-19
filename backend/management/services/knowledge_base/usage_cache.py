# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Process-local quota cache with no database or object-store import side effects."""

import asyncio
import threading
from concurrent.futures import Future
from contextlib import asynccontextmanager, contextmanager
from typing import Any

CACHE_TTL_SECONDS = 60

# In-memory cache for usage data
_usage_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_usage_refresh_locks = {}
_usage_cache_state_lock = threading.RLock()
_usage_cache_generation = 0


def _enqueue_refresh(tenant_id):
    ready = Future()
    with _usage_cache_state_lock:
        queue = _usage_refresh_locks.setdefault(tenant_id, [])
        queue.append(ready)
        if len(queue) == 1:
            ready.set_result(_usage_cache_generation)
    return ready


def _release_refresh(tenant_id, ready):
    """Remove queued or awarded ownership atomically on every exit path."""
    with _usage_cache_state_lock:
        queue = _usage_refresh_locks[tenant_id]
        was_owner = queue[0] is ready
        queue.remove(ready)
        if not was_owner:
            ready.cancel()
        if not queue:
            del _usage_refresh_locks[tenant_id]
        elif was_owner:
            queue[0].set_result(_usage_cache_generation)


@contextmanager
def usage_refresh_guard(tenant_id: str):
    """Share refresh ownership with async callers without thread affinity."""
    ready = _enqueue_refresh(tenant_id)
    try:
        yield ready.result()
    finally:
        _release_refresh(tenant_id, ready)


@asynccontextmanager
async def async_usage_refresh_guard(tenant_id: str):
    """Wait without occupying a worker; cancellation relinquishes the ticket."""
    ready = _enqueue_refresh(tenant_id)
    try:
        # Shield the shared Future so cancellation cannot corrupt handoff.
        yield await asyncio.shield(asyncio.wrap_future(ready))
    finally:
        _release_refresh(tenant_id, ready)


def store_usage_cache(tenant_id, timestamp, usage, generation):
    """Do not publish a refresh invalidated while external I/O was in flight."""
    with _usage_cache_state_lock:
        if generation == _usage_cache_generation:
            _usage_cache[tenant_id] = (timestamp, dict(usage))


def invalidate_usage_cache(tenant_id=None):
    """Invalidate cached values and prevent stale in-flight refresh publication."""
    global _usage_cache_generation
    with _usage_cache_state_lock:
        _usage_cache_generation += 1
        if tenant_id is None:
            _usage_cache.clear()
        else:
            _usage_cache.pop(tenant_id, None)
