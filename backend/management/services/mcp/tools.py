# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from consts.exceptions import MCPConnectionError, McpNotFoundError, McpValidationError
from database.market_mcp_db import (
    get_mcp_market_record_by_source_mcp_id,
    update_mcp_market_record,
)
from database.remote_mcp_db import (
    get_mcp_record_by_id_and_tenant,
    update_mcp_record_registry_json_by_id,
)


async def list_mcp_service_tools_by_id(*, tenant_id: str, mcp_id: int) -> list[dict]:
    """Get tools from an MCP service by ID.

    For API-type MCPs (OpenAPI), tools are already registered in the database
    via import_openapi_service.  Return them from the tool registry instead of
    attempting an MCP-protocol connection.

    Args:
        tenant_id: Tenant ID
        mcp_id: MCP record ID

    Returns:
        List of tool dictionaries

    Raises:
        McpNotFoundError: If MCP record is not found
        McpValidationError: If MCP record is missing connection fields
        MCPConnectionError: If MCP connection fails
    """
    record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not record:
        raise McpNotFoundError("MCP record not found")

    config_json = record.get("config_json")
    registry_json = record.get("registry_json")
    is_api_type = isinstance(config_json, dict) and "openapi" in config_json
    if is_api_type:
        # API-type MCPs have no MCP protocol endpoint.
        # Return the tool names that were extracted during registration.
        tool_names = []
        if isinstance(registry_json, dict):
            raw = registry_json.get("_toolNames")
            if isinstance(raw, list):
                tool_names = raw
        return [{"name": name, "description": ""} for name in tool_names]

    service_name = record.get("mcp_name")
    server_url = record.get("mcp_server")
    if not service_name or not server_url:
        raise McpValidationError("MCP record is missing runtime connection fields")

    authorization_token = record.get("authorization_token")
    custom_headers = record.get("custom_headers")

    from management.services.tool.discovery import get_tool_from_remote_mcp_server

    tools_info = await get_tool_from_remote_mcp_server(
        mcp_server_name=service_name,
        remote_mcp_server=server_url,
        tenant_id=tenant_id,
        authorization_token=authorization_token,
        custom_headers=custom_headers,
    )
    return [tool.__dict__ for tool in tools_info]


async def refresh_mcp_service_tool_count(
    *,
    tenant_id: str,
    user_id: str,
    mcp_id: int,
) -> list[str]:
    """Connect to the MCP server and persist a complete tool snapshot.

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        mcp_id: MCP record ID

    Returns:
        List of tool names

    Raises:
        McpNotFoundError: If MCP record is not found
        McpValidationError: If MCP record has no server URL
        MCPConnectionError: If MCP connection fails
    """
    record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not record:
        raise McpNotFoundError("MCP record not found")

    server_url = record.get("mcp_server")
    if not server_url:
        raise McpValidationError("MCP record has no server URL to connect to")

    authorization_token = record.get("authorization_token")
    custom_headers = record.get("custom_headers")

    # Skip MCP protocol check for API-type MCPs (they use OpenAPI JSON, not MCP)
    config_json = record.get("config_json")
    if isinstance(config_json, dict) and "openapi" in config_json:
        return

    headers = {}
    if authorization_token:
        headers["Authorization"] = authorization_token
    if custom_headers:
        headers.update(custom_headers)

    tool_names = await _mcp_protocol_health_check(server_url, headers)
    if not tool_names:
        raise MCPConnectionError(
            "MCP server is unreachable or does not support MCP protocol"
        )

    service_name = record.get("mcp_name")
    if not service_name:
        raise McpValidationError("MCP record is missing service name")

    from management.services.tool.discovery import get_tool_from_remote_mcp_server

    tools_info = await get_tool_from_remote_mcp_server(
        mcp_server_name=service_name,
        remote_mcp_server=server_url,
        tenant_id=tenant_id,
        authorization_token=authorization_token,
        custom_headers=custom_headers,
    )
    tool_snapshot = [
        {"name": tool.name, "description": tool.description or ""}
        for tool in tools_info
        if getattr(tool, "name", "")
    ]
    if tool_snapshot:
        tool_names = [tool["name"] for tool in tool_snapshot]

    registry_json = record.get("registry_json") or {}
    registry_json["_toolNames"] = tool_names
    registry_json["tools"] = tool_snapshot

    update_mcp_record_registry_json_by_id(
        mcp_id=mcp_id,
        tenant_id=tenant_id,
        user_id=user_id,
        registry_json=registry_json,
    )

    # A published MCP stores the tool snapshot in the market row. Keep it in
    # sync so repository details show both the current count and descriptions.
    market_id = record.get("market_id")
    if market_id is None:
        market = get_mcp_market_record_by_source_mcp_id(
            tenant_id=tenant_id,
            source_mcp_id=mcp_id,
        )
        market_id = market.get("market_id") if market else None
    if market_id is not None:
        update_mcp_market_record(
            market_id=market_id,
            user_id=user_id,
            registry_json=registry_json,
        )
    return tool_names


from management.services.mcp.health import (
    _mcp_protocol_health_check,
)
