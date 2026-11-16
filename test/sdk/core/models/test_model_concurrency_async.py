# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Async admission shares legacy permits without blocking or spawning workers."""

import asyncio
import threading

import pytest
from nexent.core.model_service.concurrency import (
    ModelConcurrencyExceeded,
    ModelConcurrencyLimiter,
)


@pytest.mark.asyncio
async def test_sync_holder_blocks_async_admission_but_not_the_event_loop():
    limiter = ModelConcurrencyLimiter()
    stop = threading.Event()
    key = ("tenant", "provider", "model")
    held = limiter.acquire(key, 1, 1, stop)
    pending = asyncio.create_task(limiter.acquire_async(key, 1, 1, stop))
    await asyncio.sleep(0)
    assert not pending.done()
    other = await limiter.acquire_async(("other", "provider", "model"), 1, 1, stop)
    other.release()
    held.release()
    acquired = await asyncio.wait_for(pending, 1)
    with pytest.raises(ModelConcurrencyExceeded):
        limiter.acquire(key, 1, 0.001, stop)
    acquired.release()
    acquired.release()
    assert limiter._entries == {}


@pytest.mark.asyncio
async def test_async_timeout_and_task_cancel_release_waiter_references():
    limiter = ModelConcurrencyLimiter()
    stop = threading.Event()
    key = ("tenant", "provider", "model")
    held = limiter.acquire(key, 1, 1, stop)
    with pytest.raises(ModelConcurrencyExceeded):
        await limiter.acquire_async(key, 1, 0.001, stop)
    assert limiter._entries[key].references == 1
    waiting = asyncio.create_task(limiter.acquire_async(key, 1, 1, stop))
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert limiter._entries[key].references == 1
    held.release()
    assert limiter._entries == {}


@pytest.mark.asyncio
async def test_stop_event_and_conflicting_limit_never_acquire_another_permit():
    limiter = ModelConcurrencyLimiter()
    stop = threading.Event()
    key = ("tenant", "provider", "model")
    held = limiter.acquire(key, 1, 1, stop)
    with pytest.raises(ValueError, match="conflicting concurrency limits"):
        await limiter.acquire_async(key, 2, 1, stop)
    stop.set()
    with pytest.raises(RuntimeError, match="cancelled"):
        await limiter.acquire_async(key, 1, 1, stop)
    assert limiter._entries[key].references == 1
    held.release()
    assert limiter._entries == {}


@pytest.mark.parametrize("limit,timeout", [(0, 1), (1, 0)])
@pytest.mark.asyncio
async def test_invalid_async_limits_fail_before_retaining_entries(limit, timeout):
    limiter = ModelConcurrencyLimiter()
    with pytest.raises(ValueError):
        await limiter.acquire_async(
            ("tenant", "provider", "model"), limit, timeout, threading.Event()
        )
    assert limiter._entries == {}
