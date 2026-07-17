"""MCP installation and tool-binding operations for NL2AGENT drafts."""

import asyncio
import hashlib
import json
import logging
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import urlparse

from consts.exceptions import (
    AgentRunException,
    Nl2AgentExternalServiceError,
    Nl2AgentOperationError,
    Nl2AgentValidationError,
)
from consts.model import MCPConfigRequest, ToolInstanceInfoRequest

logger = logging.getLogger(__name__)
_LOCK_HEARTBEAT_INTERVAL_SECONDS = 60


@dataclass(frozen=True)
class McpInstallationDependencies:
    """External operations used by the recoverable MCP installation saga."""

    get_owned_draft: Callable[..., Dict[str, Any]]
    get_session_catalogs: Callable[..., Dict[str, List[Dict[str, Any]]]]
    normalize_candidate: Callable[..., Dict[str, Any]]
    acquire_installation_lock: Callable[..., Optional[str]]
    renew_installation_lock: Callable[..., bool]
    release_installation_lock: Callable[..., Any]
    update_mcp_workflow: Callable[..., Any]
    get_mcp_records: Callable[..., List[Dict[str, Any]]]
    add_remote_mcp: Callable[..., Awaitable[int]]
    add_container_mcp: Callable[..., Awaitable[Dict[str, Any]]]
    update_remote_mcp: Callable[..., None]
    reconfigure_container_mcp: Callable[..., Awaitable[None]]
    get_mcp_record: Callable[..., Optional[Dict[str, Any]]]
    discover_tools: Callable[..., Awaitable[List[Any]]]
    upsert_discovered_tools: Callable[..., List[Dict[str, Any]]]
    recommendation_id: Callable[[str, Dict[str, Any]], str]
    validate_remote_url: Callable[[str], str]


def installation_key(
    draft_agent_id: int,
    recommendation_id: str,
    option_id: str,
) -> str:
    """Create a stable idempotency key without including submitted secrets."""
    payload = f"{draft_agent_id}:{recommendation_id}:{option_id}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def installation_lock_key(
    draft_agent_id: int,
    recommendation_id: str,
) -> str:
    """Create one mutex scope shared by every option for a recommendation."""
    payload = f"{draft_agent_id}:{recommendation_id}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _record_installation_key(record: Dict[str, Any]) -> Optional[str]:
    registry_json = record.get("registry_json")
    if isinstance(registry_json, str):
        try:
            registry_json = json.loads(registry_json)
        except json.JSONDecodeError:
            return None
    if not isinstance(registry_json, dict):
        return None
    value = registry_json.get("nl2agent_installation_key")
    return str(value) if value else None


def _resolve_recommendation(
    dependencies: McpInstallationDependencies,
    catalogs: Dict[str, List[Dict[str, Any]]],
    recommendation_id: str,
) -> tuple[str, Dict[str, Any]]:
    for source, key in (
        ("registry", "registry_results"),
        ("community", "community_results"),
    ):
        for item in catalogs.get(key, []):
            if dependencies.recommendation_id(source, item) == recommendation_id:
                return source, item
    raise AgentRunException("MCP recommendation is not part of this NL2AGENT session.")


async def install_recommended_mcp(
    dependencies: McpInstallationDependencies,
    *,
    agent_id: int,
    recommendation_id: str,
    option_id: str,
    config_values: Dict[str, Any],
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Install an MCP and persist redacted success or failure state."""
    stable_key = installation_key(agent_id, recommendation_id, option_id)
    lock_key = installation_lock_key(agent_id, recommendation_id)
    lock_token = dependencies.acquire_installation_lock(
        tenant_id,
        agent_id,
        lock_key,
    )
    if not lock_token:
        raise AgentRunException(
            "This MCP installation is already in progress. Retry after it completes."
        )
    try:
        return await _perform_with_lock_heartbeat(
            dependencies,
            agent_id=agent_id,
            recommendation_id=recommendation_id,
            option_id=option_id,
            config_values=config_values,
            tenant_id=tenant_id,
            user_id=user_id,
            stable_key=stable_key,
            lock_key=lock_key,
            lock_token=lock_token,
        )
    except Exception as exc:
        try:
            dependencies.update_mcp_workflow(
                tenant_id,
                agent_id,
                recommendation_id,
                option_id=option_id,
                status="failed",
                installation_key=stable_key,
                error=(
                    "MCP installation failed. Review the option configuration "
                    "and retry."
                ),
            )
        except Exception:
            logger.exception("Failed to persist NL2AGENT MCP failure state")
        if isinstance(exc, AgentRunException):
            raise
        raise Nl2AgentExternalServiceError(
            "MCP installation failed during connection or tool discovery."
        ) from exc
    finally:
        dependencies.release_installation_lock(
            tenant_id,
            agent_id,
            lock_key,
            lock_token,
        )


async def _perform_with_lock_heartbeat(
    dependencies: McpInstallationDependencies,
    *,
    agent_id: int,
    recommendation_id: str,
    option_id: str,
    config_values: Dict[str, Any],
    tenant_id: str,
    user_id: str,
    stable_key: str,
    lock_key: str,
    lock_token: str,
) -> Dict[str, Any]:
    """Run installation while renewing its ownership lease."""

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(_LOCK_HEARTBEAT_INTERVAL_SECONDS)
            if not dependencies.renew_installation_lock(
                tenant_id, agent_id, lock_key, lock_token
            ):
                raise AgentRunException(
                    "MCP installation lock ownership was lost. Retry installation."
                )

    operation = asyncio.create_task(
        _perform_recommended_mcp_install(
            dependencies,
            agent_id=agent_id,
            recommendation_id=recommendation_id,
            option_id=option_id,
            config_values=config_values,
            tenant_id=tenant_id,
            user_id=user_id,
            stable_key=stable_key,
        )
    )
    renewal = asyncio.create_task(heartbeat())
    try:
        done, _ = await asyncio.wait(
            {operation, renewal}, return_when=asyncio.FIRST_COMPLETED
        )
        if operation in done:
            return await operation
        operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)
        await renewal
        raise AgentRunException("MCP installation lock renewal stopped unexpectedly.")
    finally:
        renewal.cancel()
        await asyncio.gather(renewal, return_exceptions=True)


async def _perform_recommended_mcp_install(
    dependencies: McpInstallationDependencies,
    *,
    agent_id: int,
    recommendation_id: str,
    option_id: str,
    config_values: Dict[str, Any],
    tenant_id: str,
    user_id: str,
    stable_key: str,
) -> Dict[str, Any]:
    """Resolve, install, health-check, and discover one MCP recommendation."""
    dependencies.get_owned_draft(agent_id, tenant_id)
    catalogs = dependencies.get_session_catalogs(tenant_id, agent_id)
    source, raw = _resolve_recommendation(
        dependencies,
        catalogs,
        recommendation_id,
    )
    normalized = dependencies.normalize_candidate(source, raw)
    option = next(
        (
            candidate
            for candidate in normalized.get("install_options", [])
            if candidate.get("option_id") == option_id
        ),
        None,
    )
    if not option:
        raise Nl2AgentValidationError("Invalid MCP installation option.")
    if not option.get("supported", True):
        raise Nl2AgentValidationError(
            option.get("unsupported_reason")
            or "This MCP installation option is unsupported."
        )
    dependencies.update_mcp_workflow(
        tenant_id,
        agent_id,
        recommendation_id,
        option_id=option_id,
        status="installing",
        installation_key=stable_key,
    )

    registry_json = raw.get("registryJson") or raw.get("registry_json")
    registry_root = registry_json if isinstance(registry_json, dict) else raw
    server = (
        registry_root.get("server")
        if isinstance(registry_root.get("server"), dict)
        else registry_root
    )
    name = str(server.get("name") or raw.get("name") or "recommended-mcp")[:100]
    description = str(server.get("description") or raw.get("description") or "")
    field_values = config_values.get("fields") or {}
    if not isinstance(field_values, dict):
        raise Nl2AgentValidationError(
            "MCP configuration fields must be an object."
        )
    resolved_values = _validate_configuration(option, field_values)
    authorization_token, custom_headers = _resolve_headers(option, resolved_values)

    persisted_registry_json = deepcopy(raw)
    persisted_registry_json["nl2agent_installation_key"] = stable_key
    record = next(
        (
            item
            for item in dependencies.get_mcp_records(tenant_id)
            if _record_installation_key(item) == stable_key
        ),
        None,
    )
    mcp_id = int(record["mcp_id"]) if record else None
    persisted_source = "mcp_registry" if source == "registry" else source

    if option.get("type") == "remote":
        mcp_id = await _install_remote(
            dependencies,
            option=option,
            raw=raw,
            name=name,
            description=description,
            persisted_source=persisted_source,
            persisted_registry_json=persisted_registry_json,
            resolved_values=resolved_values,
            authorization_token=authorization_token,
            custom_headers=custom_headers,
            tenant_id=tenant_id,
            user_id=user_id,
            existing_mcp_id=mcp_id,
        )
    else:
        mcp_id = await _install_container(
            dependencies,
            option=option,
            option_id=option_id,
            raw=raw,
            name=name,
            description=description,
            persisted_source=persisted_source,
            persisted_registry_json=persisted_registry_json,
            resolved_values=resolved_values,
            authorization_token=authorization_token,
            tenant_id=tenant_id,
            user_id=user_id,
            existing_mcp_id=mcp_id,
        )

    return await _discover_and_complete(
        dependencies,
        agent_id=agent_id,
        recommendation_id=recommendation_id,
        option_id=option_id,
        stable_key=stable_key,
        source=source,
        name=name,
        mcp_id=mcp_id,
        authorization_token=authorization_token,
        custom_headers=custom_headers,
        tenant_id=tenant_id,
        user_id=user_id,
    )


def _validate_configuration(
    option: Dict[str, Any],
    field_values: Dict[str, Any],
) -> Dict[str, Any]:
    resolved_values: Dict[str, Any] = {}
    for field in option.get("fields", []):
        value = field_values.get(field.get("key"))
        if value in (None, ""):
            value = field.get("default")
        label = field.get("label") or field.get("name")
        if field.get("required") and value in (None, ""):
            raise Nl2AgentValidationError(
                f"Missing required MCP configuration: {label}"
            )
        if value in (None, ""):
            continue
        _validate_mcp_field_value(field, value, label)
        resolved_values[field.get("key")] = value
    return resolved_values


def _validate_mcp_field_value(
    field: Dict[str, Any],
    value: Any,
    label: Any,
) -> None:
    field_type = field.get("type")
    if field_type == "json" and isinstance(value, str):
        try:
            json.loads(value)
        except json.JSONDecodeError as exc:
            raise Nl2AgentValidationError(
                f"Invalid JSON for MCP configuration: {label}"
            ) from exc
    elif field_type == "number":
        try:
            float(value)
        except (TypeError, ValueError) as exc:
            raise Nl2AgentValidationError(
                f"Invalid number for MCP configuration: {label}"
            ) from exc
    elif field_type == "url":
        parsed_field_url = urlparse(str(value))
        if (
            parsed_field_url.scheme not in {"http", "https"}
            or not parsed_field_url.netloc
            or re.search(r"\{[^{}]+\}", str(value))
        ):
            raise Nl2AgentValidationError(
                f"Invalid URL for MCP configuration: {label}"
            )

    choices = field.get("choices") or []
    if choices and str(value) not in set(map(str, choices)):
        raise Nl2AgentValidationError(
            f"Invalid choice for MCP configuration: {label}"
        )


def _resolve_headers(
    option: Dict[str, Any],
    resolved_values: Dict[str, Any],
) -> tuple[Optional[str], Dict[str, str]]:
    authorization_token = None
    custom_headers: Dict[str, str] = {}
    for field in option.get("fields", []):
        value = resolved_values.get(field.get("key"))
        if value in (None, "") or field.get("category") != "header":
            continue
        if str(field.get("name") or "").lower() == "authorization":
            authorization_token = str(value)
        else:
            custom_headers[str(field.get("name"))] = str(value)
    return authorization_token, custom_headers


async def _install_remote(
    dependencies: McpInstallationDependencies,
    *,
    option: Dict[str, Any],
    raw: Dict[str, Any],
    name: str,
    description: str,
    persisted_source: str,
    persisted_registry_json: Dict[str, Any],
    resolved_values: Dict[str, Any],
    authorization_token: Optional[str],
    custom_headers: Dict[str, str],
    tenant_id: str,
    user_id: str,
    existing_mcp_id: Optional[int],
) -> int:
    server_url = option.get("server_url_template")
    if not server_url:
        url_field = next(
            (
                field
                for field in option.get("fields", [])
                if field.get("name") == "server_url"
            ),
            None,
        )
        server_url = resolved_values.get(url_field.get("key")) if url_field else None
    for field in option.get("fields", []):
        if field.get("category") != "variable":
            continue
        value = resolved_values.get(field.get("key"))
        if value in (None, ""):
            continue
        variable_name = str(field.get("name"))
        server_url = str(server_url).replace(
            "${" + variable_name + "}",
            str(value),
        )
        server_url = str(server_url).replace(
            "{" + variable_name + "}",
            str(value),
        )
    if not server_url or re.search(r"\{[^{}]+\}", str(server_url)):
        raise Nl2AgentValidationError(
            "MCP server URL contains unresolved configuration variables."
        )
    parsed_url = urlparse(str(server_url))
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise Nl2AgentValidationError(
            "MCP server URL must be a valid HTTP or HTTPS URL."
        )
    server_url = dependencies.validate_remote_url(str(server_url))
    if existing_mcp_id is not None:
        dependencies.update_remote_mcp(
            tenant_id=tenant_id,
            user_id=user_id,
            mcp_id=existing_mcp_id,
            new_name=name,
            description=description,
            server_url=str(server_url),
            authorization_token=authorization_token,
            custom_headers=custom_headers or None,
            tags=raw.get("tags") or [],
        )
        return existing_mcp_id
    return await dependencies.add_remote_mcp(
        tenant_id=tenant_id,
        user_id=user_id,
        name=name,
        description=description,
        source=persisted_source,
        server_url=server_url,
        tags=raw.get("tags") or [],
        authorization_token=authorization_token,
        custom_headers=custom_headers or None,
        container_config=None,
        registry_json=persisted_registry_json,
        enabled=True,
    )


async def _install_container(
    dependencies: McpInstallationDependencies,
    *,
    option: Dict[str, Any],
    option_id: str,
    raw: Dict[str, Any],
    name: str,
    description: str,
    persisted_source: str,
    persisted_registry_json: Dict[str, Any],
    resolved_values: Dict[str, Any],
    authorization_token: Optional[str],
    tenant_id: str,
    user_id: str,
    existing_mcp_id: Optional[int],
) -> int:
    config_json = deepcopy(raw.get("configJson") or raw.get("config_json"))
    if option_id.startswith("package-"):
        config_json = _build_package_config(option, name, resolved_values)
    elif isinstance(config_json, dict):
        _merge_environment(config_json, option, resolved_values)

    config_field = next(
        (
            field
            for field in option.get("fields", [])
            if field.get("name") == "config_json"
        ),
        None,
    )
    if not isinstance(config_json, dict) and config_field:
        submitted_config = resolved_values.get(config_field.get("key"))
        try:
            config_json = (
                json.loads(submitted_config)
                if isinstance(submitted_config, str)
                else submitted_config
            )
        except json.JSONDecodeError as exc:
            raise Nl2AgentValidationError(
                "MCP container configuration must be valid JSON."
            ) from exc

    port_field = next(
        (field for field in option.get("fields", []) if field.get("name") == "port"),
        None,
    )
    port = resolved_values.get(port_field.get("key")) if port_field else None
    try:
        port_number = int(port)
    except (TypeError, ValueError) as exc:
        raise Nl2AgentValidationError(
            "MCP container port must be an integer."
        ) from exc
    if not 1 <= port_number <= 65535:
        raise Nl2AgentValidationError(
            "MCP container port must be between 1 and 65535."
        )
    if not isinstance(config_json, dict):
        raise Nl2AgentValidationError(
            "This MCP requires container configuration and a port."
        )
    mcp_config = MCPConfigRequest(**config_json)
    if existing_mcp_id is not None:
        await dependencies.reconfigure_container_mcp(
            tenant_id=tenant_id,
            user_id=user_id,
            mcp_id=existing_mcp_id,
            name=name,
            description=description,
            source=persisted_source,
            tags=raw.get("tags") or [],
            authorization_token=authorization_token,
            registry_json=persisted_registry_json,
            port=port_number,
            mcp_config=mcp_config,
        )
        return existing_mcp_id
    result = await dependencies.add_container_mcp(
        tenant_id=tenant_id,
        user_id=user_id,
        name=name,
        description=description,
        source=persisted_source,
        tags=raw.get("tags") or [],
        authorization_token=authorization_token,
        registry_json=persisted_registry_json,
        port=port_number,
        mcp_config=mcp_config,
    )
    return int(result["mcp_id"])


def _build_package_config(
    option: Dict[str, Any],
    name: str,
    resolved_values: Dict[str, Any],
) -> Dict[str, Any]:
    identifier = option.get("package_identifier")
    runtime = str(
        option.get("runtime_hint") or option.get("registry_type") or "npx"
    ).lower()
    command = {"npm": "npx", "npx": "npx", "pypi": "uvx", "uvx": "uvx"}.get(
        runtime,
        runtime,
    )
    if not identifier or command not in {"npx", "uvx"}:
        raise Nl2AgentValidationError("Unsupported MCP package runtime.")
    environment: Dict[str, str] = {}
    runtime_args: List[str] = []
    package_args: List[str] = []
    for field in option.get("fields", []):
        value = resolved_values.get(field.get("key"))
        if value in (None, ""):
            continue
        category = field.get("category")
        if category == "environment":
            environment[str(field.get("name"))] = str(value)
        elif category in {"runtime_argument", "package_argument"}:
            rendered = str(value)
            if field.get("argument_type") == "named" and field.get("argument_name"):
                rendered = f"{field.get('argument_name')}={rendered}"
            target = runtime_args if category == "runtime_argument" else package_args
            target.append(rendered)
    args = [*runtime_args, identifier, *package_args]
    return {
        "mcpServers": {name: {"command": command, "args": args, "env": environment}}
    }


def _merge_environment(
    config_json: Dict[str, Any],
    option: Dict[str, Any],
    resolved_values: Dict[str, Any],
) -> None:
    server_configs = config_json.get("mcpServers")
    target_config = (
        next(
            (
                server_config
                for server_config in server_configs.values()
                if isinstance(server_config, dict)
            ),
            None,
        )
        if isinstance(server_configs, dict)
        else None
    )
    if target_config is None:
        return
    environment = target_config.setdefault("env", {})
    if not isinstance(environment, dict):
        raise Nl2AgentValidationError(
            "MCP container environment configuration must be an object."
        )
    for field in option.get("fields", []):
        if field.get("category") != "environment":
            continue
        value = resolved_values.get(field.get("key"))
        if value not in (None, ""):
            environment[str(field.get("name"))] = str(value)


async def _discover_and_complete(
    dependencies: McpInstallationDependencies,
    *,
    agent_id: int,
    recommendation_id: str,
    option_id: str,
    stable_key: str,
    source: str,
    name: str,
    mcp_id: int,
    authorization_token: Optional[str],
    custom_headers: Dict[str, str],
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    record = dependencies.get_mcp_record(
        mcp_id=int(mcp_id),
        tenant_id=tenant_id,
    )
    if not record:
        raise Nl2AgentOperationError(
            "Installed MCP record could not be resolved."
        )
    resolved_mcp_id = int(record["mcp_id"])
    try:
        discovered = await dependencies.discover_tools(
            mcp_server_name=name,
            remote_mcp_server=record.get("mcp_server"),
            tenant_id=tenant_id,
            authorization_token=authorization_token,
            custom_headers=custom_headers or None,
        )
        tools = dependencies.upsert_discovered_tools(
            tenant_id,
            user_id,
            discovered,
        )
    except Exception as exc:
        dependencies.update_mcp_workflow(
            tenant_id,
            agent_id,
            recommendation_id,
            option_id=option_id,
            status="failed",
            installation_key=stable_key,
            mcp_id=resolved_mcp_id,
            error="MCP tool discovery failed. Retry to resume discovery.",
        )
        raise Nl2AgentExternalServiceError(
            "MCP tool discovery failed. Retry installation."
        ) from exc

    dependencies.update_mcp_workflow(
        tenant_id,
        agent_id,
        recommendation_id,
        option_id=option_id,
        status="connected",
        installation_key=stable_key,
        mcp_id=resolved_mcp_id,
        discovered_tool_ids=[int(tool["tool_id"]) for tool in tools],
        bound_tool_ids=[],
        error=None,
    )
    return {
        "agent_id": agent_id,
        "mcp_id": resolved_mcp_id,
        "status": "connected",
        "tools": [
            {
                "tool_id": tool["tool_id"],
                "name": tool["name"],
                "description": tool.get("description"),
            }
            for tool in tools
        ],
    }


@dataclass(frozen=True)
class McpBindingDependencies:
    """Persistence operations required to resolve MCP tool binding."""

    get_owned_draft: Callable[..., Dict[str, Any]]
    get_mcp_record: Callable[..., Dict[str, Any] | None]
    query_tools_by_ids: Callable[..., List[Dict[str, Any]]]
    bind_tool: Callable[..., Any]
    delete_tool_instances: Callable[..., Any]
    get_db_session: Callable[..., Any]
    reserve_binding: Callable[..., Dict[str, Any]]
    complete_binding: Callable[..., Dict[str, Any]]
    release_binding: Callable[..., Dict[str, Any]]


async def bind_mcp_tools(
    dependencies: McpBindingDependencies,
    *,
    agent_id: int,
    mcp_id: int,
    tool_ids: List[int],
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Bind user-selected tools belonging to an installed MCP."""
    dependencies.get_owned_draft(agent_id, tenant_id)
    if not tool_ids:
        raise Nl2AgentValidationError(
            "Select at least one discovered MCP tool to bind."
        )
    record = dependencies.get_mcp_record(mcp_id=mcp_id, tenant_id=tenant_id)
    if not record:
        raise AgentRunException("Installed MCP not found.")
    rows = dependencies.query_tools_by_ids(tool_ids, tenant_id) if tool_ids else []
    valid = {
        int(row["tool_id"]): row
        for row in rows
        if row.get("author") == tenant_id
        and row.get("source") == "mcp"
        and row.get("usage") == record.get("mcp_name")
    }
    if set(map(int, tool_ids)) != set(valid):
        raise Nl2AgentValidationError(
            "One or more tools do not belong to the selected MCP."
        )
    operation_id = "bind:" + hashlib.sha256(
        json.dumps(sorted(valid)).encode("utf-8")
    ).hexdigest()
    workflow = dependencies.reserve_binding(
        tenant_id,
        agent_id,
        mcp_id,
        operation_id,
        sorted(valid),
    )
    recommendation_id = str(workflow["recommendation_id"])
    try:
        with dependencies.get_db_session() as db_session:
            for tool_id in valid:
                dependencies.bind_tool(
                    ToolInstanceInfoRequest(
                        tool_id=tool_id,
                        agent_id=agent_id,
                        params={},
                        enabled=True,
                        version_no=0,
                    ),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    version_no=0,
                    db_session=db_session,
                )
    except Exception as exc:
        try:
            dependencies.release_binding(
                tenant_id,
                agent_id,
                recommendation_id,
                operation_id,
            )
        except Exception:
            logger.exception("Failed to release MCP tool binding reservation")
        raise Nl2AgentOperationError("Failed to bind MCP tools.") from exc
    try:
        dependencies.complete_binding(
            tenant_id,
            agent_id,
            recommendation_id,
            operation_id,
            "tools_bound",
        )
    except Exception as exc:
        logger.exception("MCP tools were committed but workflow completion failed")
        raise Nl2AgentOperationError(
            "MCP tools were saved, but workflow state could not be reconciled. Retry binding."
        ) from exc
    return {
        "agent_id": agent_id,
        "mcp_id": mcp_id,
        "bound_tool_ids": sorted(valid),
    }


async def skip_mcp_tool_binding(
    dependencies: McpBindingDependencies,
    *,
    agent_id: int,
    mcp_id: int,
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Resolve an installed MCP without binding discovered tools."""
    dependencies.get_owned_draft(agent_id, tenant_id)
    if not dependencies.get_mcp_record(mcp_id=mcp_id, tenant_id=tenant_id):
        raise AgentRunException("Installed MCP not found.")
    operation_id = "skip:" + hashlib.sha256(str(mcp_id).encode("utf-8")).hexdigest()
    workflow = dependencies.reserve_binding(
        tenant_id,
        agent_id,
        mcp_id,
        operation_id,
        [],
    )
    recommendation_id = str(workflow["recommendation_id"])
    try:
        with dependencies.get_db_session() as db_session:
            dependencies.delete_tool_instances(
                agent_id=agent_id,
                tool_ids=workflow.get("discovered_tool_ids", []),
                tenant_id=tenant_id,
                user_id=user_id,
                version_no=0,
                db_session=db_session,
            )
    except Exception as exc:
        try:
            dependencies.release_binding(
                tenant_id,
                agent_id,
                recommendation_id,
                operation_id,
            )
        except Exception:
            logger.exception("Failed to release MCP binding skip reservation")
        raise Nl2AgentOperationError(
            "Failed to skip MCP tool binding."
        ) from exc
    try:
        dependencies.complete_binding(
            tenant_id,
            agent_id,
            recommendation_id,
            operation_id,
            "binding_skipped",
        )
    except Exception as exc:
        logger.exception("MCP skip committed but workflow completion failed")
        raise Nl2AgentOperationError(
            "MCP tools were removed, but workflow state could not be reconciled. Retry skip."
        ) from exc
    return {
        "agent_id": agent_id,
        "mcp_id": mcp_id,
        "status": "binding_skipped",
    }
