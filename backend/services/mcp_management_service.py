import logging
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List
from urllib.parse import urlencode

import aiohttp

from consts.exceptions import MCPConnectionError, MCPNameIllegal
from database.mcp_manage_db import (
    check_mcp_manage_name_exists,
    create_mcp_manage_service,
    delete_mcp_manage_service,
    get_mcp_manage_record_by_name,
    get_mcp_manage_records,
    update_mcp_manage_enabled,
    update_mcp_manage_service,
    update_mcp_manage_status,
)
from database.remote_mcp_db import (
    check_mcp_name_exists,
    create_mcp_record,
    delete_mcp_record_by_name_and_url,
    update_mcp_record_by_name_and_url,
)
from services.remote_mcp_service import mcp_server_health

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


def _is_http_transport(record: Dict[str, Any] | None) -> bool:
    transport_type = str((record or {}).get("transport_type") or "").strip().lower()
    return transport_type in {"streamable-http", "sse"}


def _extract_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _normalize_market_server(entry: Dict[str, Any]) -> Dict[str, Any] | None:
    server = entry.get("server") if isinstance(entry, dict) else None
    if not isinstance(server, dict):
        return None

    name = _extract_str(server.get("name"))
    if not name:
        return None

    title = _extract_str(server.get("title")) or name
    version = _extract_str(server.get("version"))
    website_url = _extract_str(server.get("websiteUrl"))

    description = _extract_str(server.get("description")) or "MCP 服务"

    tags: List[str] = []
    server_type = "容器"
    server_url = ""
    remotes_out: List[Dict[str, str]] = []

    remotes = server.get("remotes")
    if isinstance(remotes, list):
        for remote in remotes:
            if not isinstance(remote, dict):
                continue
            remote_url = _extract_str(remote.get("url"))
            remote_type = _extract_str(remote.get("type")).lower()
            if remote_url and remote_type in {"sse", "streamable-http", "http", ""}:
                remotes_out.append({"type": remote_type or "remote", "url": remote_url})
                server_url = remote_url
                server_type = "SSE" if remote_type == "sse" else "HTTP"
                break

    if not server_url:
        packages = server.get("packages")
        if isinstance(packages, list) and packages:
            first_pkg = packages[0] if isinstance(packages[0], dict) else {}
            registry_type = _extract_str(first_pkg.get("registryType"))
            identifier = _extract_str(first_pkg.get("identifier"))
            version = _extract_str(first_pkg.get("version"))
            runtime_hint = _extract_str(first_pkg.get("runtimeHint"))
            transport = first_pkg.get("transport") if isinstance(first_pkg, dict) else {}
            transport_url = _extract_str((transport or {}).get("url")) if isinstance(transport, dict) else ""
            transport_type = _extract_str((transport or {}).get("type")).lower() if isinstance(transport, dict) else ""

            if transport_url:
                server_url = transport_url
                server_type = "SSE" if transport_type == "sse" else "HTTP"
                remotes_out.append({"type": transport_type or "remote", "url": transport_url})
            else:
                # Non-HTTP package format (npm/pypi/oci stdio etc.) is represented as container/runtime install target.
                pkg_base = f"{registry_type}:{identifier}" if registry_type and identifier else identifier
                if version and pkg_base:
                    pkg_base = f"{pkg_base}@{version}"
                if runtime_hint and pkg_base:
                    server_url = f"{runtime_hint}://{pkg_base}"
                elif pkg_base:
                    server_url = f"package://{pkg_base}"
                else:
                    server_url = "package://unknown"
                server_type = "容器"

            if registry_type:
                tags.append(registry_type)
            if runtime_hint:
                tags.append(runtime_hint)

    version = _extract_str(server.get("version"))
    if version:
        tags.append(version)

    dedup_tags: List[str] = []
    seen = set()
    for tag in tags:
        normalized = tag.strip()
        if not normalized:
            continue
        low = normalized.lower()
        if low in seen:
            continue
        seen.add(low)
        dedup_tags.append(normalized)

    official_meta = {}
    if isinstance(entry.get("_meta"), dict):
        official_meta = entry.get("_meta", {}).get("io.modelcontextprotocol.registry/official", {}) or {}

    return {
        "name": name,
        "title": title,
        "version": version,
        "description": description,
        "websiteUrl": website_url,
        "remotes": remotes_out,
        "serverUrl": server_url,
        "serverType": server_type,
        "tags": dedup_tags,
        "status": _extract_str(official_meta.get("status")) or "active",
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
    server_type: str,
    server_url: str,
    tags: list[str] | None,
    authorization_token: str | None,
    container_config: Dict[str, Any] | None,
) -> None:
    if check_mcp_manage_name_exists(tenant_id=tenant_id, name=name):
        raise MCPNameIllegal("MCP name already exists")

    normalized_server_type = (server_type or "HTTP").strip().upper()

    # mcp-tools add flow does not perform connectivity checks.
    # All newly added services remain disabled and unchecked until manual enable/health check.
    status: bool | None = None

    source_type = "registry" if source == "公共市场" else "local"
    if normalized_server_type == "SSE":
        transport_type = "sse"
    elif normalized_server_type == "HTTP":
        transport_type = "streamable-http"
    else:
        transport_type = "stdio"

    config_json: Dict[str, Any] = {}
    if authorization_token:
        config_json["authorization_token"] = authorization_token
    if container_config:
        config_json["container_config"] = container_config

    try:
        create_mcp_manage_service(
            tenant_id=tenant_id,
            user_id=user_id,
            name=name,
            server_url=server_url,
            source_type=source_type,
            transport_type=transport_type,
            tags=tags,
            category=description,
            config_json=config_json or None,
            enabled=False,
            status=status,
        )
    except Exception:
        raise


def list_mcp_services(tenant_id: str) -> List[Dict[str, Any]]:
    records = get_mcp_manage_records(tenant_id=tenant_id)
    services: List[Dict[str, Any]] = []

    for record in records:
        source_type = (record.get("source_type") or "").lower()
        transport_type = (record.get("transport_type") or "").lower()
        enabled = bool(record.get("enabled"))
        status = record.get("status")
        config_json = _safe_config_dict(record)

        services.append({
            "name": record.get("mcp_name") or "未命名 MCP",
            "description": record.get("category") or "MCP 服务",
            "source": "公共市场" if source_type == "registry" else "本地",
            "status": "已启用" if enabled else "未启用",
            "updatedAt": _format_time(record.get("update_time")),
            "tags": _split_tags(record.get("tags")),
            "serverType": "容器" if transport_type == "stdio" else "SSE" if transport_type == "sse" else "HTTP",
            "serverUrl": record.get("mcp_server") or "-",
            "tools": record.get("tools") or [],
            "healthStatus": "正常" if status is True else "异常" if status is False else "未检测",
            "containerStatus": record.get("container_status") or None,
            "authorizationToken": config_json.get("authorization_token") or "",
        })

    return services


def update_mcp_service(
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
    current_server_url = str((current_record or {}).get("mcp_server") or "").strip()
    next_config_json = _safe_config_dict(current_record or {})

    # Keep token in config_json as single source for mcp-tools management.
    if authorization_token:
        next_config_json["authorization_token"] = authorization_token
    else:
        next_config_json.pop("authorization_token", None)

    update_mcp_manage_service(
        tenant_id=tenant_id,
        user_id=user_id,
        current_name=current_name,
        new_name=new_name,
        description=description,
        server_url=server_url,
        config_json=next_config_json or None,
        tags=tags,
    )

    if _is_http_transport(current_record) and current_server_url:
        update_mcp_record_by_name_and_url(
            update_data=SimpleNamespace(
                current_service_name=current_name,
                current_mcp_url=current_server_url,
                new_service_name=new_name,
                new_mcp_url=server_url,
                new_authorization_token=authorization_token,
            ),
            tenant_id=tenant_id,
            user_id=user_id,
        )


def update_mcp_service_enabled(
    *,
    tenant_id: str,
    user_id: str,
    name: str,
    enabled: bool,
) -> None:
    current_record = get_mcp_manage_record_by_name(tenant_id=tenant_id, name=name)

    update_mcp_manage_enabled(
        tenant_id=tenant_id,
        user_id=user_id,
        name=name,
        enabled=enabled,
    )

    if not _is_http_transport(current_record):
        return

    server_url = str((current_record or {}).get("mcp_server") or "").strip()
    if not server_url:
        return

    config_json = _safe_config_dict(current_record or {})
    authorization_token = config_json.get("authorization_token") or None
    status = current_record.get("status") if isinstance(current_record, dict) else None

    if not enabled:
        delete_mcp_record_by_name_and_url(
            mcp_name=name,
            mcp_server=server_url,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return

    if check_mcp_name_exists(mcp_name=name, tenant_id=tenant_id):
        update_mcp_record_by_name_and_url(
            update_data=SimpleNamespace(
                current_service_name=name,
                current_mcp_url=server_url,
                new_service_name=name,
                new_mcp_url=server_url,
                new_authorization_token=authorization_token,
            ),
            tenant_id=tenant_id,
            user_id=user_id,
            status=status,
        )
        return

    create_mcp_record(
        mcp_data={
            "mcp_name": name,
            "mcp_server": server_url,
            "status": status,
            "container_id": None,
            "authorization_token": authorization_token,
        },
        tenant_id=tenant_id,
        user_id=user_id,
    )


def delete_mcp_service(
    *,
    tenant_id: str,
    user_id: str,
    name: str,
) -> None:
    current_record = get_mcp_manage_record_by_name(tenant_id=tenant_id, name=name)

    delete_mcp_manage_service(
        tenant_id=tenant_id,
        user_id=user_id,
        name=name,
    )

    current_server_url = str((current_record or {}).get("mcp_server") or "").strip()
    if _is_http_transport(current_record) and current_server_url:
        delete_mcp_record_by_name_and_url(
            mcp_name=name,
            mcp_server=current_server_url,
            tenant_id=tenant_id,
            user_id=user_id,
        )


async def check_mcp_service_health(
    *,
    tenant_id: str,
    user_id: str,
    name: str,
    server_url: str,
) -> str:
    record = get_mcp_manage_record_by_name(tenant_id=tenant_id, name=name)
    config_json = _safe_config_dict(record or {})
    authorization_token = config_json.get("authorization_token")

    try:
        status = await mcp_server_health(
            remote_mcp_server=server_url,
            authorization_token=authorization_token,
        )
    except BaseException as exc:
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

    return "正常"
