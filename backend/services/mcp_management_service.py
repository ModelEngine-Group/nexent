import logging
from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import urlencode

import aiohttp

from consts.exceptions import (
    MCPConnectionError,
    McpNameConflictError,
    McpNotFoundError,
    McpValidationError,
    UnauthorizedError,
)
from database.market_mcp_db import (
    check_mcp_market_name_exists,
    create_mcp_market_record,
    delete_mcp_market_record_by_id,
    get_mcp_market_record_by_id,
    get_mcp_market_records,
    get_mcp_market_tag_stats,
    list_mcp_market_records_by_tenant_and_user,
    update_mcp_market_record_version,
)
from database.market_review_db import (
    create_mcp_market_review,
    get_mcp_market_review_by_id,
    list_mcp_market_review_records,
    list_mcp_market_review_records_by_market_id,
    list_mcp_market_review_records_by_tenant_and_user,
    update_mcp_market_review_market_id,
    update_mcp_market_review_status,
)
from database.remote_mcp_db import (
    clear_mcp_record_market_id,
    get_mcp_record_by_id_and_tenant,
    update_mcp_record_market_id_by_id,
)
from database.user_tenant_db import get_user_tenant_by_user_id

logger = logging.getLogger("mcp_management_service")

MCP_REGISTRY_BASE_URL = "https://registry.modelcontextprotocol.io/v0.1/servers"
MCP_SMITHERY_BASE_URL = "https://api.smithery.ai/servers"
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


def _resolve_author_display_name(user_id: str | None) -> str | None:
    """Resolve a user ID to a display name (email) for author display."""
    if not user_id:
        return None
    user_tenant = get_user_tenant_by_user_id(user_id) or {}
    email = str(user_tenant.get("user_email") or "").strip()
    return email or None


def _to_community_card(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "communityId": row.get("market_id") or row.get("review_id"),
        "marketId": row.get("market_id"),
        "reviewId": row.get("review_id"),
        "sourceMcpId": row.get("source_mcp_id"),
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
        "reviewStatus": row.get("review_status") if "review_status" in row else MCP_REVIEW_APPROVED,
        "reviewType": row.get("review_type") or MCP_REVIEW_TYPE_INITIAL_LISTING,
        "previousVersion": row.get("previous_version"),
        "pendingVersion": row.get("version") if row.get("review_status") == MCP_REVIEW_PENDING else None,
        "installCount": row.get("download_count") or 0,
        "authorDisplayName": _resolve_author_display_name(row.get("user_id")),
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
    db_result = get_mcp_market_records(
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
    return get_mcp_market_tag_stats()


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
    """Submit an initial listing review for a local MCP service.

    Creates a review record (not a market record). The market record is created
    only when an admin approves the review.

    Returns the review_id.
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

    community_transport_type = "container" if final_config_json is not None else "url"

    # Check name uniqueness in the community market — globally across all tenants
    if check_mcp_market_name_exists(final_name):
        raise McpNameConflictError(f"MCP name '{final_name}' already exists in the community market")

    review_id = create_mcp_market_review(
        mcp_data={
            "mcp_name": final_name,
            "source_mcp_id": mcp_id,
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
    return review_id


async def update_community_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    market_id: int,
    name: str | None,
    description: str | None,
    tags: List[str] | None,
    version: str | None,
    registry_json: Dict[str, Any] | None,
    mcp_server: str | None = None,
    config_json: Dict[str, Any] | None = None,
    transport_type: str | None = None,
) -> None:
    """Submit a version update review for a published market MCP.

    Creates a review record with review_type='version_update'. The market record
    is NOT modified until an admin approves the review.

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        market_id: Market record ID
        name: New MCP service name
        description: MCP service description
        tags: MCP tags
        version: New version being submitted
        registry_json: Registry metadata JSON
        mcp_server: MCP server URL
        config_json: Container MCP configuration JSON
        transport_type: Transport type

    Raises:
        McpNotFoundError: If market MCP record is not found
    """
    current = get_mcp_market_record_by_id(market_id=market_id)
    if not current:
        raise McpNotFoundError("Market MCP record not found")

    existing_config_json = current.get("config_json") if isinstance(current.get("config_json"), dict) else None
    next_registry_json = registry_json if isinstance(registry_json, dict) else (current.get("registry_json") or {})
    next_config_json = config_json if isinstance(config_json, dict) else existing_config_json
    next_transport_type = transport_type
    if next_transport_type is None and isinstance(config_json, dict):
        next_transport_type = "container"
    if next_transport_type is None and mcp_server is not None:
        next_transport_type = "url"

    # Check name uniqueness in the market if the name is changing
    if name is not None and name != current.get("mcp_name") and check_mcp_market_name_exists(name):
        raise McpNameConflictError(f"MCP name '{name}' already exists in the community market")

    create_mcp_market_review(
        mcp_data={
            "market_id": market_id,
            "mcp_name": name,
            "mcp_server": mcp_server,
            "version": version,
            "registry_json": next_registry_json,
            "transport_type": next_transport_type,
            "config_json": next_config_json,
            "review_status": MCP_REVIEW_PENDING,
            "review_type": MCP_REVIEW_TYPE_VERSION_UPDATE,
            "previous_version": current.get("version"),
            "tags": tags,
            "description": description,
        },
        tenant_id=tenant_id,
        user_id=user_id,
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
    db_result = list_mcp_market_review_records(
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
    review_id: int,
) -> None:
    """Approve a review submission.

    For initial_listing: creates a market record and links the review to it.
    For version_update: updates the existing market record's version/registry_json.
    """
    review_tenant_id = _get_mcp_review_admin_scope(user_id, tenant_id)
    current = get_mcp_market_review_by_id(review_id=review_id, tenant_id=review_tenant_id)
    if not current:
        raise McpNotFoundError("Review record not found")

    review_type = current.get("review_type") or MCP_REVIEW_TYPE_INITIAL_LISTING

    if review_type == MCP_REVIEW_TYPE_INITIAL_LISTING:
        # Promote to market: create a market record from the review data
        market_id = create_mcp_market_record(
            mcp_data={
                "mcp_name": current.get("mcp_name"),
                "mcp_server": current.get("mcp_server"),
                "version": current.get("version"),
                "registry_json": current.get("registry_json"),
                "transport_type": current.get("transport_type"),
                "config_json": current.get("config_json"),
                "tags": current.get("tags"),
                "description": current.get("description"),
            },
            tenant_id=current.get("tenant_id"),
            user_id=current.get("user_id"),
        )
        # Link the review to the market record
        update_mcp_market_review_market_id(
            review_id=review_id,
            market_id=market_id,
            user_id=user_id,
        )
        source_mcp_id = current.get("source_mcp_id")
        if source_mcp_id is not None:
            update_mcp_record_market_id_by_id(
                mcp_id=source_mcp_id,
                tenant_id=current.get("tenant_id"),
                user_id=current.get("user_id"),
                market_id=market_id,
            )
    else:
        # Version update: update the existing market record
        market_id = current.get("market_id")
        if market_id is None:
            raise McpNotFoundError("Market record not found for version update")
        update_mcp_market_record_version(
            market_id=market_id,
            version=current.get("version"),
            registry_json=current.get("registry_json"),
            user_id=user_id,
        )

    # Mark review as approved
    update_mcp_market_review_status(
        review_id=review_id,
        tenant_id=review_tenant_id,
        user_id=user_id,
        review_status=MCP_REVIEW_APPROVED,
    )


async def reject_community_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    review_id: int,
) -> None:
    review_tenant_id = _get_mcp_review_admin_scope(user_id, tenant_id)
    current = get_mcp_market_review_by_id(review_id=review_id, tenant_id=review_tenant_id)
    if not current:
        raise McpNotFoundError("Review record not found")
    update_mcp_market_review_status(
        review_id=review_id,
        tenant_id=review_tenant_id,
        user_id=user_id,
        review_status=MCP_REVIEW_REJECTED,
    )


async def delete_community_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    market_id: int,
) -> None:
    """Delete a market MCP service and all its associated reviews.

    Handles both approved records (in mcp_market_record_t) and pending
    review records (in mcp_market_review_t). When a record exists only as
    a pending review (no market record yet), it deletes the review directly.

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        market_id: Market record ID (or review record ID for pending items)

    Raises:
        McpNotFoundError: If neither a market nor review record is found
    """
    current = get_mcp_market_record_by_id(market_id=market_id)
    if current:
        # Approved record — soft-delete the market record
        delete_mcp_market_record_by_id(
            market_id=market_id,
            user_id=user_id,
        )
        # Soft-delete all associated reviews
        for review in list_mcp_market_review_records_by_market_id(market_id=market_id):
            update_mcp_market_review_status(
                review_id=review.get("review_id"),
                tenant_id=None,
                user_id=user_id,
                review_status=MCP_REVIEW_REJECTED,
            )
        # Clear FK references from local MCP records
        clear_mcp_record_market_id(
            tenant_id=tenant_id,
            user_id=user_id,
            market_id=market_id,
        )
        return

    # Not found in market table — check review table (pending / unapproved item)
    review = get_mcp_market_review_by_id(review_id=market_id, tenant_id=None)
    if review:
        update_mcp_market_review_status(
            review_id=market_id,
            tenant_id=None,
            user_id=user_id,
            review_status=MCP_REVIEW_REJECTED,
        )
        return

    raise McpNotFoundError("Market MCP record not found")


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
    market_rows = list_mcp_market_records_by_tenant_and_user(
        tenant_id=tenant_id,
        user_id=user_id,
    )
    review_rows = list_mcp_market_review_records_by_tenant_and_user(
        tenant_id=tenant_id,
        user_id=user_id,
        include_approved=True,
    )
    source_mcp_id_by_market_id = {
        row.get("market_id"): row.get("source_mcp_id")
        for row in review_rows
        if row.get("review_status") == MCP_REVIEW_APPROVED
        and row.get("market_id") is not None
        and row.get("source_mcp_id") is not None
    }
    enriched_market_rows = [
        {**row, "source_mcp_id": source_mcp_id_by_market_id.get(row.get("market_id"))}
        for row in market_rows
    ]
    active_review_rows = [
        row for row in review_rows if row.get("review_status") != MCP_REVIEW_APPROVED
    ]
    items = [_to_community_card(row) for row in [*active_review_rows, *enriched_market_rows]]
    return {
        "count": len(items),
        "items": items,
    }


# ---------------------------------------------------------------------------
# Registry Functions
# ---------------------------------------------------------------------------

async def _list_official_registry_mcp_services(
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


async def _list_smithery_registry_mcp_services(
    *,
    search: str | None = None,
    cursor: str | None = None,
    limit: int = 30,
) -> Dict[str, Any]:
    """List MCP services from the Smithery registry.

    Args:
        search: Search keyword (searches by displayName/qualifiedName client-side)
        cursor: Smithery page number (cursor is "page-N")
        limit: Items per page

    Returns:
        Dictionary with servers and metadata compatible with the official registry format
    """
    page = 1
    if cursor and cursor.startswith("page-"):
        try:
            page = int(cursor.split("page-", 1)[1])
        except (ValueError, IndexError):
            page = 1

    params: Dict[str, Any] = {"pageSize": limit}
    request_url = f"{MCP_SMITHERY_BASE_URL}?{urlencode(params)}&page={page}"
    timeout = aiohttp.ClientTimeout(total=20)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
        async with session.get(request_url, headers=headers) as response:
            if response.status >= 400:
                raise RuntimeError(f"Smithery request failed with status {response.status}")
            payload = await response.json(content_type=None)

    raw_servers = payload.get("servers") if isinstance(payload, dict) else []
    pagination = payload.get("pagination") if isinstance(payload, dict) else {}

    if not isinstance(raw_servers, list):
        return {"servers": [], "metadata": {}}

    total_pages = int(pagination.get("totalPages", 0)) if pagination else 0

    # Transform Smithery format to the frontend's expected format
    transformed = []
    for server in raw_servers:
        qualified_name = server.get("qualifiedName") or server.get("displayName") or ""
        display_name = server.get("displayName") or qualified_name
        description = server.get("description") or ""
        connections = server.get("connections") or []

        # Map connections to remotes
        remotes = []
        for conn in connections:
            if isinstance(conn, dict) and conn.get("deploymentUrl"):
                remotes.append({
                    "type": conn.get("type", "unknown"),
                    "url": conn.get("deploymentUrl"),
                })

        # Apply client-side search filter since Smithery doesn't support server-side search
        if search:
            search_lower = search.lower()
            if search_lower not in qualified_name.lower() and search_lower not in display_name.lower() and search_lower not in description.lower():
                continue

        transformed.append({
            "server": {
                "name": display_name,
                "qualifiedName": qualified_name,
                "description": description,
                "remotes": remotes,
                "packages": [],
            },
            "_meta": {
                "source": "smithery",
                "qualifiedName": qualified_name,
            },
        })

    next_cursor = f"page-{page + 1}" if page < total_pages else None

    return {
        "servers": transformed,
        "metadata": {"nextCursor": next_cursor},
    }


async def _get_smithery_server_detail(
    qualified_name: str,
) -> Dict[str, Any] | None:
    """Fetch detail for a single Smithery server by qualifiedName.

    The Smithery detail endpoint returns connections (with deployment URLs)
    and tools, which are not available in the list endpoint.

    Args:
        qualified_name: The Smithery qualifiedName (e.g. "exa", "@smithery-ai/server-slack")

    Returns:
        Transformed server dict matching RegistryMcpCard format, or None if not found
    """
    request_url = f"{MCP_SMITHERY_BASE_URL}/{qualified_name}"
    timeout = aiohttp.ClientTimeout(total=15)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
        async with session.get(request_url, headers=headers) as response:
            if response.status == 404:
                return None
            if response.status >= 400:
                raise RuntimeError(f"Smithery detail request failed with status {response.status}")
            server = await response.json(content_type=None)

    if not isinstance(server, dict):
        return None

    qualified_name = server.get("qualifiedName") or ""
    display_name = server.get("displayName") or qualified_name
    description = server.get("description") or ""
    connections = server.get("connections") or []

    remotes = []
    for conn in connections:
        if isinstance(conn, dict) and conn.get("deploymentUrl"):
            remote: Dict[str, Any] = {
                "type": conn.get("type", "unknown"),
                "url": conn.get("deploymentUrl"),
            }

            # Map configSchema to variables format expected by the frontend
            config_schema = conn.get("configSchema")
            if isinstance(config_schema, dict):
                required_fields = config_schema.get("required", [])
                properties = config_schema.get("properties", {})
                variables = {}
                for field_name, field_schema in properties.items():
                    if isinstance(field_schema, dict):
                        is_required = field_name in required_fields
                        variable = {
                            "description": field_schema.get("description", ""),
                            "isRequired": is_required,
                            "isSecret": field_schema.get("format") == "password" or field_schema.get("x-secret", False),
                        }
                        if field_schema.get("default"):
                            variable["default"] = field_schema["default"]
                        if field_schema.get("title"):
                            variable["label"] = field_schema["title"]
                        variables[field_name] = variable
                if variables:
                    remote["variables"] = variables

            remotes.append(remote)

    return {
        "server": {
            "name": display_name,
            "qualifiedName": qualified_name,
            "description": description,
            "remotes": remotes,
            "packages": [],
        },
        "_meta": {
            "source": "smithery",
            "qualifiedName": qualified_name,
        },
    }


async def list_registry_mcp_services(
    *,
    search: str | None = None,
    include_deleted: bool = False,
    updated_since: str | None = None,
    version: str | None = None,
    cursor: str | None = None,
    limit: int = 30,
    source: str = "official",
    detail_qualified_name: str | None = None,
) -> Dict[str, Any]:
    """List MCP services from the configured registry source.

    Args:
        search: Search keyword
        include_deleted: Include deleted records
        updated_since: Filter by update time
        version: Filter by version
        cursor: Pagination cursor
        limit: Items per page
        source: Registry source ("official" or "smithery")
        detail_qualified_name: Fetch detail for a single server by qualifiedName (Smithery only)

    Returns:
        Dictionary with servers and metadata
    """
    if detail_qualified_name and source == "smithery":
        server = await _get_smithery_server_detail(detail_qualified_name)
        return {
            "servers": [server] if server else [],
            "metadata": {},
        }

    if source == "smithery":
        return await _list_smithery_registry_mcp_services(
            search=search,
            cursor=cursor,
            limit=limit,
        )
    return await _list_official_registry_mcp_services(
        search=search,
        include_deleted=include_deleted,
        updated_since=updated_since,
        version=version,
        cursor=cursor,
        limit=limit,
    )
