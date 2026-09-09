"""Unit tests for the HTTP / WebSocket transport mixins."""

from unittest.mock import AsyncMock

import pytest
from nexent.core.gateway.transport import HttpTransportMixin, WebSocketTransportMixin


def test_http_transport_defaults():
    transport = HttpTransportMixin(base_url="https://api.example.com", api_key="sk-key")

    assert transport.transport_type == "http"
    assert transport._base_url == "https://api.example.com"
    assert transport._api_key == "sk-key"
    assert transport._ssl_verify is True
    assert transport._timeout == 30.0


def test_http_transport_custom_timeout_and_ssl():
    transport = HttpTransportMixin(
        base_url="https://api.example.com",
        api_key="sk-key",
        ssl_verify=False,
        timeout=5.5,
    )

    assert transport._ssl_verify is False
    assert transport._timeout == 5.5


@pytest.mark.asyncio
async def test_http_transport_connect_close_health_check():
    transport = HttpTransportMixin(base_url="https://api.example.com", api_key="sk-key")

    assert await transport.connect() is None
    assert await transport.close() is None
    assert await transport.health_check() is True


def test_ws_transport_defaults():
    transport = WebSocketTransportMixin()

    assert transport.transport_type == "websocket"
    assert transport._ws_url is None
    assert transport._auth_headers == {}
    assert transport._ws_connection is None


def test_ws_transport_with_params():
    transport = WebSocketTransportMixin(ws_url="wss://example.com/ws", auth_headers={"token": "abc"})

    assert transport._ws_url == "wss://example.com/ws"
    assert transport._auth_headers == {"token": "abc"}


@pytest.mark.asyncio
async def test_ws_transport_connect_and_close_connection():
    transport = WebSocketTransportMixin(ws_url="wss://example.com/ws")
    assert await transport.connect() is None

    connection = AsyncMock()
    transport._ws_connection = connection
    await transport.close()

    connection.close.assert_awaited_once()
    assert transport._ws_connection is None


@pytest.mark.asyncio
async def test_ws_transport_close_without_connection_is_idempotent():
    transport = WebSocketTransportMixin(ws_url="wss://example.com/ws")

    await transport.close()

    assert transport._ws_connection is None


@pytest.mark.asyncio
async def test_ws_transport_close_clears_connection_on_error():
    transport = WebSocketTransportMixin(ws_url="wss://example.com/ws")
    connection = AsyncMock()
    connection.close.side_effect = RuntimeError("connection reset")
    transport._ws_connection = connection

    with pytest.raises(RuntimeError, match="connection reset"):
        await transport.close()

    assert transport._ws_connection is None


@pytest.mark.asyncio
async def test_ws_transport_health_check():
    transport_with_url = WebSocketTransportMixin(ws_url="wss://example.com/ws")
    transport_without_url = WebSocketTransportMixin()

    assert await transport_with_url.health_check() is True
    assert await transport_without_url.health_check() is False