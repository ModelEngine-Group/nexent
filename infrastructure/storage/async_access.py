# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Async KV access through a caller-owned, bounded ThreadManager lane."""

import asyncio
from dataclasses import dataclass, replace
from threading import Event
from typing import TYPE_CHECKING

from nexent.storage.errors import DeadlineExceeded, OutcomeUnknown
from nexent.storage.interfaces import KeyValueStore
from nexent.storage.models import TTL, Cancellation, Missing, OperationContext, Revision

if TYPE_CHECKING:
    from nexent.core.concurrency import ThreadManagerBase


@dataclass(frozen=True)
class _CombinedCancellation:
    worker: Event
    caller: Cancellation | None

    def is_set(self):
        return self.worker.is_set() or self.caller is not None and self.caller.is_set()


class ManagedKeyValueStore:
    def __init__(
        self,
        store: KeyValueStore,
        manager: "ThreadManagerBase",
        *,
        lane: str = "control-io",
    ):
        self._store = store
        self._manager = manager
        self._lane = lane

    @property
    def scope(self):
        return self._store.scope

    @property
    def capabilities(self):
        return self._store.capabilities

    async def _run(self, method, *args, context, write=False, **kwargs):
        from nexent.core.concurrency import ManagedTaskSpec

        remaining = context.remaining()
        started = Event()

        def invoke(cancel_event):
            bound = replace(
                context,
                cancelled=_CombinedCancellation(cancel_event, context.cancelled),
            )
            bound.remaining()
            started.set()
            return method(*args, context=bound, **kwargs)

        spec = ManagedTaskSpec(
            task_name="storage.kv." + method.__name__,
            owner="storage." + self.scope.service_role,
            deadline_monotonic=context.deadline,
            pass_cancel_event=True,
        )
        try:
            async with asyncio.timeout(remaining):
                return await self._manager.run(self._lane, spec, invoke)
        except TimeoutError:
            error = OutcomeUnknown if write and started.is_set() else DeadlineExceeded
            raise error(operation_id=context.operation_id) from None

    async def get(self, key: str, *, context: OperationContext):
        return await self._run(self._store.get, key, context=context)

    async def put(self, key: str, value: bytes, *, ttl: TTL, context: OperationContext):
        return await self._run(
            self._store.put, key, value, ttl=ttl, context=context, write=True
        )

    async def compare_exchange(
        self,
        key: str,
        expected: Revision | Missing,
        value: bytes,
        *,
        ttl: TTL,
        context: OperationContext,
    ):
        return await self._run(
            self._store.compare_exchange,
            key,
            expected,
            value,
            ttl=ttl,
            context=context,
            write=True,
        )

    async def delete(
        self, key: str, *, expected: Revision | None = None, context: OperationContext
    ):
        return await self._run(
            self._store.delete, key, expected=expected, context=context, write=True
        )
