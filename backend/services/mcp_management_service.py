import logging
import asyncio
from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import urlencode

import aiohttp

from consts.const import NEXENT_MCP_DOCKER_IMAGE
from consts.exceptions import (
    MCPConnectionError,
    MCPContainerError,
    McpNotFoundError,
    McpValidationError,
    McpNameConflictError,
)
from consts.model import MCPConfigRequest
from database.mcp_manage_db import (
    delete_mcp_manage_service,
    get_mcp_manage_record_by_name,
    update_mcp_manage_enabled,
    update_mcp_manage_service,
    update_mcp_manage_status,
)
from database.remote_mcp_db import (
    check_enabled_mcp_name_exists,
    delete_mcp_record_by_id,
    create_mcp_record,
    get_mcp_record_by_id_and_tenant,
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
    list_mcp_community_records_by_tenant,
    update_mcp_community_record_by_id,
)
from services.mcp_container_service import MCPContainerManager
from services.remote_mcp_service import mcp_server_health
from services.tool_configuration_service import get_tool_from_remote_mcp_server

logger = logging.getLogger("mcp_management_service")

MCP_REGISTRY_BASE_URL = "https://registry.modelcontextprotocol.io/v0.1/servers"


def _format_time(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if value is None:
        return "-"
    return str(value)


def _split_tags(value: str | None) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _safe_config_dict(record: Dict[str, Any]) -> Dict[str, Any]:
    config_json = record.get("config_json")
    return config_json if isinstance(config_json, dict) else {}


def _extract_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _is_container_record(record: Dict[str, Any] | None) -> bool:
    return str((record or {}).get("transport_type") or "").strip().lower() == "stdio"


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
    container_id = _extract_str(record.get("container_id"))
    if not container_id:
        raise McpValidationError("Container ID is missing")

    manager = MCPContainerManager()
    container_info = await manager.start_existing_mcp_container(container_id)
    if not _extract_str(container_info.get("mcp_url")):
        raise McpValidationError("Container runtime URL is missing")
    return container_info


def _normalize_mcp_registry_server(entry: Dict[str, Any]) -> Dict[str, Any] | None:
    server = entry.get("server") if isinstance(entry, dict) else None
    if not isinstance(server, dict):
        return None

    name = _extract_str(server.get("name"))
    if not name:
        return None

    normalized_entry = dict(entry)
    normalized_server = dict(server)
    if not isinstance(normalized_server.get("remotes"), list):
        normalized_server["remotes"] = []
    if not isinstance(normalized_server.get("packages"), list):
        normalized_server["packages"] = []
    normalized_entry["server"] = normalized_server
    return normalized_entry


def _normalize_community_remotes(record: Dict[str, Any], registry_json: Dict[str, Any]) -> List[Dict[str, str]]:
    remotes_out: List[Dict[str, str]] = []
    remotes = registry_json.get("remotes") if isinstance(registry_json, dict) else None
    if isinstance(remotes, list):
        for remote in remotes:
            if not isinstance(remote, dict):
                continue
            remote_url = _extract_str(remote.get("url"))
            remote_type = _extract_str(remote.get("type")).lower()
            if remote_url:
                remotes_out.append({"type": remote_type, "url": remote_url})

    if remotes_out:
        return remotes_out

    server_url = _extract_str(record.get("mcp_server"))
    if not server_url:
        return []

    transport_type = _extract_str(record.get("transport_type")).lower()
    default_type = "streamable-http" if transport_type == "http" else transport_type or "streamable-http"
    return [{"type": default_type, "url": server_url}]


def _normalize_community_card(record: Dict[str, Any]) -> Dict[str, Any]:
    registry_json = record.get("registry_json") if isinstance(record.get("registry_json"), dict) else {}
    remotes_out = _normalize_community_remotes(record, registry_json)
    packages = registry_json.get("packages") if isinstance(registry_json.get("packages"), list) else []
    published_at = record.get("create_time")
    updated_at = record.get("update_time")

    raw_transport_type = _extract_str(record.get("transport_type")).lower()
    normalized_transport_type = "stdio" if raw_transport_type in {"stdio", "container"} else "sse" if raw_transport_type == "sse" else "http"
    config_json = record.get("config_json") if isinstance(record.get("config_json"), dict) else None

    return {
        "communityId": record.get("community_id"),
        "name": _extract_str(record.get("mcp_name")),
        "version": _extract_str(record.get("version")),
        "description": _extract_str(record.get("description")),
        "source": "community",
        "transportType": normalized_transport_type,
        "serverUrl": _extract_str(record.get("mcp_server")),
        "configJson": config_json,
        "mcpRegistryJson": registry_json if registry_json else None,
        "tags": _split_tags(record.get("tags")),
        "remotes": remotes_out,
        "packages": packages,
        "status": "active",
        "isLatest": True,
        "publishedAt": published_at.isoformat() if isinstance(published_at, datetime) else _extract_str(published_at),
        "updatedAt": updated_at.isoformat() if isinstance(updated_at, datetime) else _extract_str(updated_at),
        "serverJson": registry_json if registry_json else {},
    }


async def list_community_mcp_services(
    *,
    search: str | None = None,
    transport_type: str | None = None,
    cursor: str | None = None,
    limit: int = 30,
) -> Dict[str, Any]:
    db_result = get_mcp_community_records(
        search=(search or "").strip() or None,
        transport_type=(transport_type or "").strip().lower() or None,
        cursor=(cursor or "").strip() or None,
        limit=max(1, min(limit, 100)),
    )

    items = [_normalize_community_card(record) for record in db_result.get("items", [])]
    return {
        "count": len(items),
        "nextCursor": db_result.get("nextCursor"),
        "items": items,
    }


def _normalize_transport_type(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if raw in {"stdio", "container"}:
        return "stdio"
    if raw == "sse":
        return "sse"
    return "http"


async def publish_community_mcp_service(*, tenant_id: str, user_id: str, mcp_id: int) -> int:
    source_record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not source_record:
        raise McpNotFoundError("MCP record not found")

    source_registry_json = source_record.get("registry_json") if isinstance(source_record.get("registry_json"), dict) else None
    source_config_json = source_record.get("config_json") if isinstance(source_record.get("config_json"), dict) else None

    community_id = create_mcp_community_record(
        mcp_data={
            "mcp_name": _extract_str(source_record.get("mcp_name")),
            "mcp_server": _extract_str(source_record.get("mcp_server")),
            "version": _extract_str(source_record.get("version")),
            "registry_json": source_registry_json,
            "transport_type": _normalize_transport_type(source_record.get("transport_type")),
            "config_json": source_config_json,
            "tags": source_record.get("tags") or "",
            "description": _extract_str(source_record.get("description")),
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
    next_config_json = existing_config_json
    if isinstance(next_registry_json, dict) and isinstance(next_registry_json.get("configJson"), dict):
        next_config_json = next_registry_json.get("configJson")

    update_mcp_community_record_by_id(
        community_id=community_id,
        tenant_id=tenant_id,
        user_id=user_id,
        name=name,
        description=description,
        tags=tags,
        version=version,
        registry_json=registry_json,
        config_json=next_config_json,
    )


async def delete_community_mcp_service(*, tenant_id: str, user_id: str, community_id: int) -> None:
    current = get_mcp_community_record_by_id_and_tenant(community_id=community_id, tenant_id=tenant_id)
    if not current:
        raise McpNotFoundError("Community MCP record not found")
    delete_mcp_community_record_by_id(community_id=community_id, tenant_id=tenant_id, user_id=user_id)


async def list_my_community_mcp_services(*, tenant_id: str) -> Dict[str, Any]:
    rows = list_mcp_community_records_by_tenant(tenant_id=tenant_id)
    items = [_normalize_community_card(row) for row in rows]
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
    normalized: List[Dict[str, Any]] = []
    if isinstance(raw_servers, list):
        for entry in raw_servers:
            normalized_item = _normalize_mcp_registry_server(entry)
            if normalized_item:
                normalized.append(normalized_item)

    metadata = payload.get("metadata") if isinstance(payload, dict) and isinstance(payload.get("metadata"), dict) else {}

    # Keep response shape aligned with official MCP registry API.
    return {
        "servers": normalized,
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
    service_name = (name or "").strip()
    if check_enabled_mcp_name_exists(mcp_name=service_name, tenant_id=tenant_id):
        raise McpNameConflictError("Enabled MCP name already exists")

    servers = mcp_config.mcpServers
    if len(servers) != 1:
        raise McpValidationError("Exactly one mcpServers entry is required")

    _, config = next(iter(servers.items()))
    command = (config.command or "").strip()
    if not command:
        raise McpValidationError("command is required")

    env_vars = dict(config.env or {})
    auth_token = (authorization_token or "").strip()
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
    container_info = await container_manager.start_mcp_container(
        service_name=service_name,
        tenant_id=tenant_id,
        user_id=user_id,
        env_vars=env_vars,
        host_port=port,
        image=config.image or NEXENT_MCP_DOCKER_IMAGE,
        full_command=full_command,
    )
    started_container_id: str | None = container_info.get("container_id")

    container_config = mcp_config.model_dump(exclude_none=True)

    try:
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
        )
    except MCPConnectionError:
        if started_container_id:
            try:
                cleanup_manager = MCPContainerManager()
                await cleanup_manager.stop_mcp_container(started_container_id)
            except Exception as cleanup_exc:
                logger.warning(f"Failed to cleanup container {started_container_id}: {cleanup_exc}")
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
) -> None:
    normalized_source = (source or "local").strip().lower()
    if normalized_source not in {"local", "mcp_registry", "community"}:
        raise McpValidationError(f"Invalid source: {source}")

    normalized_transport_type = (transport_type or "http").strip().lower()
    normalized_transport_type = "stdio" if normalized_transport_type == "container" else normalized_transport_type

    # mcp-tools add flow does not perform connectivity checks.
    # Health status remains unchecked until manual health check.
    status: bool | None = None

    if normalized_transport_type not in {"http", "sse", "stdio"}:
        raise McpValidationError(f"Invalid transport_type: {transport_type}")

    normalized_container_id = container_id if isinstance(container_id, str) and container_id else None
    config_json = container_config if normalized_transport_type == "stdio" and isinstance(container_config, dict) else None

    create_mcp_record(
        mcp_data={
            "mcp_name": name,
            "mcp_server": server_url,
            "status": status,
            "container_id": normalized_container_id,
            "authorization_token": authorization_token,
            "source": normalized_source,
            "version": version,
            "registry_json": registry_json,
            "transport_type": normalized_transport_type,
            "enabled": enabled,
            "tags": ",".join(tags or []),
            "description": description,
            "config_json": config_json,
        },
        tenant_id=tenant_id,
        user_id=user_id,
    )


def list_mcp_services(tenant_id: str) -> List[Dict[str, Any]]:
    records = get_mcp_records_by_tenant(tenant_id=tenant_id)
    services: List[Dict[str, Any]] = []

    container_status_map: Dict[str, str] = {}
    try:
        manager = MCPContainerManager()
        for container in manager.list_mcp_containers(tenant_id=tenant_id):
            container_id = _extract_str(container.get("container_id"))
            status = _extract_str(container.get("status")).lower()
            if not container_id:
                continue
            if status == "running":
                container_status_map[container_id] = "running"
            elif status:
                container_status_map[container_id] = "stopped"
    except Exception as exc:
        logger.warning(f"Failed to load container runtime status: {exc}")

    for record in records:
        source = (record.get("source") or "").lower()
        transport_type = (record.get("transport_type") or "").lower()
        enabled = bool(record.get("enabled"))
        status = record.get("status")
        registry_json = record.get("registry_json") if isinstance(record.get("registry_json"), dict) else None
        raw_config_json = record.get("config_json") if isinstance(record.get("config_json"), dict) else None

        container_id = _extract_str(record.get("container_id"))
        normalized_transport_type = "stdio" if transport_type in {"stdio", "container"} else "sse" if transport_type == "sse" else "http"
        record_config_json = raw_config_json if normalized_transport_type == "stdio" else None
        container_status = None
        if normalized_transport_type == "stdio":
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
            "updatedAt": _format_time(record.get("update_time")),
            "tags": _split_tags(record.get("tags")),
            "transportType": normalized_transport_type,
            "serverUrl": _extract_str(record.get("mcp_server")),
            "version": _extract_str(record.get("version")),
            "mcpRegistryJson": registry_json,
            "configJson": record_config_json,
            "tools": record.get("tools") or [],
            "healthStatus": "healthy" if status is True else "unhealthy" if status is False else "unchecked",
            "containerStatus": container_status,
            "authorizationToken": record.get("authorization_token") or "",
        })

    return services


async def list_mcp_service_tools_by_id(*, tenant_id: str, mcp_id: int) -> List[Dict[str, Any]]:
    record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not record:
        raise McpNotFoundError("MCP record not found")

    service_name = _extract_str(record.get("mcp_name"))
    server_url = _extract_str(record.get("mcp_server"))
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

    current_transport_type = (current_record.get("transport_type") or "").strip().lower()
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
        transport_type=(current_record.get("transport_type") or "streamable-http"),
        authorization_token=authorization_token,
        config_json=config_json,
        tags=tags,
    )


def update_mcp_service_legacy(
    *,
    tenant_id: str,
    user_id: str,
    current_name: str,
    new_name: str,
    description: str | None,
    server_url: str,
    authorization_token: str | None,
    tags: list[str] | None,
) -> None:
    current_record = get_mcp_manage_record_by_name(tenant_id=tenant_id, name=current_name)
    config_json = _safe_config_dict(current_record or {})

    if authorization_token:
        config_json["authorization_token"] = authorization_token
    else:
        config_json.pop("authorization_token", None)

    update_mcp_manage_service(
        tenant_id=tenant_id,
        user_id=user_id,
        current_name=current_name,
        new_name=new_name,
        description=description,
        server_url=server_url,
        config_json=config_json or None,
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
        current_name = str((current_record or {}).get("mcp_name") or "").strip()
        if current_name:
            records = get_mcp_records_by_tenant(tenant_id=tenant_id)
            current_name_lower = current_name.lower()
            for record in records:
                if int(record.get("mcp_id") or 0) == mcp_id:
                    continue

                record_name = str(record.get("mcp_name") or "").strip().lower()
                is_enabled = bool(record.get("enabled"))
                if is_enabled and record_name == current_name_lower:
                    raise McpNameConflictError("An enabled service already uses this name")

    authorization_token = current_record.get("authorization_token")

    if _is_container_record(current_record):
        if enabled:
            container_info = await _start_container_by_id_for_record(current_record)
            next_server_url = _extract_str(container_info.get("mcp_url"))
            next_container_id = _extract_str(container_info.get("container_id")) or _extract_str(current_record.get("container_id")) or None

            health_ok = False
            for attempt in range(10):
                try:
                    health_ok = await mcp_server_health(
                        remote_mcp_server=next_server_url,
                        authorization_token=authorization_token,
                    )
                except MCPConnectionError:
                    health_ok = False
                if health_ok:
                    break
                if attempt < 9:
                    await asyncio.sleep(1)
            if not health_ok:
                await _stop_container_without_remove_if_exists(next_container_id)
                update_mcp_record_runtime_fields_by_id(
                    mcp_id=mcp_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    container_id=next_container_id,
                    mcp_server=next_server_url,
                    status=False,
                )
                raise MCPConnectionError("MCP connection failed")

            update_mcp_record_runtime_fields_by_id(
                mcp_id=mcp_id,
                tenant_id=tenant_id,
                user_id=user_id,
                container_id=next_container_id,
                mcp_server=next_server_url,
                status=True,
            )
        else:
            current_container_id = _extract_str(current_record.get("container_id")) or None
            await _stop_container_without_remove_if_exists(current_container_id)
            update_mcp_record_runtime_fields_by_id(
                mcp_id=mcp_id,
                tenant_id=tenant_id,
                user_id=user_id,
                container_id=current_container_id,
                mcp_server=_extract_str(current_record.get("mcp_server")),
                status=None,
            )
    elif enabled:
        server_url = _extract_str(current_record.get("mcp_server"))
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


def update_mcp_service_enabled_legacy(
    *,
    tenant_id: str,
    user_id: str,
    name: str,
    enabled: bool,
) -> None:
    update_mcp_manage_enabled(
        tenant_id=tenant_id,
        user_id=user_id,
        name=name,
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
        current_container_id = _extract_str(current_record.get("container_id")) or None
        await _stop_container_without_remove_if_exists(current_container_id)
        await _remove_container_if_exists(current_container_id)

    delete_mcp_record_by_id(
        mcp_id=mcp_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )


def delete_mcp_service_legacy(
    *,
    tenant_id: str,
    user_id: str,
    name: str,
) -> None:
    delete_mcp_manage_service(
        tenant_id=tenant_id,
        user_id=user_id,
        name=name,
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

    server_url = str((record or {}).get("mcp_server") or "").strip()
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


async def check_mcp_service_health_legacy(
    *,
    tenant_id: str,
    user_id: str,
    name: str,
    server_url: str,
) -> str:
    current_record = get_mcp_manage_record_by_name(tenant_id=tenant_id, name=name)
    if not current_record:
        raise McpNotFoundError("MCP record not found")

    target_server_url = str(current_record.get("mcp_server") or "").strip()
    if target_server_url and target_server_url != server_url:
        raise McpValidationError("MCP record and server_url mismatch")

    config_json = _safe_config_dict(current_record or {})
    authorization_token = config_json.get("authorization_token")

    try:
        status = await mcp_server_health(
            remote_mcp_server=server_url,
            authorization_token=authorization_token,
        )
    except Exception as exc:
        logger.error(f"MCP health check failed: {exc}")
        status = False

    update_mcp_manage_status(
        tenant_id=tenant_id,
        user_id=user_id,
        name=name,
        status=status,
    )

    if not status:
        raise MCPConnectionError("MCP connection failed")

    return "healthy"
