# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
from contextlib import AsyncExitStack

from consts.const import MCP_REQUEST_TIMEOUT_SECONDS
from contracts.errors.exceptions import MCPConnectionError, McpNotFoundError, McpValidationError
from management.db.mcp.remote import get_mcp_authorization_token_by_name_and_url, get_mcp_custom_headers_by_name_and_url, get_mcp_record_by_id_and_tenant, update_mcp_record_status_by_id, update_mcp_status_by_name_and_url
from fastmcp import Client
from fastmcp.client.transports import SSETransport, StreamableHttpTransport
from infrastructure.http.client import create_httpx_client
from management.services.mcp.common import (
    logger,
)


def _iter_exception_chain(exc: BaseException):
    seen: set[int] = set()
    current: BaseException | None = exc
    while current and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _format_mcp_connection_error(exc: BaseException) -> str:
    for candidate in _iter_exception_chain(exc):
        error_type = type(candidate).__name__.lower()
        error_text = str(candidate).lower()
        if "timeout" in error_type or any(
            keyword in error_text for keyword in ("timeout", "timed out", "etimedout")
        ):
            return "MCP connection timeout"
        if any(
            keyword in error_text
            for keyword in ("connection refused", "econnrefused", "actively refused")
        ):
            return "MCP connection refused"
        if any(
            keyword in error_text
            for keyword in (
                "unauthorized",
                "forbidden",
                "authentication",
                "authorization",
                "401",
                "403",
            )
        ):
            return "MCP authentication failed"
        if any(keyword in error_text for keyword in ("404", "not found", "endpoint")):
            return "MCP endpoint not found"
        if any(keyword in error_text for keyword in ("protocol", "invalid sse")):
            return "MCP protocol or endpoint invalid"
        if any(
            keyword in error_text
            for keyword in (
                "dns",
                "getaddrinfo",
                "enotfound",
                "eai_again",
                "network unreachable",
            )
        ):
            return "MCP address unreachable"
    return "MCP connection failed"


async def mcp_server_health(
    remote_mcp_server: str,
    authorization_token: str | None = None,
    custom_headers: dict | None = None,
) -> bool:
    """Check if an MCP server is healthy and reachable via MCP protocol.

    Returns True if the server is reachable and responds to tool listing.
    Raises MCPConnectionError if the server is unreachable or does not support MCP.
    """
    url_stripped = remote_mcp_server.strip()
    headers = {}
    if authorization_token:
        headers["Authorization"] = authorization_token
    if custom_headers:
        headers.update(custom_headers)

    tool_names = await _mcp_protocol_health_check(url_stripped, headers)
    if not tool_names:
        raise MCPConnectionError(
            "MCP server is unreachable or does not support MCP protocol"
        )
    return True


async def _mcp_protocol_health_check(url_stripped: str, headers: dict) -> list[str]:
    """Try to establish an MCP protocol-level connection and return tool names.

    Returns a list of tool names on success, or an empty list on failure.
    """
    try:
        if url_stripped.endswith("/sse"):
            transport = SSETransport(
                url=url_stripped,
                headers=headers,
                httpx_client_factory=create_httpx_client,
            )
        elif url_stripped.endswith("/mcp"):
            transport = StreamableHttpTransport(
                url=url_stripped,
                headers=headers,
                httpx_client_factory=create_httpx_client,
            )
        else:
            transport = StreamableHttpTransport(
                url=url_stripped,
                headers=headers,
                httpx_client_factory=create_httpx_client,
            )

        async def list_mcp_tools() -> list:
            client = Client(transport=transport)
            async with AsyncExitStack() as stack:
                await asyncio.wait_for(
                    stack.enter_async_context(client),
                    timeout=MCP_REQUEST_TIMEOUT_SECONDS,
                )
                # Verify the server can actually serve tools.
                # This exercises API key validation and end-to-end connectivity,
                # unlike is_connected() which only checks the initialize handshake.
                return await client.list_tools()

        tools_result = await list_mcp_tools()
        return [t.name for t in tools_result] if tools_result else []
    except BaseException as e:
        logger.debug(f"MCP protocol health check failed: {e}")
        raise MCPConnectionError(_format_mcp_connection_error(e))


async def _mcp_protocol_connect(url_stripped: str, headers: dict) -> bool:
    """Lightweight MCP connectivity check: establish an MCP initialize handshake only.

    Uses fastmcp.Client in an async context manager. The ``async with client:``
    block performs the MCP initialize handshake. After that,
    ``client.is_connected()`` returns True if the handshake succeeded.

    This is significantly faster than _mcp_protocol_health_check() which
    additionally calls list_tools().
    """
    try:
        if url_stripped.endswith("/sse"):
            transport = SSETransport(
                url=url_stripped,
                headers=headers,
                httpx_client_factory=create_httpx_client,
            )
        elif url_stripped.endswith("/mcp"):
            transport = StreamableHttpTransport(
                url=url_stripped,
                headers=headers,
                httpx_client_factory=create_httpx_client,
            )
        else:
            transport = StreamableHttpTransport(
                url=url_stripped,
                headers=headers,
                httpx_client_factory=create_httpx_client,
            )

        async def connect_client() -> bool:
            client = Client(transport=transport)
            async with AsyncExitStack() as stack:
                await asyncio.wait_for(
                    stack.enter_async_context(client),
                    timeout=MCP_REQUEST_TIMEOUT_SECONDS,
                )
                return client.is_connected()

        return await connect_client()
    except Exception as e:
        logger.debug(f"MCP protocol connect handshake failed: {e}")
        return False


async def test_mcp_connection(
    server_url: str,
    authorization_token: str | None = None,
    custom_headers: dict | None = None,
) -> bool:
    """Test connectivity to an MCP server using a lightweight initialize handshake.

    Returns True if the MCP initialize handshake succeeded, False otherwise.
    Does NOT call list_tools(), making it faster and lighter than
    mcp_server_health().
    """
    url_stripped = server_url.strip()
    headers = {}
    if authorization_token:
        headers["Authorization"] = authorization_token
    if custom_headers:
        headers.update(custom_headers)

    return await _mcp_protocol_connect(url_stripped, headers)


async def check_mcp_health_and_update_db(
    mcp_url, service_name, tenant_id, user_id
) -> None:
    """Check MCP health and update database status.

    Args:
        mcp_url: MCP server URL
        service_name: MCP service name
        tenant_id: Tenant ID
        user_id: User ID

    Raises:
        MCPConnectionError: If MCP connection fails
    """
    authorization_token = get_mcp_authorization_token_by_name_and_url(
        mcp_name=service_name, mcp_server=mcp_url, tenant_id=tenant_id
    )
    custom_headers = get_mcp_custom_headers_by_name_and_url(
        mcp_name=service_name, mcp_server=mcp_url, tenant_id=tenant_id
    )

    try:
        status = await mcp_server_health(
            remote_mcp_server=mcp_url,
            authorization_token=authorization_token,
            custom_headers=custom_headers,
        )
    except BaseException:
        status = False

    update_mcp_status_by_name_and_url(
        mcp_name=service_name,
        mcp_server=mcp_url,
        tenant_id=tenant_id,
        user_id=user_id,
        status=status,
    )
    if not status:
        raise MCPConnectionError("MCP connection failed")


async def check_mcp_service_health(
    *,
    tenant_id: str,
    user_id: str,
    mcp_id: int,
) -> str:
    """Check MCP service health by ID.

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        mcp_id: MCP record ID

    Returns:
        "healthy" if MCP is reachable

    Raises:
        McpNotFoundError: If MCP record is not found
        McpValidationError: If MCP server URL is empty
        MCPConnectionError: If MCP connection fails
    """
    record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not record:
        raise McpNotFoundError("MCP record not found")

    server_url = record.get("mcp_server")
    if not server_url:
        raise McpValidationError("MCP server URL is empty")

    # API-type MCPs are plain HTTP APIs described by OpenAPI JSON and have no
    # MCP protocol endpoint, so skip the MCP protocol handshake and treat them
    # as healthy (consistent with the enable/disable path).
    config_json = record.get("config_json")
    if isinstance(config_json, dict) and "openapi" in config_json:
        update_mcp_record_status_by_id(
            mcp_id=mcp_id,
            tenant_id=tenant_id,
            user_id=user_id,
            status=True,
        )
        return "healthy"

    authorization_token = record.get("authorization_token")
    custom_headers = record.get("custom_headers")

    try:
        status = await mcp_server_health(
            remote_mcp_server=server_url,
            authorization_token=authorization_token,
            custom_headers=custom_headers,
        )
    except MCPConnectionError:
        update_mcp_record_status_by_id(
            mcp_id=mcp_id,
            tenant_id=tenant_id,
            user_id=user_id,
            status=False,
        )
        raise
    except Exception as exc:
        logger.error(f"MCP health check failed: {exc}")
        update_mcp_record_status_by_id(
            mcp_id=mcp_id,
            tenant_id=tenant_id,
            user_id=user_id,
            status=False,
        )
        raise MCPConnectionError(str(exc) or "MCP connection failed")

    update_mcp_record_status_by_id(
        mcp_id=mcp_id,
        tenant_id=tenant_id,
        user_id=user_id,
        status=status,
    )

    if not status:
        raise MCPConnectionError("MCP connection failed")

    return "healthy"
