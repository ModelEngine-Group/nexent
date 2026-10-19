# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import importlib
import inspect
import json
import logging
import time
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import jsonref
import requests
from consts.const import (
    AIDP_API_KEY,
    AIDP_SERVER_URL,
    AIDP_TENANT_ID,
    DATA_PROCESS_SERVICE,
    LOCAL_MCP_SERVER,
    MCP_MANAGEMENT_API,
    MCP_REQUEST_TIMEOUT_SECONDS,
    RUNTIME_MCP_TOOL_TIMEOUT_SECONDS,
    TOKEN,
)
from consts.error_message import ErrorMessage
from consts.exceptions import (
    AgentDraftEditError,
    MCPConnectionError,
    NotFoundException,
    ResourceBindingError,
    ToolExecutionException,
    ValidationError,
)
from consts.model import (
    ToolInfo,
    ToolInstanceInfoRequest,
    ToolSourceEnum,
    ToolValidateRequest,
)
from consts.tool_labels import SYSTEM_MANAGED_TOOL_NAMES
from consts.tool_param_constraints import (
    TOOL_PARAM_CONSTRAINT_KEYS,
    TOOL_PARAM_CONSTRAINT_RULES,
)
from database.client import minio_client
from database.knowledge_db import get_knowledge_name_map_by_index_names
from database.outer_api_tool_db import (
    delete_openapi_service as db_delete_openapi_service,
)
from database.outer_api_tool_db import (
    query_openapi_services_by_tenant,
    upsert_openapi_service,
)
from database.remote_mcp_db import (
    get_mcp_authorization_token_by_name_and_url,
    get_mcp_custom_headers_by_name_and_url,
    get_mcp_records_by_tenant,
    get_mcp_server_by_name_and_tenant,
)
from database.tool_db import (
    check_tool_list_initialized,
    create_or_update_tool_by_tool_info,
    query_all_tools,
    query_tool_instances_by_id,
    query_tools_by_ids,
    query_tools_by_labels,
    search_last_tool_instance_by_tool_id,
    update_tool_table_from_scan_tool_list,
)
from database.user_tenant_db import get_user_email_map
from fastmcp import Client
from fastmcp.client.transports import SSETransport, StreamableHttpTransport
from infrastructure.http.client import create_httpx_client
from management.services.agent.authorization import require_agent_draft_edit
from management.services.file.service import validate_urls_access
from management.services.knowledge_base.service import (
    get_embedding_model_by_index_name,
    get_vector_db_core,
)
from management.services.mcp.addressing import get_tenant_local_mcp_server
from management.services.model.adapter import get_llm_adapter, get_vlm_adapter
from management.services.model.resolver import get_rerank_model
from management.services.tool.catalog import (
    get_local_tools_classes,
    get_local_tools_description_zh,
)
from management.services.tool.common import (
    _ALWAYS_HIDDEN_KNOWLEDGE_TOOLS,
    TOOL_PARAM_CONSTRAINT_ERROR_MESSAGES,
    logger,
)
from management.services.tool.langchain import discover_langchain_modules
from mcpadapt.smolagents_adapter import _sanitize_function_name
from nexent.core.concurrency import run_blocking
from nexent.monitor import set_monitoring_context, set_monitoring_operation
from pydantic_core import PydanticUndefined


def _get_tool_record(tool_id: int) -> Optional[Dict[str, Any]]:
    """
    Resolve a tool's DB record so constraints can be read from its ``params`` column.

    Args:
        tool_id: Tool ID

    Returns:
        Tool info dict
    """
    try:
        tools = query_tools_by_ids([tool_id])
    except Exception:
        logger.warning(
            "Failed to load tool %s for constraint validation; skipping", tool_id
        )
        return None
    return tools[0] if tools else None


def _coerce_param_value(
    tool_name: str,
    param_name: str,
    value_type: str,
    raw_value: Any,
    constraint_key: str,
):
    """
    Coerce the initial value and validate its data type.

    When the constraint key contains "length", the string length is returned.
    Otherwise the value is converted to the type expected by the parameter.

    Args:
        tool_name: Tool name
        param_name: Parameter name
        value_type: Expected parameter type
        raw_value: Raw value to coerce
        constraint_key: Constraint key being validated

    Returns:
        The coerced value (string length, string, or numeric value)

    Raises:
        ValidationError: If the value cannot be coerced to the expected type
    """
    if "length" in constraint_key:
        return len(str(raw_value))
    elif value_type == "string":
        return str(raw_value)

    try:
        numeric_value = float(raw_value)
    except (TypeError, ValueError):
        raise ValidationError(
            TOOL_PARAM_CONSTRAINT_ERROR_MESSAGES["valid_type"].format(
                tool_name=tool_name, param_name=param_name, value_type=value_type
            )
        )
    if value_type == "integer" and not numeric_value.is_integer():
        raise ValidationError(
            TOOL_PARAM_CONSTRAINT_ERROR_MESSAGES["integer"].format(
                tool_name=tool_name, param_name=param_name
            )
        )
    return numeric_value


def _format_constraint_message(
    key: str, tool_name: str, param_name: str, value: Any
) -> str:
    """Format a tool parameter constraint message from its centralized template."""
    return TOOL_PARAM_CONSTRAINT_ERROR_MESSAGES[key].format(
        tool_name=tool_name, param_name=param_name, value=value
    )


def _apply_param_constraints(
    tool_name: str,
    param_name: str,
    value_type: str,
    raw_value: Any,
    constraints: Dict[str, Any],
):
    """
    Apply a parameter's DB-stored constraints to a single configured value.

    Args:
        tool_name: Tool name
        param_name: Parameter name
        value_type: Expected parameter type
        raw_value: Raw value to validate
        constraints: Constraint definitions to apply
    """
    if any(key in constraints for key in TOOL_PARAM_CONSTRAINT_KEYS):
        for key, check_fn in TOOL_PARAM_CONSTRAINT_RULES:
            if key not in constraints:
                continue
            value = _coerce_param_value(
                tool_name, param_name, value_type, raw_value, key
            )
            if check_fn(value, constraints[key]):
                raise ValidationError(
                    _format_constraint_message(
                        key, tool_name, param_name, constraints[key]
                    )
                )


def _validate_tool_param_ranges(tool_id: int, params: Dict[str, Any]):
    """
    Validate configured parameter values against constraints stored in the DB ``params`` column.

    Args:
        tool_id: Tool ID
        params: Configured parameter values
    """
    tool = _get_tool_record(tool_id)
    if not tool:
        return
    tool_name = tool.get("name") or ""
    for spec in tool.get("params") or []:
        param_name = spec.get("name")
        constraints = spec.get("constraints")
        if not param_name or not constraints:
            continue
        raw_value = params.get(param_name)
        # None means "not configured"; the DB layer drops it and the SDK falls back to its default.
        if raw_value is None:
            continue
        _apply_param_constraints(
            tool_name, param_name, spec.get("type") or "", raw_value, constraints
        )


def update_tool_info_impl(
    tool_info: ToolInstanceInfoRequest, tenant_id: str, user_id: str
):
    """
    Update tool configuration information

    Args:
        tool_info: ToolInstanceInfoRequest containing tool configuration data
        tenant_id: Tenant ID
        user_id: User ID

    Returns:
        Dictionary containing the updated tool instance

    Raises:
        ValueError: If database update fails
    """
    version_no = getattr(tool_info, "version_no", 0)
    if version_no != 0:
        raise AgentDraftEditError("agent_not_draft")
    require_agent_draft_edit(
        agent_id=tool_info.agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    tool = next(
        (
            item
            for item in query_all_tools(tenant_id)
            if item.get("tool_id") == tool_info.tool_id
        ),
        None,
    )
    if (
        tool is None
        or tool.get("is_available") is not True
        or tool.get("name") in SYSTEM_MANAGED_TOOL_NAMES
    ):
        raise ResourceBindingError("resource_not_visible")

    if _is_aidp_search_tool(tool_info.tool_id, tool.get("name")):
        existing = query_tool_instances_by_id(
            tool_info.agent_id,
            tool_info.tool_id,
            tenant_id,
            version_no,
        )
        existing_params = dict((existing or {}).get("params") or {})
        existing_ids = _parse_kds_list(existing_params.get("kds_list"))
        params = dict(tool_info.params or {})

        # A missing key means the caller did not edit the knowledge scope.
        if "kds_list" not in params:
            params["kds_list"] = existing_ids
        else:
            submitted_ids = _parse_kds_list(params.get("kds_list"))
            try:
                snapshot = _resolve_aidp_snapshot(user_id, tenant_id)
            except Exception as exc:
                new_ids = [
                    kds_id
                    for kds_id in submitted_ids
                    if kds_id not in set(existing_ids)
                ]
                if new_ids:
                    raise ValidationError(
                        "AIDP is unavailable; the knowledge base configuration was not changed"
                    ) from exc
                params["kds_list"] = existing_ids
            else:
                existing_set = set(existing_ids)
                invalid_ids = [
                    kds_id
                    for kds_id in submitted_ids
                    if kds_id not in snapshot.accessible_id_set
                    and kds_id not in existing_set
                ]
                if invalid_ids:
                    raise ValidationError(
                        "aidp_search kds_list contains a knowledge base the user cannot configure"
                    )
                hidden_existing = [
                    kds_id
                    for kds_id in existing_ids
                    if kds_id not in snapshot.accessible_id_set
                ]
                visible_submitted = [
                    kds_id
                    for kds_id in submitted_ids
                    if kds_id in snapshot.accessible_id_set
                ]
                params["kds_list"] = list(
                    dict.fromkeys(hidden_existing + visible_submitted)
                )
        tool_info.params = params

    _validate_tool_param_ranges(
        tool_info.tool_id,
        dict(getattr(tool_info, "params", None) or {}),
    )

    tool_instance = create_or_update_tool_by_tool_info(
        tool_info, tenant_id, user_id, version_no=version_no
    )
    return {"tool_instance": tool_instance}


async def init_tool_list_for_tenant(tenant_id: str, user_id: str):
    """
    Initialize tool list for a new tenant.
    This function scans and populates available tools from local, MCP, and LangChain sources.

    Args:
        tenant_id: Tenant ID for MCP tools (required for MCP tools)
        user_id: User ID for tracking who initiated the scan

    Returns:
        Dictionary containing initialization result with tool count
    """
    # Check if tools have already been initialized for this tenant
    if check_tool_list_initialized(tenant_id):
        logger.info(f"Tool list already initialized for tenant {tenant_id}, skipping")
        return {"status": "already_initialized", "message": "Tool list already exists"}

    logger.info(f"Initializing tool list for new tenant: {tenant_id}")
    await update_tool_list(tenant_id=tenant_id, user_id=user_id)
    return {"status": "success", "message": "Tool list initialized successfully"}


async def update_tool_list(tenant_id: str, user_id: str):
    """
    Scan and gather all available tools from local, MCP, and outer API sources.
    Also refreshes dynamic outer API tools in MCP server.

    Args:
        tenant_id: Tenant ID for MCP tools (required for MCP tools)
        user_id: User ID for MCP tools (required for MCP tools)

    Returns:
        List of ToolInfo objects containing tool metadata
    """
    local_tools = get_local_tools()
    langchain_tools = get_langchain_tools()

    _refresh_openapi_services_in_mcp(tenant_id)

    try:
        mcp_tools = await get_all_mcp_tools(tenant_id)
    except Exception as e:
        logger.error(f"failed to get all mcp tools, detail: {e}")
        # Don't block local/langchain tool update when MCP is unavailable.
        mcp_tools = []

    # Enabled MCP services are "intended to be available". Their tools keep their
    # previous availability even when this scan fails to reach them, so a transient
    # connection failure does not hide a healthy MCP's tools from the tool list.
    enabled_mcp_names = {
        str(record.get("mcp_name") or "")
        for record in get_mcp_records_by_tenant(tenant_id=tenant_id)
        if bool(record.get("enabled"))
    }
    # API-converted services are persisted separately from regular MCP records,
    # but their scanned tools use the shared ``outer-apis`` usage value. Keep
    # those tools available during a transient MCP scan failure as long as at
    # least one API service still exists for the tenant.
    try:
        if query_openapi_services_by_tenant(tenant_id):
            enabled_mcp_names.add("outer-apis")
    except Exception as exc:
        logger.warning(
            "Failed to check API-converted services for tenant %s: %s", tenant_id, exc
        )

    update_tool_table_from_scan_tool_list(
        tenant_id=tenant_id,
        user_id=user_id,
        tool_list=local_tools + mcp_tools + langchain_tools,
        enabled_mcp_names=enabled_mcp_names,
    )


async def list_all_tools(tenant_id: str, labels: Optional[List[str]] = None):
    """
    List all tools for a given tenant, optionally filtered by labels (OR match).

    Args:
        tenant_id: Tenant ID
        labels: Optional labels to filter tools by (OR match)
    """
    if labels:
        tools_info = query_tools_by_labels(tenant_id, labels)
    else:
        tools_info = query_all_tools(tenant_id)

    updated_by_email_map = get_user_email_map(
        [tool.get("updated_by", "") for tool in tools_info]
    )

    # Get description_zh from SDK for local tools (not persisted to DB)
    local_tool_descriptions = get_local_tools_description_zh()

    # only return the fields needed
    formatted_tools = []
    for tool in tools_info:
        tool_name = tool.get("name")

        if tool_name in SYSTEM_MANAGED_TOOL_NAMES:
            continue

        # Always use SDK inputs for local tools to stay in sync with current tool code
        is_local = tool.get("source") == "local"
        sdk_info = local_tool_descriptions.get(tool_name) if is_local else None

        if is_local and sdk_info:
            description_zh = sdk_info.get("description_zh")

            # Merge params description_zh from SDK (independent of tool-level description_zh)
            params = tool.get("params", [])
            if params:
                for param in params:
                    if not param.get("description_zh"):
                        for sdk_param in sdk_info.get("params", []):
                            if sdk_param.get("name") == param.get("name"):
                                param["description_zh"] = sdk_param.get(
                                    "description_zh"
                                )
                                break

            # Merge SDK inputs: use DB as base, merge description_zh for existing keys,
            # add new keys from SDK. This ensures new inputs like kds_list appear even
            # if the DB record was created before the field was added to the SDK.
            inputs_str = tool.get("inputs", "{}")
            try:
                inputs = (
                    json.loads(inputs_str)
                    if isinstance(inputs_str, str)
                    else (inputs_str or {})
                )
                sdk_inputs = sdk_info.get("inputs", {})

                if isinstance(inputs, dict):
                    for key, value in inputs.items():
                        if isinstance(value, dict) and key in sdk_inputs:
                            sdk_desc_zh = sdk_inputs[key].get("description_zh")
                            if sdk_desc_zh:
                                value["description_zh"] = sdk_desc_zh

                    for key, sdk_value in sdk_inputs.items():
                        if key not in inputs:
                            inputs[key] = sdk_value

                    inputs_str = json.dumps(inputs, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                pass
        else:
            description_zh = tool.get("description_zh")
            inputs_str = tool.get("inputs", "{}")

        formatted_tool = {
            "tool_id": tool.get("tool_id"),
            "name": tool_name,
            "origin_name": tool.get("origin_name"),
            "description": tool.get("description"),
            "description_zh": description_zh,
            "source": tool.get("source"),
            "is_available": tool.get("is_available"),
            "create_time": tool.get("create_time"),
            "usage": tool.get("usage"),
            "params": tool.get("params", []),
            "inputs": inputs_str,
            "category": tool.get("category"),
            "labels": tool.get("labels", []),
            "is_user_selectable": _get_user_selectability(
                tool_name,
                tool.get("is_user_selectable", True),
            ),
            "updated_by": tool.get("updated_by", ""),
            "updated_by_name": updated_by_email_map.get(tool.get("updated_by"), ""),
        }
        formatted_tools.append(formatted_tool)
    from management.services.permission.identity.display import enrich_cas_usernames

    return enrich_cas_usernames(
        formatted_tools, {"updated_by_cas_username": "updated_by"}
    )


def load_last_tool_config_impl(tool_id: int, tenant_id: str, user_id: str):
    """
    Load the last tool configuration for a given tool ID
    """
    tool_instance = search_last_tool_instance_by_tool_id(tool_id, tenant_id, user_id)
    if tool_instance is None:
        raise ValueError(f"Tool configuration not found for tool ID: {tool_id}")
    return tool_instance.get("params", {})


from management.services.mcp.openapi import (
    _refresh_openapi_services_in_mcp,
    delete_openapi_service,
    import_openapi_service,
    list_openapi_services,
)
from management.services.tool.discovery import (
    _build_tool_info_from_langchain,
    _create_mcp_transport,
    _extract_field_constraints,
    _get_user_selectability,
    _is_aidp_search_tool,
    _parse_kds_list,
    _resolve_aidp_snapshot,
    get_all_mcp_tools,
    get_langchain_tools,
    get_local_tools,
    get_tool_from_remote_mcp_server,
    python_type_to_json_schema,
    search_tool_info_impl,
)
from management.services.tool.validation import (
    _call_mcp_tool,
    _get_tool_class_by_name,
    _validate_langchain_tool,
    _validate_local_tool,
    _validate_mcp_tool_nexent,
    _validate_mcp_tool_remote,
    validate_tool_impl,
)
