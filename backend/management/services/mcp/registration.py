# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contracts.errors.exceptions import MCPConnectionError, MCPNameIllegal
from management.db.mcp.remote import check_mcp_name_exists, create_mcp_record
from management.services.mcp.common import logger
from management.services.mcp.health import _mcp_protocol_health_check


async def add_remote_mcp_server_list(
    tenant_id: str,
    user_id: str,
    remote_mcp_server: str,
    remote_mcp_server_name: str,
    container_id: str | None = None,
    authorization_token: str | None = None,
    custom_headers: dict | None = None,
    ssl_verify: bool = True,
    source: str | None = "local",
    container_port: int | None = None,
    group_ids: str | None = None,
    ingroup_permission: str | None = None,
    shared_fields: dict | None = None,
):
    """Add a remote MCP server to the list.

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        remote_mcp_server: MCP server URL
        remote_mcp_server_name: MCP service name
        container_id: Docker container ID (optional)
        authorization_token: Authorization token (optional)
        custom_headers: Custom HTTP headers (optional)

    Raises:
        MCPNameIllegal: If MCP name already exists
        MCPConnectionError: If MCP server is not reachable
    """
    if check_mcp_name_exists(mcp_name=remote_mcp_server_name, tenant_id=tenant_id):
        logger.error(f"MCP name already exists: {remote_mcp_server_name}")
        raise MCPNameIllegal("MCP name already exists")

    headers = {}
    if authorization_token:
        headers["Authorization"] = authorization_token
    if custom_headers:
        headers.update(custom_headers)

    tool_names = await _mcp_protocol_health_check(remote_mcp_server.strip(), headers)
    if not tool_names:
        raise MCPConnectionError("MCP connection failed")

    insert_mcp_data = {
        "mcp_name": remote_mcp_server_name,
        "mcp_server": remote_mcp_server,
        "status": True,
        "container_id": container_id,
        "authorization_token": authorization_token,
        "custom_headers": custom_headers,
        "source": source,
        "container_port": container_port,
        "registry_json": {"_toolNames": tool_names},
        "group_ids": group_ids,
        "ingroup_permission": ingroup_permission,
        "shared_fields": shared_fields,
    }
    create_mcp_record(mcp_data=insert_mcp_data, tenant_id=tenant_id, user_id=user_id)


def _build_mcp_headers(
    authorization_token: str | None,
    custom_headers: dict | None,
) -> dict:
    headers = {}
    if authorization_token:
        headers["Authorization"] = authorization_token
    if custom_headers:
        headers.update(custom_headers)
    return headers


async def _check_mcp_connectivity(
    server_url: str,
    headers: dict,
    is_container: bool,
    name: str,
) -> list[str] | None:
    tool_names = await _mcp_protocol_health_check(server_url.strip(), headers)
    if not tool_names:
        if is_container:
            logger.warning(
                "Container MCP service %s is not reachable yet, "
                "tool count will be unavailable until the next refresh",
                name,
            )
            return None
        raise MCPConnectionError(
            "MCP server is unreachable or does not support MCP protocol"
        )
    return tool_names


async def add_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    name: str,
    description: str | None,
    source: str,
    server_url: str,
    tags: list | None,
    authorization_token: str | None,
    custom_headers: dict | None = None,
    container_config: dict | None,
    registry_json: dict | None,
    config_json: dict | None = None,
    market_id: int | None = None,
    enabled: bool = False,
    container_id: str | None = None,
    container_port: int | None = None,
    group_ids: str | None = None,
    ingroup_permission: str | None = None,
    shared_fields: dict | None = None,
    skip_health_check: bool = False,
) -> None:
    """Add an MCP service record.

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        name: MCP service name
        description: MCP service description
        source: Source type (local/mcp_registry/community)
        server_url: MCP server URL
        tags: MCP tags
        authorization_token: Authorization token for MCP server
        custom_headers: Custom HTTP headers
        container_config: Container configuration
        registry_json: Registry metadata JSON
        config_json: MCP configuration JSON (e.g. OpenAPI spec for API-type MCP)
        market_id: Linked market record ID
        enabled: Whether the MCP is enabled
        container_id: Docker container ID
        container_port: Container port
        group_ids: Comma-separated group IDs that can access this MCP
        ingroup_permission: Permission level: EDIT, READ_ONLY, PRIVATE
    """
    status: bool | None = None
    normalized_container_id = (
        container_id if isinstance(container_id, str) and container_id else None
    )
    is_container = container_id is not None or container_config is not None
    resolved_config_json = (
        container_config
        if is_container and isinstance(container_config, dict)
        else config_json
    )

    if check_mcp_name_exists(mcp_name=name, tenant_id=tenant_id):
        logger.error(f"MCP name already exists: {name}")
        raise MCPNameIllegal("MCP name already exists")

    resolved_registry_json = registry_json or {}
    if server_url:
        # API-type MCPs use OpenAPI JSON, not MCP protocol
        is_api = (
            isinstance(resolved_config_json, dict) and "openapi" in resolved_config_json
        )
        if is_api:
            # Register OpenAPI service (same as agent config flow)
            try:
                from management.services.tool.configuration import (
                    _refresh_openapi_services_in_mcp,
                    import_openapi_service,
                    update_tool_list,
                )

                import_openapi_service(
                    service_name=name,
                    openapi_json=resolved_config_json,
                    server_url=server_url,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    service_description=description,
                    auth_enabled=bool(custom_headers),
                    headers_template=custom_headers,
                    ssl_verify=ssl_verify,
                    force_update=True,
                )
                _refresh_openapi_services_in_mcp(tenant_id)
                # Keep the persisted tool catalog in sync with the tenant MCP runtime.
                # The agent configuration page reads /tool/list from this catalog.
                await update_tool_list(tenant_id=tenant_id, user_id=user_id)
            except Exception as exc:
                logger.warning(f"Failed to register OpenAPI service '{name}': {exc}")
            # Extract tool names from OpenAPI spec for display
            api_tools = []
            paths = resolved_config_json.get("paths", {}) or {}
            for path, methods in paths.items():
                if isinstance(methods, dict):
                    for method_name, detail in methods.items():
                        if isinstance(detail, dict):
                            tool_name = (
                                detail.get("operationId") or detail.get("summary") or ""
                            )
                            if tool_name:
                                api_tools.append(tool_name)
            if api_tools:
                resolved_registry_json["_toolNames"] = api_tools
        else:
            headers = _build_mcp_headers(authorization_token, custom_headers)
            if not skip_health_check:
                tool_names = await _check_mcp_connectivity(
                    server_url, headers, is_container, name
                )
                if tool_names:
                    resolved_registry_json["_toolNames"] = tool_names

    if enabled:
        status = True

    create_mcp_record(
        mcp_data={
            "mcp_name": name,
            "mcp_server": server_url,
            "status": status,
            "container_id": normalized_container_id,
            "container_port": container_port,
            "authorization_token": authorization_token,
            "custom_headers": custom_headers,
            "source": source,
            "registry_json": resolved_registry_json,
            "market_id": market_id,
            "enabled": enabled,
            "tags": tags,
            "description": description,
            "config_json": resolved_config_json,
            "group_ids": group_ids,
            "ingroup_permission": ingroup_permission,
            "shared_fields": shared_fields,
        },
        tenant_id=tenant_id,
        user_id=user_id,
    )
