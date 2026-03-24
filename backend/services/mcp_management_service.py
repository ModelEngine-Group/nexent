import logging
import asyncio
from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import urlencode

import aiohttp

from consts.exceptions import MCPConnectionError, MCPContainerError
from database.mcp_manage_db import (
    delete_mcp_manage_service,
    get_mcp_manage_record_by_name,
    update_mcp_manage_enabled,
    update_mcp_manage_service,
    update_mcp_manage_status,
)
from database.remote_mcp_db import (
    delete_mcp_record_by_id,
    create_mcp_record,
    get_mcp_record_by_id_and_tenant,
    get_mcp_records_by_tenant,
    update_mcp_record_enabled_by_id,
    update_mcp_record_manage_fields_by_id,
    update_mcp_record_runtime_fields_by_id,
    update_mcp_record_status_by_id,
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
        raise ValueError("Container ID is missing")

    manager = MCPContainerManager()
    container_info = await manager.start_existing_mcp_container(container_id)
    if not _extract_str(container_info.get("mcp_url")):
        raise ValueError("Container runtime URL is missing")
    return container_info


def _normalize_market_server(entry: Dict[str, Any]) -> Dict[str, Any] | None:
    server = entry.get("server") if isinstance(entry, dict) else None
    if not isinstance(server, dict):
        return None

    name = _extract_str(server.get("name"))
    if not name:
        return None

    version = _extract_str(server.get("version"))
    description = _extract_str(server.get("description"))

    remotes_out: List[Dict[str, str]] = []
    packages_out: List[Dict[str, Any]] = []

    remotes = server.get("remotes")
    if isinstance(remotes, list):
        for remote in remotes:
            if not isinstance(remote, dict):
                continue
            remote_url = _extract_str(remote.get("url"))
            remote_type = _extract_str(remote.get("type")).lower()
            if remote_url:
                remotes_out.append({"type": remote_type, "url": remote_url})

    packages = server.get("packages")
    if isinstance(packages, list):
        for package in packages:
            if not isinstance(package, dict):
                continue

            transport_raw = package.get("transport")
            transport = {
                "type": _extract_str(transport_raw.get("type")) if isinstance(transport_raw, dict) else "",
                "url": _extract_str(transport_raw.get("url")) if isinstance(transport_raw, dict) else "",
            }

            packages_out.append({
                "registryType": _extract_str(package.get("registryType")),
                "identifier": _extract_str(package.get("identifier")),
                "version": _extract_str(package.get("version")),
                "runtimeHint": _extract_str(package.get("runtimeHint")),
                "transport": transport,
            })

    official_meta = {}
    if isinstance(entry.get("_meta"), dict):
        official_meta = entry.get("_meta", {}).get("io.modelcontextprotocol.registry/official", {}) or {}

    return {
        "name": name,
        "version": version,
        "description": description,
        "remotes": remotes_out,
        "packages": packages_out,
        "status": _extract_str(official_meta.get("status")),
        "isLatest": bool(official_meta.get("isLatest")),
        "publishedAt": _extract_str(official_meta.get("publishedAt")),
        "updatedAt": _extract_str(official_meta.get("updatedAt")),
        "serverJson": server,
    }


def _pick_latest_market_servers(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for item in items:
        key = str(item.get("name") or "").strip().lower()
        if not key:
            continue
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = item
            continue

        existing_latest = bool(existing.get("isLatest"))
        current_latest = bool(item.get("isLatest"))
        if current_latest and not existing_latest:
            grouped[key] = item
            continue
        if current_latest == existing_latest:
            existing_time = _extract_str(existing.get("updatedAt")) or _extract_str(existing.get("publishedAt"))
            current_time = _extract_str(item.get("updatedAt")) or _extract_str(item.get("publishedAt"))
            if current_time > existing_time:
                grouped[key] = item

    result = list(grouped.values())
    result.sort(key=lambda x: (_extract_str(x.get("updatedAt")) or _extract_str(x.get("publishedAt"))), reverse=True)
    return result


async def list_market_mcp_services(
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
            normalized_item = _normalize_market_server(entry)
            if normalized_item:
                normalized.append(normalized_item)

    metadata = payload.get("metadata") if isinstance(payload, dict) and isinstance(payload.get("metadata"), dict) else {}

    return {
        "count": len(normalized),
        "nextCursor": _extract_str(metadata.get("nextCursor")),
        "items": normalized,
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
    mcp_registry_json: Dict[str, Any] | None,
    enabled: bool = False,
    container_id: str | None = None,
) -> None:
    normalized_source = (source or "local").strip().lower()
    normalized_source = "mcp_registry" if normalized_source in {"market", "registry"} else normalized_source
    if normalized_source not in {"local", "mcp_registry"}:
        raise ValueError(f"Invalid source: {source}")

    normalized_transport_type = (transport_type or "http").strip().lower()
    normalized_transport_type = "stdio" if normalized_transport_type == "container" else normalized_transport_type

    # mcp-tools add flow does not perform connectivity checks.
    # Health status remains unchecked until manual health check.
    status: bool | None = None

    if normalized_transport_type not in {"http", "sse", "stdio"}:
        raise ValueError(f"Invalid transport_type: {transport_type}")

    normalized_container_id = container_id if isinstance(container_id, str) and container_id else None
    config_json = container_config if normalized_transport_type == "stdio" and isinstance(container_config, dict) else None

    create_mcp_record(
        mcp_data={
            "mcp_name": name,
            "mcp_server": server_url,
            "status": status,
            "container_id": normalized_container_id,
            "authorization_token": authorization_token,
            "souce": normalized_source,
            "version": version,
            "mcp_registry_json": mcp_registry_json,
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
        souce = (record.get("souce") or record.get("source_type") or "").lower()
        transport_type = (record.get("transport_type") or "").lower()
        enabled = bool(record.get("enabled"))
        status = record.get("status")
        registry_json = record.get("mcp_registry_json") if isinstance(record.get("mcp_registry_json"), dict) else None
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
            "source": souce or "local",
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
        raise ValueError("MCP record not found")

    service_name = _extract_str(record.get("mcp_name"))
    server_url = _extract_str(record.get("mcp_server"))
    if not service_name or not server_url:
        raise ValueError("MCP record is missing runtime connection fields")

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
        raise ValueError("MCP record not found")

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
        souce=(current_record.get("souce") or current_record.get("source_type") or "local"),
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
        raise ValueError("MCP record not found")

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
                    raise ValueError("An enabled service already uses this name")

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
        raise ValueError("MCP record not found")

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
        raise ValueError("MCP record not found")

    server_url = str((record or {}).get("mcp_server") or "").strip()
    if not server_url:
        raise ValueError("MCP server URL is empty")

    authorization_token = record.get("authorization_token")

    try:
        status = await mcp_server_health(
            remote_mcp_server=server_url,
            authorization_token=authorization_token,
        )
    except Exception as exc:
        logger.error(f"MCP health check failed: {exc}")
        status = False

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
        raise ValueError("MCP record not found")

    target_server_url = str(current_record.get("mcp_server") or "").strip()
    if target_server_url and target_server_url != server_url:
        raise ValueError("MCP record and server_url mismatch")

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
