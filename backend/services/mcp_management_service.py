import logging
from datetime import datetime
from typing import Any, Dict, FrozenSet, List, Tuple
from urllib.parse import urlencode

import aiohttp

from consts.const import CAN_EDIT_ALL_USER_ROLES
from consts.exceptions import (
    MCPConnectionError,
    McpNameConflictError,
    McpNotFoundError,
    McpValidationError,
    UnauthorizedError,
)
from consts.mcp_market import (
    STATUS_NOT_SHARED,
    STATUS_PENDING_REVIEW,
    STATUS_REJECTED,
    STATUS_SHARED,
    VALID_MARKET_STATUSES,
)
from database.market_mcp_db import (
    check_mcp_market_name_exists,
    create_mcp_market_record,
    delete_mcp_market_record_by_id,
    get_mcp_market_record_by_id,
    get_mcp_market_records,
    get_mcp_market_tag_stats_by_tenant,
    increment_mcp_market_download_count,
    list_mcp_market_records_by_status,
    list_mcp_market_records_by_tenant_and_user,
    update_mcp_market_record,
    update_mcp_market_status,
)
from database.remote_mcp_db import (
    clear_mcp_record_market_id,
    get_mcp_record_by_id_and_tenant,
    update_mcp_record_market_id_by_id,
)
from database.user_tenant_db import get_user_tenant_by_user_id
from database.group_db import query_group_ids_by_user
from utils.str_utils import convert_list_to_string, convert_string_to_list

logger = logging.getLogger("mcp_management_service")

MCP_REGISTRY_BASE_URL = "https://registry.modelcontextprotocol.io/v0.1/servers"
ADMIN_ROLES = {"ADMIN", "SUPER_ADMIN", "SU"}
SUPER_ADMIN_ROLES = {"SUPER_ADMIN", "SU"}

# ---------------------------------------------------------------------------
# State machine transitions (following Agent Repository pattern)
# ---------------------------------------------------------------------------

_SU_TRANSITIONS: FrozenSet[Tuple[str, str]] = frozenset({
    (STATUS_PENDING_REVIEW, STATUS_REJECTED),
    (STATUS_PENDING_REVIEW, STATUS_SHARED),
    (STATUS_SHARED, STATUS_NOT_SHARED),
})

_ADMIN_REVIEW_TRANSITIONS: FrozenSet[Tuple[str, str]] = frozenset({
    (STATUS_PENDING_REVIEW, STATUS_REJECTED),
    (STATUS_PENDING_REVIEW, STATUS_SHARED),
})

_PUBLISHER_TRANSITIONS: FrozenSet[Tuple[str, str]] = frozenset({
    (STATUS_NOT_SHARED, STATUS_PENDING_REVIEW),
    (STATUS_REJECTED, STATUS_PENDING_REVIEW),
    (STATUS_PENDING_REVIEW, STATUS_NOT_SHARED),
    (STATUS_REJECTED, STATUS_NOT_SHARED),
    (STATUS_SHARED, STATUS_NOT_SHARED),
})

_SUBMIT_TRANSITIONS: FrozenSet[Tuple[str, str]] = frozenset({
    (STATUS_NOT_SHARED, STATUS_PENDING_REVIEW),
    (STATUS_REJECTED, STATUS_PENDING_REVIEW),
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_mcp_review_admin_scope(user_id: str, tenant_id: str) -> str | None:
    """Return tenant scope for review queries. None means no scope (SU sees all)."""
    user_tenant = get_user_tenant_by_user_id(user_id)
    user_role = (user_tenant or {}).get("user_role", "").upper()
    if user_role not in ADMIN_ROLES:
        raise UnauthorizedError("Only administrators can review MCP submissions")
    if user_role in SUPER_ADMIN_ROLES:
        return None
    return tenant_id


def _resolve_user_email(user_id: str) -> str | None:
    """Resolve user_id to email for submitted_by tracking."""
    user_tenant = get_user_tenant_by_user_id(user_id) or {}
    email = str(user_tenant.get("user_email") or "").strip()
    return email or None


def _resolve_author_display_name(user_id: str | None) -> str | None:
    if not user_id:
        return None
    return _resolve_user_email(user_id)


def _to_community_card(row: Dict[str, Any]) -> Dict[str, Any]:
    raw_status = row.get("review_status") or "not_shared"
    status_map: Dict[str, str] = {
        STATUS_NOT_SHARED: "offline",
        STATUS_PENDING_REVIEW: "pending",
        STATUS_SHARED: "approved",
        STATUS_REJECTED: "rejected",
    }
    return {
        "communityId": row.get("market_id"),
        "marketId": row.get("market_id"),
        "reviewId": row.get("market_id"),
        "sourceMcpId": row.get("source_mcp_id"),
        "name": row.get("mcp_name"),
        "description": row.get("description"),
        "status": "active" if raw_status == STATUS_SHARED else "inactive",
        "createdAt": row.get("create_time"),
        "updatedAt": row.get("update_time"),
        "source": "community",
        "transportType": row.get("transport_type"),
        "serverUrl": row.get("mcp_server"),
        "configJson": row.get("config_json") if isinstance(row.get("config_json"), dict) else None,
        "registryJson": row.get("registry_json") if isinstance(row.get("registry_json"), dict) else None,
        "tags": row.get("tags") or [],
        "reviewStatus": status_map.get(raw_status, raw_status),
        "reviewType": "initial_listing",
        "installCount": row.get("download_count") or 0,
        "authorDisplayName": _resolve_author_display_name(row.get("user_id")),
        "groupIds": row.get("group_ids"),
        "ingroupPermission": row.get("ingroup_permission"),
    }


def _get_user_role(user_id: str) -> str:
    user_tenant = get_user_tenant_by_user_id(user_id) or {}
    return str(user_tenant.get("user_role", "")).upper()


def _validate_market_status_transition(
    *,
    user_role: str,
    current_status: str,
    new_status: str,
    record: Dict[str, Any],
    user_id: str,
    tenant_id: str,
) -> str | None:
    """Validate role, ownership, and allowed status transition.

    Returns submitter email if this is a submit action (not_shared/pending_review
    or rejected/pending_review), otherwise None.
    """
    transition = (current_status, new_status)

    if user_role == "SU":
        if transition not in _SU_TRANSITIONS:
            raise ValueError(
                f"Invalid status transition from '{current_status}' to '{new_status}'"
            )
        return None

    if user_role in ("ADMIN", "DEV"):
        if record.get("tenant_id") != tenant_id:
            raise UnauthorizedError("Not authorized to update this marketplace listing")
        if user_role == "DEV" and record.get("user_id") != user_id:
            raise UnauthorizedError("Not authorized to update this marketplace listing")

        # ADMIN can also act as reviewer
        if user_role == "ADMIN" and transition in _ADMIN_REVIEW_TRANSITIONS:
            return None

        if transition not in _PUBLISHER_TRANSITIONS:
            raise ValueError(
                f"Invalid status transition from '{current_status}' to '{new_status}'"
            )

        if transition in _SUBMIT_TRANSITIONS:
            return _resolve_user_email(user_id)
        return None

    raise UnauthorizedError(
        f"User role {user_role} not authorized to update marketplace listing"
    )


# ---------------------------------------------------------------------------
# Community MCP Service Functions
# ---------------------------------------------------------------------------

async def list_community_mcp_services(
    *,
    tenant_id: str,
    user_id: str,
    search: str | None = None,
    tag: str | None = None,
    transport_type: str | None = None,
    cursor: str | None = None,
    limit: int = 30,
) -> Dict[str, Any]:
    """List shared (approved) community MCP services scoped to a tenant with permission filtering."""
    user_role = _get_user_role(user_id)
    user_group_ids = None
    if user_role not in CAN_EDIT_ALL_USER_ROLES:
        try:
            user_group_ids = list(query_group_ids_by_user(user_id) or [])
        except Exception as e:
            logger.warning(f"Failed to query user group ids: user_id={user_id}, err={e}")

    db_result = get_mcp_market_records(
        tenant_id=tenant_id,
        search=search,
        tag=tag,
        transport_type=transport_type,
        cursor=cursor,
        limit=limit,
        user_id=user_id if user_role not in CAN_EDIT_ALL_USER_ROLES else None,
        user_group_ids=user_group_ids,
    )
    return {
        "count": db_result.get("count", 0),
        "nextCursor": db_result.get("nextCursor"),
        "items": [_to_community_card(item) for item in db_result.get("items", [])],
    }


def list_community_mcp_tag_stats(tenant_id: str) -> List[Dict[str, Any]]:
    return get_mcp_market_tag_stats_by_tenant(tenant_id=tenant_id)


async def publish_community_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    mcp_id: int,
    name: str | None = None,
    description: str | None = None,
    tags: List[str] | None = None,
    mcp_server: str | None = None,
    config_json: Dict[str, Any] | None = None,
    group_ids: List[int] | None = None,
    ingroup_permission: str | None = None,
) -> int:
    """Submit a local MCP service for review.

    Creates a market record with status=pending_review directly (no separate review table).
    Returns the new market_id.
    """
    source_record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not source_record:
        raise McpNotFoundError("MCP record not found")

    source_registry_json = (
        source_record.get("registry_json")
        if isinstance(source_record.get("registry_json"), dict)
        else None
    )
    source_config_json = (
        source_record.get("config_json")
        if isinstance(source_record.get("config_json"), dict)
        else None
    )

    final_name = name if name is not None else source_record.get("mcp_name")
    final_description = description if description is not None else source_record.get("description")
    final_tags = tags if tags is not None else source_record.get("tags")
    final_mcp_server = mcp_server if mcp_server is not None else source_record.get("mcp_server")
    final_config_json = config_json if isinstance(config_json, dict) else source_config_json

    community_transport_type = "container" if final_config_json is not None else "url"

    # Check name uniqueness among shared records only
    if check_mcp_market_name_exists(final_name):
        raise McpNameConflictError(f"MCP name '{final_name}' already exists in the community market")

    market_id = create_mcp_market_record(
        mcp_data={
            "mcp_name": final_name,
            "source_mcp_id": mcp_id,
            "mcp_server": final_mcp_server,
            "registry_json": source_registry_json,
            "transport_type": source_record.get("transport_type") or community_transport_type,
            "config_json": final_config_json,
            "review_status": STATUS_PENDING_REVIEW,
            "submitted_by": _resolve_user_email(user_id),
            "tags": final_tags,
            "description": final_description,
            "group_ids": convert_list_to_string(group_ids) if group_ids else None,
            "ingroup_permission": ingroup_permission,
        },
        tenant_id=tenant_id,
        user_id=user_id,
    )
    return market_id


async def update_community_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    market_id: int,
    name: str | None,
    description: str | None,
    tags: List[str] | None,
    registry_json: Dict[str, Any] | None,
    mcp_server: str | None = None,
    config_json: Dict[str, Any] | None = None,
    transport_type: str | None = None,
    group_ids: List[int] | None = None,
    ingroup_permission: str | None = None,
) -> None:
    """Update a published market MCP and set it back to pending_review for re-approval."""
    current = get_mcp_market_record_by_id(market_id=market_id)
    if not current:
        raise McpNotFoundError("Market MCP record not found")

    existing_config_json = (
        current.get("config_json") if isinstance(current.get("config_json"), dict) else None
    )
    next_registry_json = (
        registry_json if isinstance(registry_json, dict) else (current.get("registry_json") or {})
    )
    next_config_json = config_json if isinstance(config_json, dict) else existing_config_json
    next_transport_type = transport_type
    if next_transport_type is None and isinstance(config_json, dict):
        next_transport_type = "container"
    if next_transport_type is None and mcp_server is not None:
        next_transport_type = "url"

    # Check name uniqueness if name is changing
    if name is not None and name != current.get("mcp_name") and check_mcp_market_name_exists(name):
        raise McpNameConflictError(f"MCP name '{name}' already exists in the community market")

    # Update fields
    update_mcp_market_record(
        market_id=market_id,
        user_id=user_id,
        mcp_name=name,
        description=description,
        tags=tags,
        registry_json=next_registry_json,
        mcp_server=mcp_server,
        config_json=next_config_json,
        transport_type=next_transport_type,
        group_ids=convert_list_to_string(group_ids) if group_ids else None,
        ingroup_permission=ingroup_permission,
    )

    # Set back to pending_review for re-approval
    update_mcp_market_status(
        market_id=market_id,
        user_id=user_id,
        review_status=STATUS_PENDING_REVIEW,
        submitted_by=_resolve_user_email(user_id),
    )


async def change_mcp_market_status(
    *,
    tenant_id: str,
    user_id: str,
    market_id: int,
    new_status: str,
) -> None:
    """Unified status change endpoint. Validates state machine transitions.

    Supports all allowed transitions: submit, approve, reject, withdraw, unshare.
    """
    if new_status not in VALID_MARKET_STATUSES:
        raise ValueError(
            f"Invalid status '{new_status}'; must be one of: "
            f"{', '.join(sorted(VALID_MARKET_STATUSES))}"
        )

    current = get_mcp_market_record_by_id(market_id=market_id)
    if not current:
        raise McpNotFoundError("Market MCP record not found")

    user_role = _get_user_role(user_id)
    current_status = current.get("review_status", STATUS_NOT_SHARED)

    submitted_by = _validate_market_status_transition(
        user_role=user_role,
        current_status=current_status,
        new_status=new_status,
        record=current,
        user_id=user_id,
        tenant_id=tenant_id,
    )

    update_mcp_market_status(
        market_id=market_id,
        user_id=user_id,
        review_status=new_status,
        submitted_by=submitted_by,
    )

    # When approving for the first time, link the source MCP record
    if new_status == STATUS_SHARED and current_status == STATUS_PENDING_REVIEW:
        source_mcp_id = current.get("source_mcp_id")
        if source_mcp_id is not None:
            update_mcp_record_market_id_by_id(
                mcp_id=source_mcp_id,
                tenant_id=current.get("tenant_id"),
                user_id=current.get("user_id"),
                market_id=market_id,
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
    """List market records awaiting review (for the review center)."""
    review_tenant_id = _get_mcp_review_admin_scope(user_id, tenant_id)
    review_status = status or STATUS_PENDING_REVIEW
    db_result = list_mcp_market_records_by_status(
        tenant_id=review_tenant_id,
        review_status=review_status,
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


async def delete_community_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    market_id: int,
) -> None:
    """Soft-delete a market MCP service and clear FK references."""
    current = get_mcp_market_record_by_id(market_id=market_id)
    if not current:
        raise McpNotFoundError("Market MCP record not found")

    delete_mcp_market_record_by_id(market_id=market_id, user_id=user_id)
    clear_mcp_record_market_id(
        tenant_id=tenant_id,
        user_id=user_id,
        market_id=market_id,
    )


async def list_my_community_mcp_services(
    *,
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """List MCP services (all statuses) published by the current user."""
    market_rows = list_mcp_market_records_by_tenant_and_user(
        tenant_id=tenant_id,
        user_id=user_id,
    )
    items = [_to_community_card(row) for row in market_rows]
    return {
        "count": len(items),
        "items": items,
    }


# ---------------------------------------------------------------------------
# Legacy convenience wrappers (for backward compat / internal use)
# ---------------------------------------------------------------------------

async def approve_community_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    market_id: int,
) -> None:
    """Approve: pending_review -> shared."""
    user_role = _get_user_role(user_id)
    if user_role not in ADMIN_ROLES:
        raise UnauthorizedError("Only administrators can approve MCP submissions")
    await change_mcp_market_status(
        tenant_id=tenant_id,
        user_id=user_id,
        market_id=market_id,
        new_status=STATUS_SHARED,
    )


async def reject_community_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    market_id: int,
) -> None:
    """Reject: pending_review -> rejected."""
    user_role = _get_user_role(user_id)
    if user_role not in ADMIN_ROLES:
        raise UnauthorizedError("Only administrators can reject MCP submissions")
    await change_mcp_market_status(
        tenant_id=tenant_id,
        user_id=user_id,
        market_id=market_id,
        new_status=STATUS_REJECTED,
    )


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
    """List MCP services from the official MCP Registry."""
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


async def list_registry_mcp_services(
    *,
    search: str | None = None,
    include_deleted: bool = False,
    updated_since: str | None = None,
    version: str | None = None,
    cursor: str | None = None,
    limit: int = 30,
) -> Dict[str, Any]:
    """List MCP services from the official registry."""
    return await _list_official_registry_mcp_services(
        search=search,
        include_deleted=include_deleted,
        updated_since=updated_since,
        version=version,
        cursor=cursor,
        limit=limit,
    )
