# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit contracts for the shared system configuration refresh component."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import OperationalError

from test.backend.configuration.test_catalog import EXPECTED_DEFAULTS


def _runtime(**overrides):
    from infrastructure.system_configuration.runtime import SystemConfigurationRuntime

    return SystemConfigurationRuntime(**overrides)


async def test_refresh_rejects_invalid_snapshot_and_retains_last_valid_value():
    loads = [dict(EXPECTED_DEFAULTS), {"MAX_TENANT_COUNT": 1}]
    loader = AsyncMock(side_effect=loads)
    runtime = _runtime(loader=loader)

    assert await runtime.refresh() is True
    assert await runtime.refresh() is False
    assert runtime.get_snapshot().to_dict() == EXPECTED_DEFAULTS


async def test_refresh_database_timeout_retains_snapshot_and_retries():
    loader = AsyncMock(
        side_effect=[
            dict(EXPECTED_DEFAULTS),
            OperationalError("SELECT", {}, RuntimeError("statement timeout")),
            {**EXPECTED_DEFAULTS, "MAX_TENANT_COUNT": 7},
        ]
    )
    runtime = _runtime(loader=loader)

    assert await runtime.refresh() is True
    assert await runtime.refresh() is False
    assert runtime.get_snapshot().to_dict() == EXPECTED_DEFAULTS
    assert await runtime.refresh() is True
    assert runtime.get_snapshot().get("MAX_TENANT_COUNT") == 7
    assert loader.await_count == 3


async def test_getter_is_local_and_does_not_call_loader_or_redis():
    loader = AsyncMock(return_value=dict(EXPECTED_DEFAULTS))
    redis_factory = AsyncMock()
    runtime = _runtime(loader=loader, redis_factory=redis_factory)
    await runtime.refresh()
    loader.reset_mock()
    redis_factory.reset_mock()

    snapshot = runtime.get_snapshot()

    assert snapshot.get("MAX_TENANT_COUNT") == 100
    loader.assert_not_called()
    redis_factory.assert_not_called()


def test_getter_fails_when_no_valid_snapshot_exists():
    from infrastructure.system_configuration.runtime import ConfigurationNotReadyError

    runtime = _runtime(loader=AsyncMock())

    with pytest.raises(ConfigurationNotReadyError):
        runtime.get_snapshot()


async def test_concurrent_refreshes_are_serialized_and_latest_database_value_wins():
    active = 0
    maximum_active = 0
    calls = 0

    async def loader():
        nonlocal active, maximum_active, calls
        active += 1
        maximum_active = max(maximum_active, active)
        calls += 1
        await asyncio.sleep(0.01)
        active -= 1
        return {**EXPECTED_DEFAULTS, "MAX_TENANT_COUNT": calls}

    runtime = _runtime(loader=loader)

    await asyncio.gather(*(runtime.refresh() for _ in range(5)))

    assert maximum_active == 1
    assert runtime.get_snapshot().get("MAX_TENANT_COUNT") == 5


async def test_poll_coalesces_notifications_and_ignores_message_values():
    from infrastructure.system_configuration.runtime import CONFIGURATION_CHANNEL

    loader = AsyncMock(return_value={**EXPECTED_DEFAULTS, "MAX_TENANT_COUNT": 7})
    runtime = _runtime(loader=loader)
    messages = [
        {"channel": CONFIGURATION_CHANNEL, "data": "stale-values-and-revision"},
        {"channel": CONFIGURATION_CHANNEL, "data": "duplicate"},
    ]
    pubsub = Mock(spec=["subscribe", "get_message", "close"])
    pubsub.get_message = AsyncMock(side_effect=[messages[0], messages[1], None])

    await runtime.poll_once(pubsub)

    assert loader.await_count == 1
    assert runtime.get_snapshot().get("MAX_TENANT_COUNT") == 7


async def test_start_loads_before_and_after_subscription_and_stop_closes_resources():
    loader = AsyncMock(return_value=dict(EXPECTED_DEFAULTS))
    pubsub = Mock(spec=["subscribe", "get_message", "close"])
    pubsub.subscribe = AsyncMock()

    async def pending_message(**_kwargs):
        await asyncio.Future()

    pubsub.get_message = AsyncMock(side_effect=pending_message)
    pubsub.close = AsyncMock()
    redis = Mock(spec=["pubsub", "aclose"])
    redis.pubsub = Mock(return_value=pubsub)
    redis.aclose = AsyncMock()
    runtime = _runtime(loader=loader, redis_factory=lambda: redis, normal_interval=0.01)

    await runtime.start()
    await asyncio.sleep(0)
    await runtime.stop()

    assert loader.await_count == 2
    pubsub.subscribe.assert_awaited_once()
    pubsub.close.assert_awaited_once()
    redis.aclose.assert_awaited_once()


async def test_reconnect_subscribes_again_and_refreshes_database():
    loader = AsyncMock(return_value=dict(EXPECTED_DEFAULTS))
    pubsub = Mock(spec=["subscribe", "get_message", "close"])
    pubsub.subscribe = AsyncMock()

    async def pending_message(**_kwargs):
        await asyncio.Future()

    pubsub.get_message = AsyncMock(side_effect=pending_message)
    pubsub.close = AsyncMock()
    redis = Mock(spec=["pubsub", "aclose"])
    redis.pubsub = Mock(return_value=pubsub)
    redis.aclose = AsyncMock()
    redis_factory = Mock(side_effect=[RuntimeError("redis unavailable"), redis])
    runtime = _runtime(
        loader=loader,
        redis_factory=redis_factory,
        disconnected_interval=0.001,
    )
    await runtime.start()
    for _ in range(20):
        if redis_factory.call_count >= 2 and pubsub.subscribe.await_count:
            break
        await asyncio.sleep(0.001)
    await runtime.stop()

    assert redis_factory.call_count >= 2
    assert loader.await_count >= 3
    pubsub.subscribe.assert_awaited_once()


async def test_pubsub_close_failure_still_closes_redis_client():
    runtime = _runtime(loader=AsyncMock())
    pubsub = Mock()
    pubsub.aclose = AsyncMock(side_effect=ConnectionError("close failed")
    )
    redis = Mock()
    redis.aclose = AsyncMock()
    runtime._pubsub = pubsub
    runtime._redis = redis

    await runtime._close_connection()

    pubsub.aclose.assert_awaited_once_with()
    redis.aclose.assert_awaited_once_with()


async def test_reconnect_continues_after_pubsub_close_failure():
    loader = AsyncMock(return_value=dict(EXPECTED_DEFAULTS))
    pubsub = Mock(spec=["subscribe", "get_message", "aclose"])
    pubsub.subscribe = AsyncMock()
    pubsub.get_message = AsyncMock(side_effect=ConnectionError("lost connection"))
    pubsub.aclose = AsyncMock(side_effect=ConnectionError("close failed"))
    redis = Mock(spec=["pubsub", "aclose"])
    redis.pubsub = Mock(return_value=pubsub)
    redis.aclose = AsyncMock()
    redis_factory = Mock(side_effect=[redis, redis])
    runtime = _runtime(
        loader=loader,
        redis_factory=redis_factory,
        disconnected_interval=0.001,
    )

    task = asyncio.create_task(runtime._run())
    for _ in range(30):
        if redis_factory.call_count >= 2:
            break
        await asyncio.sleep(0.001)

    assert redis_factory.call_count >= 2
    assert not task.done()
    await runtime.stop()
    assert pubsub.aclose.await_count >= 1
    assert redis.aclose.await_count >= 1


async def test_stop_suppresses_task_failure_and_closes_resources():
    runtime = _runtime(loader=AsyncMock())
    pubsub = Mock()
    pubsub.aclose = AsyncMock(side_effect=ConnectionError("close failed")
    )
    redis = Mock()
    redis.aclose = AsyncMock()
    runtime._pubsub = pubsub
    runtime._redis = redis

    async def fail():
        raise ConnectionError("task failed")

    runtime._task = asyncio.create_task(fail())
    await asyncio.sleep(0)

    await runtime.stop()

    assert runtime._task is None
    assert runtime._pubsub is None
    assert runtime._redis is None
    pubsub.aclose.assert_awaited_once_with()
    redis.aclose.assert_awaited_once_with()


async def test_start_replaces_an_already_finished_refresh_task():
    loader = AsyncMock(return_value=dict(EXPECTED_DEFAULTS))
    runtime = _runtime(loader=loader, disconnected_interval=0.001)
    previous = asyncio.create_task(asyncio.sleep(0))
    await previous
    runtime._task = previous

    await runtime.start()

    assert runtime._task is not previous
    assert not runtime._task.done()
    await runtime.stop()
