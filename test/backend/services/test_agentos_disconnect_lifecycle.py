# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Ensure disconnect cancels only the work owned by the AgentOS request."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.http.server.agentos_lifecycle import run_until_disconnect


async def test_execution_completion_closes_the_disconnect_waiter():
    waiting = asyncio.Event()
    closed = asyncio.Event()
    response = object()

    async def receive():
        waiting.set()
        try:
            await asyncio.Future()
        finally:
            closed.set()

    async def execute():
        await waiting.wait()
        return response

    assert await run_until_disconnect(SimpleNamespace(receive=receive), execute()) is response
    assert closed.is_set()


async def test_disconnect_waits_for_worker_cleanup_before_returning():
    started, closed = asyncio.Event(), asyncio.Event()

    async def execute():
        started.set()
        try:
            await asyncio.Future()
        finally:
            closed.set()

    replies = iter([{"type": "http.request"}, {"type": "http.disconnect"}])

    async def receive():
        await started.wait()
        return next(replies)

    transport = SimpleNamespace(receive=AsyncMock(side_effect=receive))
    response = await run_until_disconnect(transport, execute())

    assert response.status_code == 499
    assert response.body == b'{"code":"AGENTOS_CLIENT_DISCONNECTED"}'
    assert closed.is_set()
    assert transport.receive.await_count == 2


async def test_execution_failure_is_propagated_after_waiter_cleanup():
    waiting = asyncio.Event()
    closed = asyncio.Event()

    async def receive():
        waiting.set()
        try:
            await asyncio.Future()
        finally:
            closed.set()

    async def execute():
        await waiting.wait()
        raise RuntimeError("worker stopped")

    with pytest.raises(RuntimeError, match="worker stopped"):
        await run_until_disconnect(SimpleNamespace(receive=receive), execute())
    assert closed.is_set()
