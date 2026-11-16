# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Process-local quota cache with no database or object-store import side effects."""

import threading
from contextlib import contextmanager
from typing import Any

# In-memory cache for usage data
_usage_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_usage_refresh_locks = {}
_usage_cache_state_lock = threading.RLock()
_usage_cache_generation = 0


@contextmanager
def usage_refresh_guard(tenant_id: str):
    """Coalesce refreshes per tenant without retaining idle lock objects."""
    with _usage_cache_state_lock:
        entry = _usage_refresh_locks.setdefault(tenant_id, [threading.RLock(), 0])
        entry[1] += 1
    try:
        with entry[0]:
            with _usage_cache_state_lock:
                generation = _usage_cache_generation
            yield generation
    finally:
        with _usage_cache_state_lock:
            entry[1] -= 1
            if entry[1] == 0:
                del _usage_refresh_locks[tenant_id]


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
