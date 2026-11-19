# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit regressions for native MCP transport configuration."""

import asyncio
from contextlib import AsyncExitStack
from threading import Event
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from openjiuwen.core.foundation.tool.mcp.base import McpServerConfig

from nexent.consts.mcp_errors import MCPConnectionFailure, MCPConnectionTimeoutError, classify_mcp_failure
from nexent.core.agents.cores.jiuwen.mcp import JiuwenMCPCollection, _ConfiguredNativeClient
from nexent.core.concurrency import RunCancellationScope


def test_session_worker_does_not_replace_recorded_connection_error_with_cleanup_error():
    owner = JiuwenMCPCollection(
        observe=lambda *_: None,
        manager=MagicMock(),
        server_parameters=[],
        cancellation_scope=RunCancellationScope(),
        tool_timeout_seconds=3,
        close_timeout_seconds=1,
    )
    original = ValueError("original connection failure")

    async def failed_session():
        owner._startup_error = original
        raise RuntimeError("cleanup failure")

    owner._run_async_session = failed_session
    with pytest.raises(RuntimeError, match="cleanup failure"):
        owner._run_session(Event())
    assert owner._startup_error is original
    assert owner._ready.is_set()


@pytest.mark.asyncio
async def test_native_disconnect_preserves_transport_exception_and_clears_session():
    client = _ConfiguredNativeClient(
        McpServerConfig(server_name="fixture", server_path="http://fixture/mcp", client_type="streamable-http"), None
    )
    original = RuntimeError("transport group failure")
    client._exit_stack = MagicMock(aclose=AsyncMock(side_effect=original))
    with pytest.raises(RuntimeError) as found:
        await client.disconnect(timeout=1)
    assert found.value is original
    assert client._session is None and client._is_disconnected


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_error", [asyncio.CancelledError(), RuntimeError("cleanup")])
async def test_connection_diagnostic_survives_task_bound_cleanup(monkeypatch, cleanup_error):
    original = httpx.HTTPStatusError(
        "private authentication response",
        request=httpx.Request("POST", "http://fixture/mcp"),
        response=httpx.Response(401),
    )
    client = MagicMock(connect=AsyncMock(side_effect=original), disconnect=AsyncMock(side_effect=cleanup_error))
    monkeypatch.setattr("nexent.core.agents.cores.jiuwen.mcp._ConfiguredNativeClient", lambda *_: client)
    owner = JiuwenMCPCollection(
        observe=lambda *_: None,
        manager=MagicMock(),
        server_parameters=[{"url": "http://fixture/mcp", "transport": "streamable-http"}],
        cancellation_scope=RunCancellationScope(),
        tool_timeout_seconds=3,
        close_timeout_seconds=1,
    )
    raised = None
    # Lazy connect runs inside the owner stack and registers the disconnect
    # callback itself; a failing disconnect during stack cleanup must not
    # erase the recorded connection diagnostic.
    with pytest.raises(type(cleanup_error)):
        async with AsyncExitStack() as stack:
            owner._stack = stack
            try:
                await owner._connect_server({"url": "http://fixture/mcp", "transport": "streamable-http"})
            except Exception as exc:
                raised = exc
                raise
    assert isinstance(raised, MCPConnectionFailure)
    assert owner._startup_error is not None
    assert classify_mcp_failure(owner._startup_error)[0] == "auth_failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["streamable-http", "sse"])
async def test_native_transport_preserves_headers_factory_and_session(monkeypatch, transport):
    headers = {"Authorization": "fixture-token"}
    http_client = MagicMock()
    factory = MagicMock(return_value=http_client)
    stream_context = MagicMock()
    open_http = MagicMock(return_value=stream_context)
    open_sse = MagicMock(return_value=stream_context)
    session = MagicMock(initialize=AsyncMock())
    create_session = MagicMock(return_value=session)
    monkeypatch.setattr("mcp.client.streamable_http.streamable_http_client", open_http)
    monkeypatch.setattr("mcp.client.sse.sse_client", open_sse)
    monkeypatch.setattr("mcp.ClientSession", create_session)
    client = _ConfiguredNativeClient(
        McpServerConfig(
            server_name="fixture",
            server_path="http://fixture/mcp",
            client_type=transport,
            auth_headers=headers,
        ),
        factory,
    )
    streams = (MagicMock(), MagicMock(), MagicMock())
    client._exit_stack = MagicMock(
        enter_async_context=AsyncMock(
            side_effect=[http_client, streams, session] if transport == "streamable-http" else [streams, session],
        )
    )
    assert await client.connect(timeout=3)
    session.initialize.assert_awaited_once()
    create_session.assert_called_once_with(streams[0], streams[1])
    if transport == "streamable-http":
        factory.assert_called_once()
        assert factory.call_args.kwargs["headers"] == headers
        assert factory.call_args.kwargs["timeout"].connect == 3
        open_http.assert_called_once_with("http://fixture/mcp", http_client=http_client)
        assert client._exit_stack.enter_async_context.call_args_list[0].args[0] is http_client
        open_sse.assert_not_called()
    else:
        open_sse.assert_called_once_with(
            "http://fixture/mcp", headers=headers, timeout=3, httpx_client_factory=factory
        )
        factory.assert_not_called()
        open_http.assert_not_called()


@pytest.mark.asyncio
async def test_false_connect_result_records_timeout_and_disconnects_owner(monkeypatch):
    client = MagicMock(connect=AsyncMock(return_value=False), disconnect=AsyncMock())
    monkeypatch.setattr("nexent.core.agents.cores.jiuwen.mcp._ConfiguredNativeClient", lambda *_: client)
    owner = JiuwenMCPCollection(observe=lambda *_: None, manager=MagicMock(),
        server_parameters=[{"url": "http://fixture/mcp", "transport": "streamable-http"}],
        cancellation_scope=RunCancellationScope(), tool_timeout_seconds=3,
        connect_timeout_seconds=2, close_timeout_seconds=1,
    )
    with pytest.raises(MCPConnectionFailure) as found:
        async with AsyncExitStack() as stack:
            owner._stack = stack
            await owner._connect_server({"url": "http://fixture/mcp", "transport": "streamable-http"})
    assert owner._startup_error is found.value
    assert isinstance(found.value.__cause__, MCPConnectionTimeoutError)
    assert classify_mcp_failure(found.value)[0] == "timeout"
    client.connect.assert_awaited_once_with(timeout=2)
    client.list_tools.assert_not_called()
    client.disconnect.assert_awaited_once_with(timeout=1)
    assert owner.tools == []


@pytest.mark.asyncio
async def test_successful_disconnect_closes_stack_and_clears_all_transport_references():
    client = _ConfiguredNativeClient(
        McpServerConfig(server_name="fixture", server_path="http://fixture/mcp", client_type="streamable-http"), None
    )
    client._exit_stack = MagicMock(aclose=AsyncMock())
    client._session, client._client, client._read, client._write = (object() for _ in range(4))
    client._is_disconnected = False
    assert await client.disconnect(timeout=1) is True
    client._exit_stack.aclose.assert_awaited_once()
    assert (client._session, client._client, client._read, client._write) == (None, None, None, None)
    assert client._is_disconnected is True
