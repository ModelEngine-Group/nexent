# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Managed async access must preserve cancellation, deadlines and write uncertainty."""

from threading import Event, get_ident
from time import monotonic
from unittest.mock import MagicMock

import pytest
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.storage.errors import CapabilityUnsupported, OutcomeUnknown
from nexent.storage.models import TTL, OperationContext, StorageScope, TTLMode

from infrastructure.redis.kv import RedisKeyValueConfig, RedisKeyValueStore
from infrastructure.storage.async_access import ManagedKeyValueStore


def make_manager():
    manager = ThreadManager(
        "storage-test",
        {
            "control-io": LanePolicy(
                "control-io",
                max_workers=1,
                max_queue_size=1,
                queue_timeout_seconds=1,
                cancel_grace_seconds=0.1,
                shutdown_grace_seconds=1,
            )
        },
    )
    manager.start()
    return manager


@pytest.mark.asyncio
async def test_blocking_port_is_rejected_on_the_event_loop_without_io():
    factory = MagicMock()
    store = RedisKeyValueStore(
        RedisKeyValueConfig("redis://fixture/0", "fixture"),
        StorageScope("runtime", "tenant", "actor", {"cache"}),
        namespace="cache",
        client_factory=factory,
    )
    with pytest.raises(CapabilityUnsupported):
        store.get("key", context=OperationContext("read", monotonic() + 1))
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_async_access_uses_the_supplied_managed_worker():
    manager = make_manager()
    event_loop_thread = get_ident()
    scope = StorageScope("runtime", "tenant", "actor", {"cache"})

    class Store:
        def __init__(self):
            self.scope = scope

        def get(self, key, *, context):
            assert get_ident() != event_loop_thread
            assert context.cancelled is not None
            return key

    try:
        store = ManagedKeyValueStore(Store(), manager)
        assert (
            await store.get("value", context=OperationContext("read", monotonic() + 1))
            == "value"
        )
    finally:
        result = await manager.shutdown(timeout=1)
        assert result.stuck_execution_ids == ()


@pytest.mark.asyncio
async def test_started_write_timeout_is_unknown_and_worker_receives_cancellation():
    manager = make_manager()
    worker_exited = Event()
    scope = StorageScope("runtime", "tenant", "actor", {"cache"})

    class Store:
        def __init__(self):
            self.scope = scope

        def put(self, key, value, *, ttl, context):
            while not context.cancelled.is_set():
                worker_exited.wait(0.005)
            worker_exited.set()

    try:
        store = ManagedKeyValueStore(Store(), manager)
        with pytest.raises(OutcomeUnknown) as caught:
            await store.put(
                "key",
                b"value",
                ttl=TTL(TTLMode.NO_EXPIRY),
                context=OperationContext("write", monotonic() + 0.1),
            )
        assert caught.value.operation_id == "write"
    finally:
        result = await manager.shutdown(timeout=1)
        assert result.stuck_execution_ids == ()
    assert worker_exited.is_set()
