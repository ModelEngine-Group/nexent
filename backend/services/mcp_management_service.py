import logging
from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import urlencode

import aiohttp

from consts.exceptions import (
    MCPConnectionError,
    McpNotFoundError,
    McpValidationError,
    UnauthorizedError,
)
from database.community_mcp_db import (
    create_mcp_community_record,
    delete_mcp_community_record_by_id,
    get_mcp_community_record_by_id_and_tenant,
    get_mcp_community_records,
    get_mcp_community_tag_stats,
    list_mcp_community_records_by_tenant_and_user,
    list_mcp_community_review_records,
    update_mcp_community_record_by_id,
    update_mcp_community_review_status,
)
from database.remote_mcp_db import (
    clear_mcp_record_community_id,
    get_mcp_record_by_id_and_tenant,
    update_mcp_record_community_id_by_id,
)
from database.user_tenant_db import get_user_tenant_by_user_id

logger = logging.getLogger("mcp_management_service")

MCP_REGISTRY_BASE_URL = "https://registry.modelcontextprotocol.io/v0.1/servers"
MCP_REVIEW_PENDING = "pending"
MCP_REVIEW_APPROVED = "approved"
MCP_REVIEW_REJECTED = "rejected"
MCP_REVIEW_TYPE_INITIAL_LISTING = "initial_listing"
MCP_REVIEW_TYPE_VERSION_UPDATE = "version_update"
ADMIN_ROLES = {"ADMIN", "SUPER_ADMIN", "SU"}
SUPER_ADMIN_ROLES = {"SUPER_ADMIN", "SU"}


def _get_mcp_review_admin_scope(user_id: str, tenant_id: str) -> str | None:
    user_tenant = get_user_tenant_by_user_id(user_id)
    user_role = (user_tenant or {}).get("user_role", "").upper()
    if user_role not in ADMIN_ROLES:
        raise UnauthorizedError("Only administrators can review MCP submissions")
    if user_role in SUPER_ADMIN_ROLES:
        return None
    return tenant_id


def _to_community_card(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "communityId": row.get("community_id"),
        "name": row.get("mcp_name"),
        "version": row.get("version"),
        "description": row.get("description"),
        "status": "active",
        "createdAt": row.get("create_time"),
        "updatedAt": row.get("update_time"),
        "source": "community",
        "transportType": row.get("transport_type"),
        "serverUrl": row.get("mcp_server"),
        "configJson": row.get("config_json") if isinstance(row.get("config_json"), dict) else None,
        "registryJson": row.get("registry_json") if isinstance(row.get("registry_json"), dict) else None,
        "tags": row.get("tags") or [],
        "reviewStatus": row.get("review_status") or MCP_REVIEW_PENDING,
        "reviewType": row.get("review_type") or MCP_REVIEW_TYPE_INITIAL_LISTING,
    }


# ---------------------------------------------------------------------------
# Community MCP Service Functions
# ---------------------------------------------------------------------------

async def list_community_mcp_services(
    *,
    search: str | None = None,
    tag: str | None = None,
    transport_type: str | None = None,
    cursor: str | None = None,
    limit: int = 30,
) -> Dict[str, Any]:
    """List public community MCP services.

    Args:
        search: Search keyword
        tag: Filter by tag
        transport_type: Filter by transport (url or container)
        cursor: Pagination cursor
        limit: Items per page

    Returns:
        Dictionary with count, nextCursor, and items
    """
    db_result = get_mcp_community_records(
        search=search,
        tag=tag,
        transport_type=transport_type,
        cursor=cursor,
        limit=limit,
    )

    raw_items = db_result.get("items", [])
    items = [_to_community_card(item) for item in raw_items]
    return {
        "count": len(items),
        "nextCursor": db_result.get("nextCursor"),
        "items": items,
    }


def list_community_mcp_tag_stats() -> List[Dict[str, Any]]:
    """Get community MCP tag statistics.

    Args:
        tenant_id: Tenant ID

    Returns:
        List of tag statistics
    """
    return get_mcp_community_tag_stats()


async def publish_community_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    mcp_id: int,
    name: str | None = None,
    description: str | None = None,
    version: str | None = None,
    tags: List[str] | None = None,
    mcp_server: str | None = None,
    config_json: Dict[str, Any] | None = None,
) -> int:
    """Publish a local MCP service to the community.

    Optional ``name`` / ``description`` / ``version`` / ``tags`` / ``mcp_server`` /
    ``config_json`` override the values copied from the local MCP row when creating
    the community record. Omit an optional field (``None``) to keep the local MCP
    value for that field.

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        mcp_id: MCP record ID to publish
        name: Optional community display name override
        description: Optional description override
        version: Optional version override
        tags: Optional tags override
        mcp_server: Optional remote MCP URL override
        config_json: Optional container config override

    Returns:
        Community record ID

    Raises:
        McpNotFoundError: If MCP record is not found
    """
    source_record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not source_record:
        raise McpNotFoundError("MCP record not found")

    source_registry_json = source_record.get("registry_json") if isinstance(source_record.get("registry_json"), dict) else None
    source_config_json = source_record.get("config_json") if isinstance(source_record.get("config_json"), dict) else None

    final_name = name if name is not None else source_record.get("mcp_name")
    final_description = description if description is not None else source_record.get("description")
    final_version = version if version is not None else source_record.get("version")
    final_tags = tags if tags is not None else source_record.get("tags")
    final_mcp_server = (
        mcp_server if mcp_server is not None else source_record.get("mcp_server")
    )
    final_config_json = (
        config_json if isinstance(config_json, dict) else source_config_json
    )

    # Remote MCP table may omit transport_type; community list still needs it for filters.
    community_transport_type = "container" if final_config_json is not None else "url"

    community_id = create_mcp_community_record(
        mcp_data={
            "mcp_name": final_name,
            "mcp_server": final_mcp_server,
            "version": final_version,
            "registry_json": source_registry_json,
            "transport_type": source_record.get("transport_type") or community_transport_type,
            "config_json": final_config_json,
            "review_status": MCP_REVIEW_PENDING,
            "review_type": MCP_REVIEW_TYPE_INITIAL_LISTING,
            "tags": final_tags,
            "description": final_description,
        },
        tenant_id=tenant_id,
        user_id=user_id,
    )
    update_mcp_record_community_id_by_id(
        mcp_id=mcp_id,
        tenant_id=tenant_id,
        user_id=user_id,
        community_id=community_id,
    )
    return community_id


async def update_community_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    community_id: int,
    name: str | None,
    description: str | None,
    tags: List[str] | None,
    version: str | None,
    registry_json: Dict[str, Any] | None,
    mcp_server: str | None = None,
    config_json: Dict[str, Any] | None = None,
    transport_type: str | None = None,
) -> None:
    """Update a community MCP service.

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        community_id: Community record ID
        name: New MCP service name
        description: MCP service description
        tags: MCP tags
        version: MCP version
        registry_json: Registry metadata JSON
        mcp_server: MCP server URL
        config_json: Container MCP configuration JSON
        transport_type: Transport type

    Raises:
        McpNotFoundError: If community MCP record is not found
    """
    current = get_mcp_community_record_by_id_and_tenant(community_id=community_id, tenant_id=tenant_id)
    if not current:
        raise McpNotFoundError("Community MCP record not found")

    existing_config_json = current.get("config_json") if isinstance(current.get("config_json"), dict) else None
    next_registry_json = registry_json if isinstance(registry_json, dict) else current.get("registry_json")
    next_config_json = config_json if isinstance(config_json, dict) else existing_config_json
    next_transport_type = transport_type
    if next_transport_type is None and isinstance(config_json, dict):
        next_transport_type = "container"
    if next_transport_type is None and mcp_server is not None:
        next_transport_type = "url"

    update_mcp_community_record_by_id(
        community_id=community_id,
        tenant_id=tenant_id,
        user_id=user_id,
        name=name,
        description=description,
        tags=tags,
        version=version,
        registry_json=next_registry_json,
        config_json=next_config_json,
        mcp_server=mcp_server,
        transport_type=next_transport_type,
        review_status=MCP_REVIEW_PENDING,
        review_type=MCP_REVIEW_TYPE_VERSION_UPDATE,
    )


async def list_community_mcp_review_services(
    *,
    tenant_id: str,
    user_id: str,
    status: str | None = None,
    search: str | None = None,
    tag: str | None = None,
    transport_type: str | None = None,
    cursor: str | None = None,
    limit: int = 30,
) -> Dict[str, Any]:
    review_tenant_id = _get_mcp_review_admin_scope(user_id, tenant_id)
    db_result = list_mcp_community_review_records(
        tenant_id=review_tenant_id,
        status=status,
        search=search,
        tag=tag,
        transport_type=transport_type,
        cursor=cursor,
        limit=limit,
    )
    return {
        "count": db_result.get("count", 0),
        "nextCursor": db_result.get("nextCursor"),
        "items": [_to_community_card(item) for item in db_result.get("items", [])],
    }


async def approve_community_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    community_id: int,
) -> None:
    review_tenant_id = _get_mcp_review_admin_scope(user_id, tenant_id)
    current = get_mcp_community_record_by_id_and_tenant(community_id=community_id, tenant_id=review_tenant_id)
    if not current:
        raise McpNotFoundError("Community MCP record not found")
    update_mcp_community_review_status(
        community_id=community_id,
        tenant_id=review_tenant_id,
        user_id=user_id,
        review_status=MCP_REVIEW_APPROVED,
    )


async def reject_community_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    community_id: int,
) -> None:
    review_tenant_id = _get_mcp_review_admin_scope(user_id, tenant_id)
    current = get_mcp_community_record_by_id_and_tenant(community_id=community_id, tenant_id=review_tenant_id)
    if not current:
        raise McpNotFoundError("Community MCP record not found")
    update_mcp_community_review_status(
        community_id=community_id,
        tenant_id=review_tenant_id,
        user_id=user_id,
        review_status=MCP_REVIEW_REJECTED,
    )


async def delete_community_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    community_id: int,
) -> None:
    """Delete a community MCP service.

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        community_id: Community record ID

    Raises:
        McpNotFoundError: If community MCP record is not found
    """
    current = get_mcp_community_record_by_id_and_tenant(community_id=community_id, tenant_id=tenant_id)
    if not current:
        raise McpNotFoundError("Community MCP record not found")
    delete_mcp_community_record_by_id(
        community_id=community_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    clear_mcp_record_community_id(
        tenant_id=tenant_id,
        user_id=user_id,
        community_id=community_id,
    )


async def list_my_community_mcp_services(
    *,
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """List MCP services published by the current user to the community.

    Args:
        tenant_id: Tenant ID
        user_id: User ID

    Returns:
        Dictionary with count and items
    """
    rows = list_mcp_community_records_by_tenant_and_user(
        tenant_id=tenant_id,
        user_id=user_id,
    )
    items = [_to_community_card(row) for row in rows]
    return {
        "count": len(items),
        "items": items,
    }


# ---------------------------------------------------------------------------
# Registry Functions
# ---------------------------------------------------------------------------

async def list_registry_mcp_services(
    *,
    search: str | None = None,
    include_deleted: bool = False,
    updated_since: str | None = None,
    version: str | None = None,
    cursor: str | None = None,
    limit: int = 30,
) -> Dict[str, Any]:
    """List MCP services from the official MCP Registry.

    Args:
        search: Search keyword
        include_deleted: Include deleted records
        updated_since: Filter by update time
        version: Filter by version
        cursor: Pagination cursor
        limit: Items per page

    Returns:
        Dictionary with servers and metadata
    """
    params: Dict[str, Any] = {"limit": limit}
    if search:
        params["search"] = search
    if include_deleted:
        params["include_deleted"] = "true"
    if updated_since:
        params["updated_since"] = updated_since
    if version:
        params["version"] = version
    if cursor:
        params["cursor"] = cursor

    request_url = f"{MCP_REGISTRY_BASE_URL}?{urlencode(params)}"
    timeout = aiohttp.ClientTimeout(total=20)

    async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
        async with session.get(request_url) as response:
            if response.status >= 400:
                raise RuntimeError(f"Registry request failed with status {response.status}")
            payload = await response.json(content_type=None)

    raw_servers = payload.get("servers") if isinstance(payload, dict) else []
    metadata = payload.get("metadata") if isinstance(payload, dict) and isinstance(payload.get("metadata"), dict) else {}

    return {
        "servers": raw_servers if isinstance(raw_servers, list) else [],
        "metadata": metadata,
    }
