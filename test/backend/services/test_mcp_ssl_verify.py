# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""TLS certificate verification preference across remote MCP boundaries."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from backend.http.client import (
    create_httpx_client,
    create_verified_httpx_client,
)
from contracts.tool import (
    AddMcpServiceRequest,
    TestMcpConnectionRequest,
    UpdateMcpServiceRequest,
)
from management.services.mcp import health, registration
from management.services.tool import discovery


# ============================================================================
# Request contracts
# ============================================================================

@pytest.mark.parametrize("value", [True, False])
def test_add_request_ssl_verify_preference(value):
    assert AddMcpServiceRequest(name="svc", server_url="http://server/mcp").ssl_verify is True
    assert AddMcpServiceRequest(name="svc", server_url="http://server/mcp", ssl_verify=value).ssl_verify is value
    with pytest.raises(ValidationError):
        AddMcpServiceRequest(name="svc", server_url="http://server/mcp", ssl_verify=None)


def test_update_request_ssl_verify_omission_keeps_stored_value():
    assert UpdateMcpServiceRequest(mcp_id=1, name="svc").ssl_verify is None
    assert UpdateMcpServiceRequest(mcp_id=1, name="svc", ssl_verify=False).ssl_verify is False
    assert UpdateMcpServiceRequest(mcp_id=1, name="svc", ssl_verify=True).ssl_verify is True


@pytest.mark.parametrize("value", [True, False])
def test_connection_test_request_ssl_verify_preference(value):
    assert TestMcpConnectionRequest(server_url="http://server/mcp").ssl_verify is True
    assert TestMcpConnectionRequest(server_url="http://server/mcp", ssl_verify=value).ssl_verify is value
    with pytest.raises(ValidationError):
        TestMcpConnectionRequest(server_url="http://server/mcp", ssl_verify=None)


# ============================================================================
# HTTP client factories
# ============================================================================

@patch("backend.http.client.AsyncClient")
def test_verified_factory_verifies_peer_certificate(constructor):
    create_verified_httpx_client(headers={"X-Key": "1"}, timeout=5)
    constructor.assert_called_once_with(
        headers={"X-Key": "1"}, timeout=5, auth=None,
        follow_redirects=True, trust_env=False, verify=True,
    )


@patch("backend.http.client.AsyncClient")
def test_internal_factory_skips_peer_certificate(constructor):
    create_httpx_client(headers={"X-Key": "1"}, timeout=5)
    constructor.assert_called_once_with(
        headers={"X-Key": "1"}, timeout=5, auth=None,
        follow_redirects=True, trust_env=False, verify=False,
    )


# ============================================================================
# Health checks and connection tests
# ============================================================================

@pytest.mark.parametrize(
    "ssl_verify,expected",
    [(True, create_verified_httpx_client), (False, create_httpx_client)],
)
def test_health_check_selects_client_factory(ssl_verify, expected):
    assert health._select_mcp_httpx_client_factory(ssl_verify) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, False])
async def test_mcp_server_health_forwards_preference(mocker, value):
    check = mocker.patch.object(health, "_mcp_protocol_health_check", AsyncMock(return_value=["tool"]))
    await health.mcp_server_health("http://server/mcp", "token", None, ssl_verify=value)
    check.assert_awaited_once_with("http://server/mcp", {"Authorization": "token"}, ssl_verify=value)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, False])
async def test_connection_test_forwards_preference(mocker, value):
    connect = mocker.patch.object(health, "_mcp_protocol_connect", AsyncMock(return_value=True))
    assert await health.test_mcp_connection("http://server/mcp", None, None, ssl_verify=value) is True
    connect.assert_awaited_once_with("http://server/mcp", {}, ssl_verify=value)


@pytest.mark.asyncio
@pytest.mark.parametrize("preference", [{}, {"ssl_verify": True}, {"ssl_verify": False}])
async def test_stored_preference_used_for_service_health(mocker, preference):
    record = {
        "mcp_id": 1,
        "mcp_server": "http://server/mcp",
        "authorization_token": "token",
        "custom_headers": None,
        "config_json": None,
        **preference,
    }
    mocker.patch.object(health, "get_mcp_record_by_id_and_tenant", return_value=record)
    server_health = mocker.patch.object(health, "mcp_server_health", AsyncMock(return_value=True))
    result = await health.check_mcp_service_health(
        tenant_id="tenant", user_id="user", mcp_id=1, persist_status=False
    )
    assert result == "healthy"
    server_health.assert_awaited_once_with(
        remote_mcp_server="http://server/mcp",
        authorization_token="token",
        custom_headers=None,
        ssl_verify=preference.get("ssl_verify", True),
    )


@pytest.mark.asyncio
async def test_health_update_db_reads_stored_preference(mocker):
    mocker.patch.object(health, "get_mcp_authorization_token_by_name_and_url", return_value="token")
    mocker.patch.object(health, "get_mcp_custom_headers_by_name_and_url", return_value=None)
    stored = mocker.patch.object(health, "get_mcp_ssl_verify_by_name_and_url", return_value=False)
    server_health = mocker.patch.object(health, "mcp_server_health", AsyncMock(return_value=True))
    mocker.patch.object(health, "update_mcp_status_by_name_and_url")
    await health.check_mcp_health_and_update_db("http://server/mcp", "svc", "tenant", "user")
    stored.assert_called_once_with(mcp_name="svc", mcp_server="http://server/mcp", tenant_id="tenant")
    server_health.assert_awaited_once_with(
        remote_mcp_server="http://server/mcp",
        authorization_token="token",
        custom_headers=None,
        ssl_verify=False,
    )


# ============================================================================
# Tool discovery
# ============================================================================

@pytest.mark.parametrize(
    "ssl_verify,expected",
    [(True, create_verified_httpx_client), (False, create_httpx_client)],
)
def test_discovery_transport_selects_client_factory(mocker, ssl_verify, expected):
    sse = mocker.patch.object(discovery, "SSETransport")
    stream = mocker.patch.object(discovery, "StreamableHttpTransport")
    discovery._create_mcp_transport("http://server/sse", None, None, ssl_verify=ssl_verify)
    sse.assert_called_once_with(url="http://server/sse", headers={}, httpx_client_factory=expected)
    stream.assert_not_called()
    discovery._create_mcp_transport("http://server/mcp", "token", {"X-Key": "1"}, ssl_verify=ssl_verify)
    stream.assert_called_once_with(
        url="http://server/mcp",
        headers={"Authorization": "token", "X-Key": "1"},
        httpx_client_factory=expected,
    )


@pytest.fixture
def discovery_session(mocker):
    """Patch the fastmcp session so discovery runs without network access."""
    mocker.patch.object(discovery, "get_config_snapshot", lambda: {
        "MCP_REQUEST_TIMEOUT_SECONDS": 5,
        "RUNTIME_MCP_TOOL_TIMEOUT_SECONDS": 5,
    })
    mocker.patch.object(discovery, "get_mcp_authorization_token_by_name_and_url", return_value=None)
    mocker.patch.object(discovery, "get_mcp_custom_headers_by_name_and_url", return_value=None)
    stored = mocker.patch.object(discovery, "get_mcp_ssl_verify_by_name_and_url", return_value=False)
    transport = mocker.patch.object(discovery, "_create_mcp_transport")

    client_instance = MagicMock()
    client_instance.list_tools = AsyncMock(return_value=[])
    mocker.patch.object(discovery, "Client", return_value=client_instance)
    return SimpleNamespace(stored=stored, transport=transport)


@pytest.mark.asyncio
async def test_local_endpoint_keeps_verification_off(discovery_session):
    await discovery.get_tool_from_remote_mcp_server(
        "svc", "http://local/mcp/tenant/sse", tenant_id="tenant"
    )
    # Internal local MCP endpoints use the internal service certificate and
    # always skip verification; the stored flag is never consulted.
    discovery_session.stored.assert_not_called()
    assert discovery_session.transport.call_args.kwargs["ssl_verify"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, False])
async def test_remote_discovery_forwards_explicit_preference(discovery_session, value):
    await discovery.get_tool_from_remote_mcp_server(
        "svc", "https://remote.example/mcp", tenant_id="tenant", ssl_verify=value
    )
    assert discovery_session.transport.call_args.kwargs["ssl_verify"] is value


@pytest.mark.asyncio
async def test_remote_discovery_reads_stored_preference(discovery_session):
    await discovery.get_tool_from_remote_mcp_server(
        "svc", "https://remote.example/mcp", tenant_id="tenant"
    )
    discovery_session.stored.assert_called_once_with(
        mcp_name="svc", mcp_server="https://remote.example/mcp", tenant_id="tenant"
    )
    assert discovery_session.transport.call_args.kwargs["ssl_verify"] is False


# ============================================================================
# Registration
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, False])
async def test_add_mcp_service_uses_and_persists_preference(mocker, value):
    mocker.patch.object(registration, "check_mcp_name_exists", return_value=False)
    check = mocker.patch.object(registration, "_mcp_protocol_health_check", AsyncMock(return_value=["tool"]))
    create = mocker.patch.object(registration, "create_mcp_record", return_value=42)
    result = await registration.add_mcp_service(
        tenant_id="tenant", user_id="user", name="svc", description=None, source="local",
        server_url="https://remote.example/mcp", tags=[], authorization_token=None,
        container_config=None, registry_json={}, ssl_verify=value,
    )
    assert result == 42
    check.assert_awaited_once_with("https://remote.example/mcp", {}, ssl_verify=value)
    mcp_data = create.call_args.kwargs["mcp_data"]
    assert mcp_data["ssl_verify"] is value
