"""Unit regressions for native MCP transport configuration."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from openjiuwen.core.foundation.tool.mcp.base import McpServerConfig

from nexent.core.agents.core_adapters.mcp import _ConfiguredNativeClient


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
    client = _ConfiguredNativeClient(McpServerConfig(
        server_name="fixture", server_path="http://fixture/mcp", client_type=transport, auth_headers=headers,
    ), factory)
    streams = (MagicMock(), MagicMock(), MagicMock())
    client._exit_stack = MagicMock(enter_async_context=AsyncMock(
        side_effect=[http_client, streams, session] if transport == "streamable-http" else [streams, session],
    ))
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
        open_sse.assert_called_once_with("http://fixture/mcp", headers=headers, timeout=3,
                                        httpx_client_factory=factory)
        factory.assert_not_called()
        open_http.assert_not_called()
