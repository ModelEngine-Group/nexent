# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit contracts for the shared system configuration refresh component."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import OperationalError

from test.backend.configuration.test_catalog import EXPECTED_DEFAULTS


def _runtime(**overrides):
    from management.configuration.runtime import SystemConfigurationRuntime

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
    from management.configuration.runtime import ConfigurationNotReadyError

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
    from management.configuration.runtime import CONFIGURATION_CHANNEL

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
