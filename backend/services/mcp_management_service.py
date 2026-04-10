import logging
import asyncio
import socket
from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import urlencode

import aiohttp

from consts.const import NEXENT_MCP_DOCKER_IMAGE
from consts.exceptions import (
    MCPConnectionError,
    MCPContainerError,
    McpNotFoundError,
    McpPortConflictError,
    McpValidationError,
    McpNameConflictError,
)
from consts.model import MCPConfigRequest
from database.remote_mcp_db import (
    check_enabled_mcp_name_exists,
    delete_mcp_record_by_id,
    create_mcp_record,
    get_mcp_record_by_id_and_tenant,
    get_mcp_records_by_container_port,
    get_mcp_tag_stats_by_tenant,
    get_mcp_records_by_tenant,
    update_mcp_record_enabled_by_id,
    update_mcp_record_manage_fields_by_id,
    update_mcp_record_runtime_fields_by_id,
    update_mcp_record_status_by_id,
)
from database.community_mcp_db import (
    create_mcp_community_record,
    delete_mcp_community_record_by_id,
    get_mcp_community_record_by_id_and_tenant,
    get_mcp_community_records,
    get_mcp_community_tag_stats_by_tenant,
    list_mcp_community_records_by_tenant,
    update_mcp_community_record_by_id,
)
from services.mcp_container_service import MCPContainerManager
from services.remote_mcp_service import mcp_server_health
from services.tool_configuration_service import get_tool_from_remote_mcp_server

logger = logging.getLogger("mcp_management_service")

MCP_REGISTRY_BASE_URL = "https://registry.modelcontextprotocol.io/v0.1/servers"


def _is_container_record(record: Dict[str, Any] | None) -> bool:
    return (record or {}).get("transport_type") == "stdio"


def check_container_port_conflict_records(port: int) -> bool:
    """Check if there are enabled MCP records that already use the given container port."""
    return not get_mcp_records_by_container_port(container_port=port)


def check_runtime_host_port_available(port: int) -> bool:
    """Return True when the host port is not occupied by a listener."""
    probe_targets = [(socket.AF_INET, "127.0.0.1")]
    if socket.has_ipv6:
        probe_targets.append((socket.AF_INET6, "::1"))

    # When the backend runs inside Docker on Windows/macOS, the host listener is
    # usually reachable through host.docker.internal rather than localhost.
    try:
        host_infos = socket.getaddrinfo("host.docker.internal", port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in host_infos:
            probe_targets.append((family, sockaddr[0]))
    except OSError:
        pass

    for family, host in probe_targets:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as probe_socket:
                probe_socket.settimeout(0.2)
                connect_result = probe_socket.connect_ex((host, port) if family == socket.AF_INET else (host, port, 0, 0))
                if connect_result == 0:
                    logger.info(f"Host port {port} is already in use on {host}")
                    return False
        except OSError:
            continue

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as bind_probe:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                bind_probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                bind_probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            bind_probe.bind(("0.0.0.0", port))
            bind_probe.listen(1)
        return True
    except OSError as exc:
        logger.info(f"Host port {port} is already in use: {exc}")
        return False



def check_container_port_conflict(
    *,
    port: int,
) -> bool:
    no_conflict_records = check_container_port_conflict_records(port=port)
    runtime_available = check_runtime_host_port_available(port)
    return no_conflict_records and runtime_available


def suggest_container_port(
    *,
    start_port: int = 5500,
) -> int:
    port = start_port
    while port <= 65535:
        if check_container_port_conflict(port=port):
            return port
        port += 1

    raise McpPortConflictError("No available port found")


async def _stop_container_without_remove_if_exists(container_id: str | None) -> None:
    if not container_id:
        return
    try:
        manager = MCPContainerManager()
        await manager.stop_mcp_container_only(container_id)
    except Exception as exc:
        logger.warning(f"Skip stopping container {container_id}: {exc}")


async def _remove_container_if_exists(container_id: str | None) -> None:
    if not container_id:
        return
    try:
        manager = MCPContainerManager()
        await manager.remove_mcp_container(container_id)
    except Exception as exc:
        logger.warning(f"Skip removing container {container_id}: {exc}")


async def _start_container_by_id_for_record(record: Dict[str, Any]) -> Dict[str, Any]:
    container_id = record.get("container_id")
    if not container_id:
        raise McpValidationError("Container ID is missing")

    manager = MCPContainerManager()
    container_info = await manager.start_existing_mcp_container(container_id)
    if not container_info.get("mcp_url"):
        raise McpValidationError("Container runtime URL is missing")
    return container_info


async def list_community_mcp_services(
    *,
    search: str | None = None,
    tag: str | None = None,
    transport_type: str | None = None,
    cursor: str | None = None,
    limit: int = 30,
) -> Dict[str, Any]:
    db_result = get_mcp_community_records(
        search=search,
        tag=tag,
        transport_type=transport_type,
        cursor=cursor,
        limit=limit,
    )

    raw_items = db_result.get("items", [])
    items = []
    for item in raw_items:
        registry_json = item.get("registry_json") if isinstance(item.get("registry_json"), dict) else {}
        items.append({
            "communityId": item.get("community_id"),
            "name": item.get("mcp_name") or "",
            "version": item.get("version"),
            "description": item.get("description") or "",
            "status": "active",
            "publishedAt": item.get("last_sync_time"),
            "updatedAt": item.get("update_time") or item.get("last_sync_time"),
            "serverJson": registry_json,
            "source": "community",
            "transportType": item.get("transport_type"),
            "serverUrl": item.get("mcp_server") or "",
            "configJson": item.get("config_json") if isinstance(item.get("config_json"), dict) else None,
            "mcpRegistryJson": registry_json,
            "tags": item.get("tags") or [],
        })
    return {
        "count": len(items),
        "nextCursor": db_result.get("nextCursor"),
        "items": items,
    }


def list_community_mcp_tag_stats(tenant_id: str) -> List[Dict[str, Any]]:
    return get_mcp_community_tag_stats_by_tenant(tenant_id=tenant_id)


async def publish_community_mcp_service(*, tenant_id: str, user_id: str, mcp_id: int) -> int:
    source_record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not source_record:
        raise McpNotFoundError("MCP record not found")

    source_registry_json = source_record.get("registry_json") if isinstance(source_record.get("registry_json"), dict) else None
    source_config_json = source_record.get("config_json") if isinstance(source_record.get("config_json"), dict) else None

    community_id = create_mcp_community_record(
        mcp_data={
            "mcp_name": source_record.get("mcp_name"),
            "mcp_server": source_record.get("mcp_server"),
            "version": source_record.get("version"),
            "registry_json": source_registry_json,
            "transport_type": source_record.get("transport_type"),
            "config_json": source_config_json,
            "tags": source_record.get("tags"),
            "description": source_record.get("description"),
            "last_sync_time": datetime.now(),
        },
        tenant_id=tenant_id,
        user_id=user_id,
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
) -> None:
    current = get_mcp_community_record_by_id_and_tenant(community_id=community_id, tenant_id=tenant_id)
    if not current:
        raise McpNotFoundError("Community MCP record not found")

    existing_config_json = current.get("config_json") if isinstance(current.get("config_json"), dict) else None
    next_registry_json = registry_json if isinstance(registry_json, dict) else current.get("registry_json")
    next_config_json = existing_config_json if isinstance(existing_config_json, dict) else None

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
    )


async def delete_community_mcp_service(*, tenant_id: str, user_id: str, community_id: int) -> None:
    current = get_mcp_community_record_by_id_and_tenant(community_id=community_id, tenant_id=tenant_id)
    if not current:
        raise McpNotFoundError("Community MCP record not found")
    delete_mcp_community_record_by_id(community_id=community_id, tenant_id=tenant_id, user_id=user_id)


async def list_my_community_mcp_services(*, tenant_id: str) -> Dict[str, Any]:
    rows = list_mcp_community_records_by_tenant(tenant_id=tenant_id)
    items = []
    for row in rows:
        registry_json = row.get("registry_json") if isinstance(row.get("registry_json"), dict) else {}
        items.append({
            "communityId": row.get("community_id"),
            "name": row.get("mcp_name") or "",
            "version": row.get("version"),
            "description": row.get("description") or "",
            "status": "active",
            "publishedAt": row.get("last_sync_time"),
            "updatedAt": row.get("update_time") or row.get("last_sync_time"),
            "serverJson": registry_json,
            "source": "community",
            "transportType": row.get("transport_type"),
            "serverUrl": row.get("mcp_server") or "",
            "configJson": row.get("config_json") if isinstance(row.get("config_json"), dict) else None,
            "mcpRegistryJson": registry_json,
            "tags": row.get("tags") or [],
        })
    return {
        "count": len(items),
        "items": items,
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

    # Keep response shape aligned with official MCP registry API.
    return {
        "servers": raw_servers if isinstance(raw_servers, list) else [],
        "metadata": metadata,
    }


async def add_container_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    name: str,
    description: str | None,
    source: str,
    tags: list[str] | None,
    authorization_token: str | None,
    registry_json: Dict[str, Any] | None,
    port: int,
    mcp_config: MCPConfigRequest,
) -> Dict[str, Any]:
    service_name = name
    if check_enabled_mcp_name_exists(mcp_name=service_name, tenant_id=tenant_id):
        raise McpNameConflictError("Enabled MCP name already exists")

    if not check_container_port_conflict(port=port):
        raise McpPortConflictError(f"Port {port} is already in use")

    servers = mcp_config.mcpServers
    if len(servers) != 1:
        raise McpValidationError("Exactly one mcpServers entry is required")

    _, config = next(iter(servers.items()))
    command = config.command
    if not command:
        raise McpValidationError("command is required")
    if command.strip().lower() == "docker":
        raise McpValidationError("Docker command is not supported")

    env_vars = dict(config.env or {})
    auth_token = authorization_token
    if auth_token:
        env_vars["authorization_token"] = auth_token

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
    try:
        container_info = await container_manager.start_mcp_container(
            service_name=service_name,
            tenant_id=tenant_id,
            user_id=user_id,
            env_vars=env_vars,
            host_port=port,
            image=NEXENT_MCP_DOCKER_IMAGE,
            full_command=full_command,
        )

        container_config = mcp_config.model_dump(exclude_none=True)

        await add_mcp_service(
            tenant_id=tenant_id,
            user_id=user_id,
            name=service_name,
            description=description,
            source=source,
            transport_type="stdio",
            server_url=container_info["mcp_url"],
            tags=tags,
            authorization_token=auth_token,
            container_config=container_config,
            version=None,
            registry_json=registry_json,
            enabled=True,
            container_id=container_info.get("container_id"),
            container_port=container_info.get("host_port"),
        )
    except Exception as exc:
        logger.warning(f"Failed to start container MCP service, status: {exc}")
        raise

    return {
        "service_name": service_name,
        "mcp_url": container_info.get("mcp_url"),
        "container_id": container_info.get("container_id"),
        "container_name": container_info.get("container_name"),
        "host_port": container_info.get("host_port"),
    }


async def add_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    name: str,
    description: str | None,
    source: str,
    transport_type: str,
    server_url: str,
    tags: list[str] | None,
    authorization_token: str | None,
    container_config: Dict[str, Any] | None,
    version: str | None,
    registry_json: Dict[str, Any] | None,
    enabled: bool = False,
    container_id: str | None = None,
    container_port: int | None = None,
) -> None:
    # mcp-tools add flow does not perform connectivity checks.
    # Health status remains unchecked until manual health check.
    status: bool | None = None

    normalized_container_id = container_id if isinstance(container_id, str) and container_id else None
    config_json = container_config if transport_type == "stdio" and isinstance(container_config, dict) else None

    create_mcp_record(
        mcp_data={
            "mcp_name": name,
            "mcp_server": server_url,
            "status": status,
            "container_id": normalized_container_id,
            "container_port": container_port,
            "authorization_token": authorization_token,
            "source": source,
            "version": version,
            "registry_json": registry_json,
            "transport_type": transport_type,
            "enabled": enabled,
            "tags": tags,
            "description": description,
            "config_json": config_json,
        },
        tenant_id=tenant_id,
        user_id=user_id,
    )


def list_mcp_services(tenant_id: str, tag: str | None = None) -> List[Dict[str, Any]]:
    records = get_mcp_records_by_tenant(tenant_id=tenant_id, tag=tag)
    services: List[Dict[str, Any]] = []

    container_status_map: Dict[str, str] = {}
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

    for record in records:
        source = record.get("source")
        transport_type = record.get("transport_type")
        enabled = bool(record.get("enabled"))
        status = record.get("status")
        registry_json = record.get("registry_json")
        raw_config_json = record.get("config_json")

        container_id = record.get("container_id")
        container_port = record.get("container_port")
        record_config_json = raw_config_json if transport_type == "stdio" else None
        container_status = None
        if transport_type == "stdio":
            if container_id:
                container_status = container_status_map.get(container_id, "stopped")
            else:
                container_status = "stopped"

        services.append({
            "mcpId": record.get("mcp_id"),
            "containerId": container_id or None,
            "name": record.get("mcp_name"),
            "description": record.get("description") or record.get("category") or "",
            "source": source or "local",
            "status": "enabled" if enabled else "disabled",
            "updatedAt": record.get("update_time"),
            "tags": record.get("tags") or [],
            "transportType": transport_type,
            "serverUrl": record.get("mcp_server"),
            "containerPort": container_port,
            "version": record.get("version"),
            "mcpRegistryJson": registry_json,
            "configJson": record_config_json,
            "tools": record.get("tools") or [],
            "healthStatus": "healthy" if status is True else "unhealthy" if status is False else "unchecked",
            "containerStatus": container_status,
            "authorizationToken": record.get("authorization_token") or "",
        })

    return services


def list_mcp_tag_stats(tenant_id: str) -> List[Dict[str, Any]]:
    return get_mcp_tag_stats_by_tenant(tenant_id=tenant_id)


async def list_mcp_service_tools_by_id(*, tenant_id: str, mcp_id: int) -> List[Dict[str, Any]]:
    record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not record:
        raise McpNotFoundError("MCP record not found")

    service_name = record.get("mcp_name")
    server_url = record.get("mcp_server")
    if not service_name or not server_url:
        raise McpValidationError("MCP record is missing runtime connection fields")

    tools_info = await get_tool_from_remote_mcp_server(
        mcp_server_name=service_name,
        remote_mcp_server=server_url,
        tenant_id=tenant_id,
    )
    return [tool.__dict__ for tool in tools_info]


def update_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    mcp_id: int,
    new_name: str,
    description: str | None,
    server_url: str,
    authorization_token: str | None,
    tags: list[str] | None,
) -> None:
    current_record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not current_record:
        raise McpNotFoundError("MCP record not found")

    current_transport_type = current_record.get("transport_type")
    config_json = None
    if current_transport_type in {"stdio", "container"}:
        config_json = current_record.get("config_json") if isinstance(current_record.get("config_json"), dict) else None

    update_mcp_record_manage_fields_by_id(
        mcp_id=mcp_id,
        tenant_id=tenant_id,
        user_id=user_id,
        name=new_name,
        description=description,
        server_url=server_url,
        source=(current_record.get("source") or "local"),
        transport_type=(current_record.get("transport_type") or "http"),
        authorization_token=authorization_token,
        config_json=config_json,
        tags=tags,
    )

async def update_mcp_service_enabled(
    *,
    tenant_id: str,
    user_id: str,
    mcp_id: int,
    enabled: bool,
) -> None:
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
                    raise McpNameConflictError("An enabled service already uses this name")

    authorization_token = current_record.get("authorization_token")

    if _is_container_record(current_record):
        if enabled:
            next_container_port = current_record.get("container_port")
            if next_container_port is not None and not check_runtime_host_port_available(next_container_port):
                raise McpPortConflictError(f"Port {next_container_port} is already in use")

            container_info = await _start_container_by_id_for_record(current_record)
            next_server_url = container_info.get("mcp_url")
            next_container_id = container_info.get("container_id") or current_record.get("container_id")
            next_container_port = container_info.get("host_port") or next_container_port

            health_ok = False
            MCP_CONTAINER_HEALTH_CHECK_ATTEMPTS = 4
            MCP_CONTAINER_HEALTH_CHECK_DELAY_SECONDS = 0.5
            for attempt in range(MCP_CONTAINER_HEALTH_CHECK_ATTEMPTS):
                try:
                    health_ok = await mcp_server_health(
                        remote_mcp_server=next_server_url,
                        authorization_token=authorization_token,
                    )
                except MCPConnectionError:
                    health_ok = False
                if health_ok:
                    break
                if attempt < MCP_CONTAINER_HEALTH_CHECK_ATTEMPTS - 1:
                    await asyncio.sleep(MCP_CONTAINER_HEALTH_CHECK_DELAY_SECONDS)
            if not health_ok:
                await _stop_container_without_remove_if_exists(next_container_id)
                update_mcp_record_runtime_fields_by_id(
                    mcp_id=mcp_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    container_id=next_container_id,
                    container_port=next_container_port,
                    mcp_server=next_server_url,
                    status=False,
                )
                raise MCPConnectionError("MCP connection failed")

            update_mcp_record_runtime_fields_by_id(
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
            await _stop_container_without_remove_if_exists(current_container_id)
            update_mcp_record_runtime_fields_by_id(
                mcp_id=mcp_id,
                tenant_id=tenant_id,
                user_id=user_id,
                container_id=current_container_id,
                container_port=current_record.get("container_port"),
                mcp_server=current_record.get("mcp_server"),
                status=None,
            )
    elif enabled:
        server_url = current_record.get("mcp_server")
        health_ok = await mcp_server_health(
            remote_mcp_server=server_url,
            authorization_token=authorization_token,
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
    current_record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not current_record:
        raise McpNotFoundError("MCP record not found")

    if _is_container_record(current_record):
        current_container_id = current_record.get("container_id")
        await _stop_container_without_remove_if_exists(current_container_id)
        await _remove_container_if_exists(current_container_id)

    delete_mcp_record_by_id(
        mcp_id=mcp_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )

async def check_mcp_service_health(
    *,
    tenant_id: str,
    user_id: str,
    mcp_id: int,
) -> str:
    record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not record:
        raise McpNotFoundError("MCP record not found")

    server_url = record.get("mcp_server")
    if not server_url:
        raise McpValidationError("MCP server URL is empty")

    authorization_token = record.get("authorization_token")

    try:
        status = await mcp_server_health(
            remote_mcp_server=server_url,
            authorization_token=authorization_token,
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