# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""QUOTA-CACHE-ASYNC-01 covers shared refresh ownership and cancellation."""

import asyncio

import pytest
from management.services.knowledge_base import usage_cache as cache
from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager


@pytest.fixture(autouse=True)
def clean_cache():
    cache.invalidate_usage_cache()
    yield
    cache.invalidate_usage_cache()
    assert cache._usage_refresh_locks == {}


@pytest.fixture
async def manager():
    value = ThreadManager(service_name='quota-async-test', lane_policies={
        'control-io': LanePolicy('control-io', 2, 4),
    })
    value.start()
    try:
        yield value
    finally:
        result = await value.shutdown(timeout=3)
        assert not result.stuck_execution_ids


async def test_async_waiter_does_not_enter_during_sync_refresh(manager):
    entered, release = asyncio.Event(), asyncio.Event()
    loop = asyncio.get_running_loop()
    from threading import Event

    unblock = Event()

    def synchronous():
        with cache.usage_refresh_guard('tenant'):
            loop.call_soon_threadsafe(entered.set)
            assert unblock.wait(3)

    task = asyncio.create_task(manager.run('control-io', ManagedTaskSpec(task_name='refresh', owner='test'), synchronous))
    await asyncio.wait_for(entered.wait(), 2)

    async def asynchronous():
        async with cache.async_usage_refresh_guard('tenant'):
            release.set()

    waiter = asyncio.create_task(asynchronous())
    try:
        await asyncio.sleep(0)
        assert not release.is_set()
    finally:
        unblock.set()
    await asyncio.wait_for(asyncio.gather(task, waiter), 3)
    assert release.is_set()


async def test_sync_waiter_does_not_enter_during_async_refresh(manager):
    from threading import Event

    attempted, entered = Event(), Event()

    def synchronous():
        attempted.set()
        with cache.usage_refresh_guard('tenant'):
            entered.set()

    async with cache.async_usage_refresh_guard('tenant'):
        task = asyncio.create_task(manager.run('control-io', ManagedTaskSpec(task_name='refresh', owner='test'), synchronous))
        async with asyncio.timeout(2):
            while not attempted.is_set():
                await asyncio.sleep(.001)
        assert not entered.is_set()
    await asyncio.wait_for(task, 3)
    assert entered.is_set()


@pytest.mark.parametrize('cancel_after_handoff', [False, True])
async def test_cancelled_waiter_releases_queued_or_awarded_slot(cancel_after_handoff):
    events = []

    async def refresh(name):
        async with cache.async_usage_refresh_guard('tenant'):
            events.append(name)

    async with cache.async_usage_refresh_guard('tenant'):
        first = asyncio.create_task(refresh('cancelled'))
        second = asyncio.create_task(refresh('next'))
        await asyncio.sleep(0)
        if not cancel_after_handoff:
            first.cancel()
    if cancel_after_handoff:
        first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    await asyncio.wait_for(second, 2)
    assert events == ['next']


async def test_holder_cancellation_releases_next_waiter():
    started = asyncio.Event()

    async def held():
        async with cache.async_usage_refresh_guard('tenant'):
            started.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(held())
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with asyncio.timeout(1):
        async with cache.async_usage_refresh_guard('tenant'):
            pass


async def test_exception_releases_owner_and_other_tenant_is_independent():
    with pytest.raises(ValueError):
        async with cache.async_usage_refresh_guard('tenant'):
            async with cache.async_usage_refresh_guard('other'):
                raise ValueError()
    with cache.usage_refresh_guard('tenant'):
        pass


async def test_invalidation_during_async_refresh_prevents_publication():
    async with cache.async_usage_refresh_guard('tenant') as generation:
        cache.invalidate_usage_cache('tenant')
        cache.store_usage_cache('tenant', 100, {'total_bytes': 7}, generation)
    assert 'tenant' not in cache._usage_cache
    async with cache.async_usage_refresh_guard('tenant') as generation:
        cache.store_usage_cache('tenant', 101, {'total_bytes': 9}, generation)
    assert cache._usage_cache['tenant'] == (101, {'total_bytes': 9})


async def test_waiters_keep_fifo_order_and_capture_generation_at_handoff():
    seen = []

    async def refresh(number):
        async with cache.async_usage_refresh_guard('tenant') as generation:
            seen.append(number)
            cache.store_usage_cache('tenant', number, {'total_bytes': number}, generation)

    async with cache.async_usage_refresh_guard('tenant'):
        tasks = [asyncio.create_task(refresh(i)) for i in range(4)]
        await asyncio.sleep(0)
        cache.invalidate_usage_cache('tenant')
    await asyncio.wait_for(asyncio.gather(*tasks), 2)
    assert seen == [0, 1, 2, 3] and cache._usage_cache['tenant'][1] == {'total_bytes': 3}


async def test_waiter_total_timeout_does_not_consume_next_ownership():
    entered = []

    async def waiting():
        async with asyncio.timeout(.02):
            async with cache.async_usage_refresh_guard('tenant'):
                entered.append(True)

    async with cache.async_usage_refresh_guard('tenant'):
        with pytest.raises(TimeoutError):
            await waiting()
    assert not entered
    async with cache.async_usage_refresh_guard('tenant'):
        pass
