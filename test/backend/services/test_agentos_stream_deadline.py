# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bound response-header admission without limiting an admitted SSE lifetime."""

import asyncio
import logging
from unittest.mock import AsyncMock

import httpx
import pytest

from contracts.agentos import AgentResume
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeServiceTimeoutError
from infrastructure.agentos_client import AgentOSClient


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setattr(environment, "JWT_SECRET", "synthetic-deadline-signing-key")
    monkeypatch.setattr(environment, "AGENTOS_STREAM_OPEN_TIMEOUT_SECONDS", 0.02)


@pytest.mark.asyncio
async def test_header_deadline_cancels_pending_transport_and_closes_once(transport, caplog):
    exited = asyncio.Event()

    async def handler(request):
        try:
            await asyncio.sleep(10)
        finally:
            exited.set()

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    original_close = client.aclose
    client.aclose = AsyncMock(wraps=original_close)
    agentos = AgentOSClient("http://runtime", lambda **_: client)
    with caplog.at_level(logging.WARNING), pytest.raises(RuntimeServiceTimeoutError):
        await asyncio.wait_for(agentos.resume(
            AgentResume(conversation_id=42, run_id="a" * 32), "user", "tenant",
        ), timeout=1)
    assert exited.is_set() and client.is_closed
    client.aclose.assert_awaited_once()
    assert "agentos_stream_open_timeout" in caplog.text and "phase=headers" in caplog.text
    assert "synthetic-deadline-signing-key" not in caplog.text


@pytest.mark.asyncio
async def test_external_cancellation_remains_cancellation_and_closes_once(transport):
    entered = asyncio.Event()

    async def handler(request):
        entered.set()
        await asyncio.sleep(10)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client.aclose = AsyncMock(wraps=client.aclose)
    agentos = AgentOSClient("http://runtime", lambda **_: client)
    task = asyncio.create_task(agentos.resume(AgentResume(conversation_id=42, run_id="a" * 32), "user", "tenant"))
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.is_closed
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_admitted_stream_outlives_header_deadline_and_closes_once(transport):
    class Stream(httpx.AsyncByteStream):
        closed = 0

        async def __aiter__(self):
            await asyncio.sleep(0.06)
            yield b"data: complete\n\n"

        async def aclose(self):
            self.closed += 1

    stream = Stream()
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream)))
    client.aclose = AsyncMock(wraps=client.aclose)
    agentos = AgentOSClient("http://runtime", lambda **_: client)
    response = await agentos.resume(AgentResume(conversation_id=42, run_id="a" * 32), "user", "tenant")
    assert b"".join([chunk async for chunk in response.body_iterator]) == b"data: complete\n\n"
    await response.background()
    assert client.is_closed and stream.closed == 1
    client.aclose.assert_awaited_once()
