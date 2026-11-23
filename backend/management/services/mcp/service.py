# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import logging
import os
import random
import socket
import tempfile
from contextlib import AsyncExitStack
from typing import Awaitable, Callable

from consts.const import (
    CAN_EDIT_ALL_USER_ROLES,
    MCP_REQUEST_TIMEOUT_SECONDS,
    NEXENT_MCP_DOCKER_IMAGE,
    PERMISSION_EDIT,
    PERMISSION_READ,
)
from consts.exceptions import (
    MCPConnectionError,
    MCPContainerError,
    McpNameConflictError,
    MCPNameIllegal,
    McpNotFoundError,
    McpPortConflictError,
    McpValidationError,
)
from consts.model import MCPConfigRequest
from database.group_db import query_group_ids_by_user
from database.market_mcp_db import (
    get_mcp_market_record_by_source_mcp_id,
    update_mcp_market_record,
)
from database.remote_mcp_db import (
    check_enabled_mcp_name_exists,
    check_mcp_name_exists,
    create_mcp_record,
    delete_mcp_record_by_container_id,
    delete_mcp_record_by_id,
    get_mcp_authorization_token_by_name_and_url,
    get_mcp_custom_headers_by_name_and_url,
    get_mcp_record_by_id_and_tenant,
    get_mcp_records_by_tenant,
    update_mcp_record_by_name_and_url,
    update_mcp_record_container_fields_by_id,
    update_mcp_record_enabled_by_id,
    update_mcp_record_manage_fields_by_id,
    update_mcp_record_registry_json_by_id,
    update_mcp_record_status_by_id,
    update_mcp_status_by_name_and_url,
)
from database.tool_db import set_mcp_tools_unavailable
from database.user_tenant_db import get_user_tenant_by_user_id
from fastmcp import Client
from fastmcp.client.transports import SSETransport, StreamableHttpTransport
from infrastructure.http.client import create_httpx_client
from management.services.mcp.common import (
    logger,
)
from management.services.mcp.containers import MCPContainerManager


async def update_remote_mcp_server_list(
    update_data, tenant_id: str, user_id: str
) -> None:
    """Update an existing remote MCP server record.

    Args:
        update_data: MCPUpdateRequest containing current and new values
        tenant_id: Tenant ID
        user_id: User ID

    Raises:
        MCPNameIllegal: If the new MCP name already exists
        MCPConnectionError: If the new MCP server URL is not accessible
    """
    if not check_mcp_name_exists(
        mcp_name=update_data.current_service_name, tenant_id=tenant_id
    ):
        raise MCPNameIllegal("MCP name does not exist")

    if update_data.new_service_name != update_data.current_service_name:
        if check_mcp_name_exists(
            mcp_name=update_data.new_service_name, tenant_id=tenant_id
        ):
            raise MCPNameIllegal("New MCP name already exists")

    authorization_token = update_data.new_authorization_token
    custom_headers = getattr(update_data, "custom_headers", None)

    try:
        status = await mcp_server_health(
            remote_mcp_server=update_data.new_mcp_url,
            authorization_token=authorization_token,
            custom_headers=custom_headers,
        )
    except BaseException:
        status = False

    if not status:
        raise MCPConnectionError("New MCP server connection failed")

    update_mcp_record_by_name_and_url(
        update_data=update_data, tenant_id=tenant_id, user_id=user_id, status=status
    )


def update_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    mcp_id: int,
    new_name: str,
    description: str | None,
    server_url: str,
    authorization_token: str | None,
    custom_headers: dict | None,
    config_json: dict | None,
    tags: list | None,
    market_id: int | None,
    group_ids: str | None = None,
    ingroup_permission: str | None = None,
    shared_fields: dict | None = None,
) -> None:
    """Update an MCP service record by ID.

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        mcp_id: MCP record ID
        new_name: New MCP service name
        description: MCP service description
        server_url: New MCP server URL
        authorization_token: Authorization token
        custom_headers: Custom HTTP headers
        config_json: MCP configuration JSON
        tags: MCP tags
        market_id: Linked market record ID
        group_ids: Comma-separated group IDs that can access this MCP
        ingroup_permission: Permission level: EDIT, READ_ONLY, PRIVATE

    Raises:
        McpNotFoundError: If MCP record is not found
    """
    current_record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not current_record:
        raise McpNotFoundError("MCP record not found")

    # Check name uniqueness (exclude the current record itself)
    if new_name != current_record.get("mcp_name"):
        if check_mcp_name_exists(mcp_name=new_name, tenant_id=tenant_id):
            logger.error(f"MCP name already exists: {new_name} in tenant {tenant_id}")
            raise McpNameConflictError("MCP name already exists")

    current_config_json = (
        current_record.get("config_json")
        if isinstance(current_record.get("config_json"), dict)
        else None
    )
    next_config_json = config_json if config_json is not None else current_config_json

    next_market_id = (
        market_id if market_id is not None else current_record.get("market_id")
    )

    update_mcp_record_manage_fields_by_id(
        mcp_id=mcp_id,
        tenant_id=tenant_id,
        user_id=user_id,
        name=new_name,
        description=description,
        server_url=server_url,
        source=(current_record.get("source") or "local"),
        authorization_token=authorization_token,
        custom_headers=custom_headers,
        config_json=next_config_json,
        tags=tags,
        market_id=next_market_id,
        group_ids=group_ids,
        ingroup_permission=ingroup_permission,
        shared_fields=shared_fields,
    )


async def update_mcp_service_enabled(
    *,
    tenant_id: str,
    user_id: str,
    mcp_id: int,
    enabled: bool,
) -> None:
    """Enable or disable an MCP service.

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        mcp_id: MCP record ID
        enabled: True to enable, False to disable

    Raises:
        McpNotFoundError: If MCP record is not found
        McpNameConflictError: If an enabled service with the same name exists
        McpPortConflictError: If the container port is not available
        MCPConnectionError: If MCP connection fails
    """
    current_record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not current_record:
        raise McpNotFoundError("MCP record not found")

    if enabled:
        current_name = current_record.get("mcp_name")
        if current_name:
            records = get_mcp_records_by_tenant(tenant_id=tenant_id)
            for record in records:
                if int(record.get("mcp_id") or 0) == mcp_id:
                    continue
                record_name = record.get("mcp_name")
                is_enabled = bool(record.get("enabled"))
                if is_enabled and record_name == current_name:
                    raise McpNameConflictError(
                        "An enabled service already uses this name"
                    )

    authorization_token = current_record.get("authorization_token")
    custom_headers = (
        current_record.get("custom_headers")
        if isinstance(current_record.get("custom_headers"), dict)
        else None
    )

    if _is_container_record(current_record):
        if enabled:
            port = current_record.get("container_port")
            if port is None:
                raise McpValidationError(
                    "Container port is missing, cannot rebuild container"
                )

            # Clean up any existing container before starting a new one
            old_container_id = current_record.get("container_id")
            if old_container_id:
                try:
                    await MCPContainerManager().stop_mcp_container(old_container_id)
                    logger.info(
                        "Stopped existing container %s before re-enabling",
                        old_container_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to stop existing container %s: %s",
                        old_container_id,
                        exc,
                    )

            if not check_runtime_host_port_available(port):
                # Orphan container recovery: when the port is in use but the DB has no
                # container_id (e.g. the previous enable request was aborted right after
                # the container started but before the DB write), try to find and stop
                # any MCP container occupying this port.
                try:
                    orphan_manager = MCPContainerManager()
                    for candidate in orphan_manager.list_mcp_containers(
                        tenant_id=tenant_id
                    ):
                        if str(candidate.get("host_port")) == str(port):
                            logger.warning(
                                "Found orphan container %s on port %s, stopping it",
                                candidate.get("container_id"),
                                port,
                            )
                            await orphan_manager.stop_mcp_container(
                                candidate["container_id"]
                            )
                            break
                except Exception as cleanup_exc:
                    logger.warning(
                        "Failed to clean up orphan container on port %s: %s",
                        port,
                        cleanup_exc,
                    )

                if not check_runtime_host_port_available(port):
                    raise McpPortConflictError(f"Port {port} is already in use")

            config_json = current_record.get("config_json")
            if not isinstance(config_json, dict):
                raise McpValidationError(
                    "Container configuration is missing, cannot rebuild container"
                )

            try:
                mcp_config = MCPConfigRequest(**config_json)
            except Exception as exc:
                raise McpValidationError(f"Invalid container configuration: {exc}")

            servers = mcp_config.mcpServers
            if not servers or len(servers) != 1:
                raise McpValidationError("Exactly one mcpServers entry is required")
            _, config = next(iter(servers.items()))
            command = config.command
            if not command:
                raise McpValidationError("command is required")

            env_vars = dict(config.env or {})
            if authorization_token:
                env_vars["authorization_token"] = authorization_token

            full_command = [
                "python",
                "-m",
                "mcp_proxy",
                "--host",
                "0.0.0.0",
                "--port",
                str(port),
                "--transport",
                "streamablehttp",
                "--",
                command,
                *(config.args or []),
            ]

            container_manager = MCPContainerManager()
            container_info = await container_manager.start_mcp_container(
                service_name=current_record.get("mcp_name"),
                tenant_id=tenant_id,
                user_id=user_id,
                env_vars=env_vars,
                host_port=port,
                image=NEXENT_MCP_DOCKER_IMAGE,
                full_command=full_command,
            )

            next_server_url = container_info.get("mcp_url")
            next_container_id = container_info.get("container_id")
            next_container_port = container_info.get("host_port") or port

            health_ok = False
            MCP_CONTAINER_HEALTH_CHECK_ATTEMPTS = 10
            MCP_CONTAINER_HEALTH_CHECK_DELAY_SECONDS = 0.5
            for attempt in range(MCP_CONTAINER_HEALTH_CHECK_ATTEMPTS):
                try:
                    health_ok = await mcp_server_health(
                        remote_mcp_server=next_server_url,
                        authorization_token=authorization_token,
                        custom_headers=custom_headers,
                    )
                except MCPConnectionError:
                    health_ok = False
                if health_ok:
                    break
                if attempt < MCP_CONTAINER_HEALTH_CHECK_ATTEMPTS - 1:
                    await asyncio.sleep(MCP_CONTAINER_HEALTH_CHECK_DELAY_SECONDS)

            if not health_ok:
                if next_container_id:
                    try:
                        await MCPContainerManager().stop_mcp_container(
                            next_container_id
                        )
                    except Exception as exc:
                        logger.warning(
                            f"Failed to stop unhealthy container {next_container_id}: {exc}"
                        )
                update_mcp_record_container_fields_by_id(
                    mcp_id=mcp_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    container_id=None,
                    container_port=port,
                    mcp_server=next_server_url,
                    status=False,
                )
                raise MCPConnectionError("MCP connection failed")

            update_mcp_record_container_fields_by_id(
                mcp_id=mcp_id,
                tenant_id=tenant_id,
                user_id=user_id,
                container_id=next_container_id,
                container_port=next_container_port,
                mcp_server=next_server_url,
                status=True,
            )
        else:
            current_container_id = current_record.get("container_id")
            if current_container_id and current_record.get("config_json"):
                try:
                    manager = MCPContainerManager()
                    await manager.stop_mcp_container(current_container_id)
                except Exception as exc:
                    logger.warning(
                        f"Failed to stop container {current_container_id}: {exc}"
                    )
            update_mcp_record_container_fields_by_id(
                mcp_id=mcp_id,
                tenant_id=tenant_id,
                user_id=user_id,
                container_id=None,
                container_port=current_record.get("container_port"),
                mcp_server=current_record.get("mcp_server"),
                status=None,
            )
    elif enabled:
        server_url = current_record.get("mcp_server")
        # Skip MCP protocol check for API-type MCPs
        config_json = current_record.get("config_json")
        api_type = isinstance(config_json, dict) and "openapi" in config_json
        if api_type:
            update_mcp_record_status_by_id(
                mcp_id=mcp_id,
                tenant_id=tenant_id,
                user_id=user_id,
                status=True,
            )
        else:
            health_ok = await mcp_server_health(
                remote_mcp_server=server_url,
                authorization_token=authorization_token,
                custom_headers=custom_headers,
            )
            update_mcp_record_status_by_id(
                mcp_id=mcp_id,
                tenant_id=tenant_id,
                user_id=user_id,
                status=bool(health_ok),
            )
            if not health_ok:
                raise MCPConnectionError("MCP connection failed")

    update_mcp_record_enabled_by_id(
        mcp_id=mcp_id,
        tenant_id=tenant_id,
        user_id=user_id,
        enabled=enabled,
    )


async def delete_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    mcp_id: int,
) -> None:
    """Delete an MCP service by ID.

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        mcp_id: MCP record ID

    Raises:
        McpNotFoundError: If MCP record is not found
    """
    current_record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not current_record:
        raise McpNotFoundError("MCP record not found")
    container_id = current_record.get("container_id")
    if container_id:
        try:
            manager = MCPContainerManager()
            await manager.stop_mcp_container(container_id=container_id)
        except Exception as exc:
            logger.warning(
                f"Failed to stop container: {exc}, but continue to delete MCP record"
            )

    is_openapi_service = (
        isinstance(current_record.get("config_json"), dict)
        and "openapi" in current_record["config_json"]
    )

    if is_openapi_service:
        # API-to-MCP services have a separate service record and all their
        # persisted tools use the shared ``outer-apis`` usage value.
        try:
            from management.services.tool.configuration import (
                _refresh_openapi_services_in_mcp,
                delete_openapi_service,
            )

            delete_openapi_service(
                service_name=current_record.get("mcp_name") or "",
                tenant_id=tenant_id,
                user_id=user_id,
            )
            _refresh_openapi_services_in_mcp(tenant_id)
        except Exception as exc:
            logger.warning(
                f"Failed to remove API-to-MCP service '{current_record.get('mcp_name')}': {exc}"
            )
    # Hide the deleted MCP's tools and remove their editable agent draft bindings.
    # Cleanup must succeed before the MCP record is deleted to avoid stale bindings.
    set_mcp_tools_unavailable(
        tenant_id=tenant_id,
        mcp_server_name=(
            "outer-apis" if is_openapi_service else current_record.get("mcp_name") or ""
        ),
        user_id=user_id,
    )

    delete_mcp_record_by_id(
        mcp_id=mcp_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    from management.services.tag.library import TagManagementService

    TagManagementService.cleanup_resource_assignments(
        tenant_id, "mcp_service", str(mcp_id), user_id
    )


async def delete_mcp_by_container_id(
    tenant_id: str, user_id: str, container_id: str
) -> None:
    """Soft delete MCP record associated with a specific container ID."""
    # Hide the deleted MCP's tools and remove their editable agent draft bindings.
    deleted_mcp_id = None
    for record in get_mcp_records_by_tenant(tenant_id=tenant_id):
        if str(record.get("container_id") or "") == str(container_id):
            deleted_mcp_id = record.get("mcp_id")
            set_mcp_tools_unavailable(
                tenant_id=tenant_id,
                mcp_server_name=record.get("mcp_name") or "",
                user_id=user_id,
            )
            break

    delete_mcp_record_by_container_id(
        container_id=container_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    if deleted_mcp_id is not None:
        from management.services.tag.library import TagManagementService

        TagManagementService.cleanup_resource_assignments(
            tenant_id, "mcp_service", str(deleted_mcp_id), user_id
        )


async def get_remote_mcp_server_list(
    tenant_id: str,
    user_id: str | None = None,
    is_need_auth: bool = True,
) -> list[dict]:
    """Get list of remote MCP servers with full details.

    Args:
        tenant_id: Tenant ID
        user_id: User ID for permission checking
        is_need_auth: Whether to include authorization tokens

    Returns:
        List of MCP server records with all fields including container_id, description,
        enabled, source, update_time, tags, container_port, registry_json, config_json,
        container_status, and authorization_token
    """
    mcp_records = get_mcp_records_by_tenant(tenant_id=tenant_id)
    mcp_records_list = []
    can_edit_all = False
    user_groups: list[str] | None = None
    if user_id:
        user_tenant_record = get_user_tenant_by_user_id(user_id) or {}
        user_role = str(user_tenant_record.get("user_role") or "").upper()
        can_edit_all = user_role in CAN_EDIT_ALL_USER_ROLES
        try:
            raw_groups = query_group_ids_by_user(user_id) or []
            user_groups = [str(g) for g in raw_groups]
        except Exception:
            user_groups = []

    if user_groups is not None:
        filtered_records = []
        for record in mcp_records:
            # NULL group_ids means public (backward compatible with pre-PR data)
            if record.get("group_ids") is None:
                filtered_records.append(record)
                continue
            record_group_ids = (record.get("group_ids") or "").strip()
            # User can see MCPs they created
            if str(record.get("created_by") or record.get("user_id") or "") == user_id:
                filtered_records.append(record)
                continue
            # User can see MCPs where they belong to at least one allowed group
            if user_groups:
                allowed = [g.strip() for g in record_group_ids.split(",") if g.strip()]
                if any(g in allowed for g in user_groups):
                    # Hide PRIVATE MCPs from non-creator group members (like agent behavior)
                    ingroup_perm = (record.get("ingroup_permission") or "").upper()
                    if ingroup_perm == "PRIVATE":
                        continue
                    filtered_records.append(record)
                    continue
        logger.info(
            f"[MCP group filter] user_id={user_id}, groups={user_groups}, "
            f"total={len(mcp_records)}, filtered={len(filtered_records)}"
        )
        mcp_records = filtered_records

    container_status_map = {}
    try:
        manager = MCPContainerManager()
        for container in manager.list_mcp_containers(tenant_id=tenant_id):
            container_id = container.get("container_id")
            status = container.get("status")
            if not container_id:
                continue
            if status == "running":
                container_status_map[container_id] = "running"
            elif status:
                container_status_map[container_id] = "stopped"
    except Exception as exc:
        logger.warning(f"Failed to load container runtime status: {exc}")

    for record in mcp_records:
        created_by = record.get("created_by") or record.get("user_id")
        if user_id is None:
            permission = PERMISSION_READ
        else:
            permission = (
                PERMISSION_EDIT
                if can_edit_all or str(created_by) == str(user_id)
                else PERMISSION_READ
            )
        # Public MCPs (NULL group_ids) are editable by all users
        if record.get("group_ids") is None:
            permission = PERMISSION_EDIT
        # For group-shared MCPs, respect ingroup_permission
        if permission == PERMISSION_READ and user_groups:
            record_group_ids = (record.get("group_ids") or "").strip()
            if record_group_ids:
                allowed = [g.strip() for g in record_group_ids.split(",") if g.strip()]
                if any(g in allowed for g in user_groups):
                    ingroup_perm = (
                        record.get("ingroup_permission") or "READ_ONLY"
                    ).upper()
                    if ingroup_perm == "EDIT":
                        permission = PERMISSION_EDIT

        config_json = record.get("config_json")
        container_id = record.get("container_id")

        # Reuse _is_container_record so an empty config_json (e.g. `{}`) is not
        # misclassified as a container, matching the API/enable path behavior.
        is_container = _is_container_record(record)

        container_status = None
        if is_container:
            if container_id:
                container_status = container_status_map.get(container_id, "stopped")
            else:
                container_status = "stopped"

        record_dict = {
            "remote_mcp_server_name": record["mcp_name"],
            "remote_mcp_server": record["mcp_server"],
            "status": record.get("status"),
            "permission": permission,
            "mcp_id": record.get("mcp_id"),
            "container_id": container_id,
            "description": record.get("description"),
            "enabled": record.get("enabled"),
            "source": record.get("source"),
            "update_time": record.get("update_time"),
            "create_time": record.get("create_time"),
            "tags": record.get("tags") or [],
            "container_port": record.get("container_port"),
            "registry_json": record.get("registry_json"),
            "config_json": record.get("config_json"),
            "market_id": record.get("market_id"),
            "is_listed_in_repository": record.get("market_id") is not None,
            "container_status": container_status,
            "group_ids": record.get("group_ids"),
            "ingroup_permission": record.get("ingroup_permission"),
            "shared_fields": record.get("shared_fields"),
        }
        if is_need_auth:
            record_dict["authorization_token"] = record.get("authorization_token")
            record_dict["custom_headers"] = record.get("custom_headers")
        mcp_records_list.append(record_dict)
    return mcp_records_list


def attach_mcp_container_permissions(
    *,
    containers: list[dict],
    tenant_id: str,
    user_id: str | None = None,
) -> list[dict]:
    """Attach permission (EDIT/READ) to each MCP container entry.

    Args:
        containers: List of container records
        tenant_id: Tenant ID
        user_id: User ID for permission checking

    Returns:
        List of containers with permission field added
    """
    if not containers:
        return []
    can_edit_all = False
    if user_id:
        user_tenant_record = get_user_tenant_by_user_id(user_id) or {}
        user_role = str(user_tenant_record.get("user_role") or "").upper()
        can_edit_all = user_role in CAN_EDIT_ALL_USER_ROLES

    created_by_by_container_id = {}
    try:
        for record in get_mcp_records_by_tenant(tenant_id=tenant_id) or []:
            cid = record.get("container_id")
            if not cid:
                continue
            created_by_by_container_id[str(cid)] = str(
                record.get("created_by") or record.get("user_id") or ""
            )
    except Exception as e:
        logger.warning(f"Failed to load MCP records for permission mapping: {e}")

    enriched = []
    for container in containers:
        container_id = str(container.get("container_id") or "")
        created_by = created_by_by_container_id.get(container_id, "")

        if user_id is None:
            permission = PERMISSION_READ
        else:
            permission = (
                PERMISSION_EDIT
                if can_edit_all or (created_by and str(created_by) == str(user_id))
                else PERMISSION_READ
            )

        enriched.append({**container, "permission": permission})

    return enriched


async def get_mcp_record_by_id(
    mcp_id: int,
    tenant_id: str,
    user_id: str | None = None,
) -> dict | None:
    """Get MCP record by ID.

    Args:
        mcp_id: MCP record ID
        tenant_id: Tenant ID
        user_id: User ID for visibility checking; when provided, records that
            the user cannot see in the list view are treated as not found

    Returns:
        Dictionary containing mcp_name, mcp_server, authorization_token, and custom_headers, or None if not found
    """
    mcp_record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not mcp_record:
        return None

    if user_id is not None:
        visible_records = await get_remote_mcp_server_list(
            tenant_id=tenant_id,
            user_id=user_id,
            is_need_auth=False,
        )
        visible_ids = {record.get("mcp_id") for record in visible_records}
        if mcp_id not in visible_ids:
            return None

    return {
        "mcp_name": mcp_record.get("mcp_name"),
        "mcp_server": mcp_record.get("mcp_server"),
        "authorization_token": mcp_record.get("authorization_token"),
        "custom_headers": mcp_record.get("custom_headers"),
    }


from management.services.mcp.health import (
    _format_mcp_connection_error,
    _iter_exception_chain,
    _mcp_protocol_connect,
    _mcp_protocol_health_check,
    check_mcp_health_and_update_db,
    check_mcp_service_health,
    mcp_server_health,
    test_mcp_connection,
)
from management.services.mcp.provisioning import (
    _is_container_record,
    add_container_mcp_service,
    check_container_port_conflict,
    check_container_port_conflict_records,
    check_runtime_host_port_available,
    suggest_container_port,
    upload_and_start_mcp_image,
)
from management.services.mcp.registration import (
    _build_mcp_headers,
    _check_mcp_connectivity,
    add_mcp_service,
    add_remote_mcp_server_list,
)
from management.services.mcp.tools import (
    list_mcp_service_tools_by_id,
    refresh_mcp_service_tool_count,
)
