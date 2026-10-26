# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import inspect
import json
from typing import Any, Dict, List, Optional

from contracts.constants.environment import AIDP_API_KEY, AIDP_SERVER_URL, AIDP_TENANT_ID
from contracts.tool import ToolInfo, ToolSourceEnum
from contracts.constants.constants import TOOL_PARAM_CONSTRAINT_KEYS
from management.db.mcp.remote import get_mcp_records_by_tenant
from management.db.tool.repository import query_tool_instances_by_id, query_tools_by_ids
from fastmcp.client.transports import SSETransport, StreamableHttpTransport
from infrastructure.http.client import create_httpx_client
from management.services.mcp.addressing import get_tenant_local_mcp_server
from management.services.tool.catalog import get_local_tools_classes
from management.services.tool.common import (
    _ALWAYS_HIDDEN_KNOWLEDGE_TOOLS,
    logger,
)
from management.services.tool.langchain import discover_langchain_modules
from pydantic_core import PydanticUndefined


def _get_user_selectability(
    tool_name: str,
    default: bool,
) -> bool:
    """Keep managed knowledge tools hidden from manual selection."""
    if tool_name in _ALWAYS_HIDDEN_KNOWLEDGE_TOOLS:
        return False
    return default


def _parse_kds_list(value: Any) -> list[str]:
    """Normalize legacy JSON strings and list values into ordered string IDs."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _is_aidp_search_tool(tool_id: int, tool_name: Any = None) -> bool:
    if isinstance(tool_name, str):
        return tool_name == "aidp_search"
    tools = query_tools_by_ids([tool_id])
    return bool(tools and tools[0].get("name") == "aidp_search")


def _resolve_aidp_snapshot(user_id: str, tenant_id: str):
    from ext_components.aidp.services.aidp_access_service import (
        resolve_current_aidp_access,
    )

    return resolve_current_aidp_access(
        server_url=AIDP_SERVER_URL,
        api_key=AIDP_API_KEY,
        user_id=user_id,
        tenant_id=tenant_id,
        aidp_tenant_id=AIDP_TENANT_ID,
    )


def _create_mcp_transport(
    url: str,
    authorization_token: Optional[str] = None,
    custom_headers: Optional[Dict[str, Any]] = None,
):
    """
    Create appropriate MCP transport based on URL ending.

    Args:
        url: MCP server URL
        authorization_token: Optional authorization token
        custom_headers: Optional custom HTTP headers

    Returns:
        Transport instance (SSETransport or StreamableHttpTransport)
    """
    url_stripped = url.strip()
    headers = {}
    if authorization_token:
        headers["Authorization"] = authorization_token
    if custom_headers:
        headers.update(custom_headers)

    if url_stripped.endswith("/sse"):
        return SSETransport(
            url=url_stripped, headers=headers, httpx_client_factory=create_httpx_client
        )
    elif url_stripped.endswith("/mcp"):
        return StreamableHttpTransport(
            url=url_stripped, headers=headers, httpx_client_factory=create_httpx_client
        )
    else:
        # Default to StreamableHttpTransport for unrecognized formats
        return StreamableHttpTransport(
            url=url_stripped, headers=headers, httpx_client_factory=create_httpx_client
        )


def python_type_to_json_schema(annotation: Any) -> str:
    """
    Convert Python type annotations to JSON Schema types

    Args:
        annotation: Python type annotation

    Returns:
        Corresponding JSON Schema type string
    """
    # Handle case with no type annotation
    if annotation == inspect.Parameter.empty:
        return "string"

    # Get type name
    type_name = getattr(annotation, "__name__", str(annotation))

    # Type mapping dictionary
    type_mapping = {
        "str": "string",
        "int": "integer",
        "float": "float",
        "bool": "boolean",
        "list": "array",
        "List": "array",
        "tuple": "array",
        "Tuple": "array",
        "dict": "object",
        "Dict": "object",
        "Any": "any",
    }

    # Return mapped type, or original type name if no mapping exists
    return type_mapping.get(type_name, type_name)


def _extract_field_constraints(field_info: Any) -> Dict[str, Any]:
    """Extract Pydantic ``Field`` validation constraints (ge, le, gt, lt, ...).

    In Pydantic v2, constraints declared via ``Field(ge=..., le=...)`` are stored
    in ``FieldInfo.metadata`` as ``annotated_types`` instances (e.g. ``Ge``, ``Le``,
    ``Interval``, ``MinLen``). This helper reads the relevant attributes so the
    constraints can be persisted to the DB ``params`` column.

    Args:
        field_info: Pydantic FieldInfo to extract constraints from
    """
    constraints: Dict[str, Any] = {}
    for item in getattr(field_info, "metadata", None) or []:
        for attr in TOOL_PARAM_CONSTRAINT_KEYS:
            value = getattr(item, attr, None)
            if value is not None:
                constraints[attr] = value
    return constraints


def get_local_tools() -> List[ToolInfo]:
    """
    Get metadata for all locally available tools

    Returns:
        List of ToolInfo objects for local tools
    """
    tools_info = []
    tools_classes = get_local_tools_classes()
    for tool_class in tools_classes:
        # Get class-level init_param_descriptions for fallback
        init_param_descriptions = getattr(tool_class, "init_param_descriptions", {})

        init_params_list = []
        sig = inspect.signature(tool_class.__init__)
        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue

            # Check if parameter has a default value and if it should be excluded
            if param.default != inspect.Parameter.empty:
                if hasattr(param.default, "exclude") and param.default.exclude:
                    continue

            # Check if default is a Pydantic FieldInfo (has .default attribute)
            is_pydantic_field = hasattr(param.default, "default")

            # Get description in both languages
            param_description = param.default.description if is_pydantic_field else ""

            # First try to get from param.default.description_zh (FieldInfo)
            # Note: Pydantic Field doesn't have description_zh attribute, so use getattr with default
            param_description_zh = (
                getattr(param.default, "description_zh", None)
                if is_pydantic_field
                else None
            )

            # Fallback to init_param_descriptions if not found
            if param_description_zh is None and param_name in init_param_descriptions:
                param_description_zh = init_param_descriptions[param_name].get(
                    "description_zh"
                )

            param_info = {
                "type": python_type_to_json_schema(param.annotation),
                "name": param_name,
                "description": param_description,
                "description_zh": param_description_zh,
            }

            # Handle both Pydantic FieldInfo and simple defaults
            if is_pydantic_field:
                if param.default.default is PydanticUndefined:
                    param_info["optional"] = False
                else:
                    param_info["default"] = param.default.default
                    param_info["optional"] = True

                # Persist Pydantic Field validation constraints (ge, le, gt, lt, ...)
                # so they are stored in the DB params column on scan/refresh and first init.
                constraints = _extract_field_constraints(param.default)
                if constraints:
                    param_info["constraints"] = constraints
            else:
                # Simple default value (not a FieldInfo)
                if param.default == inspect.Parameter.empty:
                    param_info["optional"] = False
                else:
                    param_info["default"] = param.default
                    param_info["optional"] = True

            init_params_list.append(param_info)

        # Get tool fixed attributes with bilingual support
        tool_description_zh = getattr(tool_class, "description_zh", None)
        tool_inputs = getattr(tool_class, "inputs", {})

        # Process inputs to add bilingual descriptions
        processed_inputs = {}
        if isinstance(tool_inputs, dict):
            for key, value in tool_inputs.items():
                if isinstance(value, dict):
                    processed_inputs[key] = {
                        **value,
                        "description_zh": value.get("description_zh"),
                    }
                else:
                    processed_inputs[key] = value

        tool_info = ToolInfo(
            name=getattr(tool_class, "name"),
            description=getattr(tool_class, "description"),
            description_zh=tool_description_zh,
            params=init_params_list,
            source=ToolSourceEnum.LOCAL.value,
            inputs=json.dumps(processed_inputs, ensure_ascii=False),
            output_type=getattr(tool_class, "output_type"),
            category=getattr(tool_class, "category"),
            labels=getattr(tool_class, "labels", None),
            is_user_selectable=_get_user_selectability(
                getattr(tool_class, "name"),
                getattr(tool_class, "is_user_selectable", True),
            ),
            class_name=tool_class.__name__,
            usage=None,
            origin_name=getattr(tool_class, "name"),
        )
        tools_info.append(tool_info)
    return tools_info


def _build_tool_info_from_langchain(obj) -> ToolInfo:
    """Convert a LangChain Tool object into our internal ToolInfo model."""

    # Try to infer parameter schema from the underlying callable signature if
    # available.  LangChain tools usually expose a `.func` attribute pointing
    # to the original python function.  If not present, we fallback to the
    # tool instance itself (implements __call__).
    target_callable = getattr(obj, "func", obj)

    inputs = getattr(obj, "args", {})

    if inputs:
        for key, value in inputs.items():
            if "description" not in value:
                value["description"] = "see the description"

    # Attempt to infer output type from return annotation
    try:
        return_schema = inspect.signature(target_callable).return_annotation
        output_type = python_type_to_json_schema(return_schema)
    except (TypeError, ValueError):
        output_type = "string"
    tool_name = getattr(obj, "name", target_callable.__name__)
    tool_info = ToolInfo(
        name=tool_name,
        description=getattr(obj, "description", ""),
        params=[],
        source=ToolSourceEnum.LANGCHAIN.value,
        inputs=json.dumps(inputs, ensure_ascii=False),
        output_type=output_type,
        class_name=tool_name,
        usage=None,
        origin_name=tool_name,
        category=None,
        labels=None,
        is_user_selectable=True,
    )
    return tool_info


def get_langchain_tools() -> List[ToolInfo]:
    """Discover LangChain tools in the specified directory.

    We dynamically import every `*.py` file and extract objects that look like
    LangChain tools (based on presence of `name` & `description`).  Any valid
    tool is converted to ToolInfo with source = "langchain".
    """
    tools_info: List[ToolInfo] = []
    # Discover all objects that look like LangChain tools
    discovered_tools = discover_langchain_modules()

    # Process discovered tools
    for obj, filename in discovered_tools:
        try:
            tool_info = _build_tool_info_from_langchain(obj)
            tools_info.append(tool_info)
        except Exception as e:
            logger.warning(f"Error processing LangChain tool in {filename}: {e}")

    return tools_info


async def get_all_mcp_tools(tenant_id: str) -> List[ToolInfo]:
    """
    Get metadata for all tools available from the MCP service

    Returns:
        List of ToolInfo objects for MCP tools, or empty list if connection fails
    """
    mcp_info = get_mcp_records_by_tenant(tenant_id=tenant_id)
    tools_info = []
    for record in mcp_info:
        # Only scan MCP services that are explicitly enabled and currently healthy.
        if bool(record.get("enabled")) and bool(record.get("status")):
            try:
                tools_info.extend(
                    await get_tool_from_remote_mcp_server(
                        mcp_server_name=record["mcp_name"],
                        remote_mcp_server=record["mcp_server"],
                        tenant_id=tenant_id,
                        authorization_token=record.get("authorization_token"),
                        custom_headers=record.get("custom_headers"),
                    )
                )
            except Exception as e:
                logger.error(f"mcp connection error: {str(e)}")

    default_mcp_url = get_tenant_local_mcp_server(tenant_id)
    tools_info.extend(
        await get_tool_from_remote_mcp_server(
            mcp_server_name="outer-apis",
            remote_mcp_server=default_mcp_url,
            tenant_id=tenant_id,
        )
    )
    return tools_info


def search_tool_info_impl(
    agent_id: int,
    tool_id: int,
    tenant_id: str,
    user_id: Optional[str] = None,
):
    """
    Search for tool configuration information by agent ID and tool ID

    Args:
        agent_id: Agent ID
        tool_id: Tool ID
        tenant_id: Tenant ID

    Returns:
        Dictionary containing tool parameters and enabled status

    Raises:
        ValueError: If database query fails
    """
    tool_instance = query_tool_instances_by_id(agent_id, tool_id, tenant_id)

    if tool_instance:
        params = dict(tool_instance["params"] or {})
        if user_id and _is_aidp_search_tool(tool_id):
            snapshot = _resolve_aidp_snapshot(user_id, tenant_id)
            existing_ids = _parse_kds_list(params.get("kds_list"))
            params["kds_list"] = [
                kds_id
                for kds_id in existing_ids
                if kds_id in snapshot.accessible_id_set
            ]
        return {"params": params, "enabled": tool_instance["enabled"]}
    else:
        return {"params": None, "enabled": False}


import asyncio
from contextlib import AsyncExitStack
from typing import Any, Dict, Optional

import jsonref
from contracts.constants.environment import MCP_REQUEST_TIMEOUT_SECONDS, RUNTIME_MCP_TOOL_TIMEOUT_SECONDS, TOKEN
from contracts.errors.exceptions import MCPConnectionError
from contracts.tool import ToolInfo, ToolSourceEnum
from management.db.mcp.remote import get_mcp_authorization_token_by_name_and_url, get_mcp_custom_headers_by_name_and_url
from fastmcp import Client
from management.services.tool.common import logger
from mcpadapt.smolagents_adapter import _sanitize_function_name


async def get_tool_from_remote_mcp_server(
    mcp_server_name: str,
    remote_mcp_server: str,
    tenant_id: Optional[str] = None,
    authorization_token: Optional[str] = None,
    custom_headers: Optional[Dict[str, Any]] = None,
):
    """
    Get the tool information from the remote MCP server, avoid blocking the event loop

    Args:
        mcp_server_name: Name of the MCP server
        remote_mcp_server: URL of the MCP server
        tenant_id: Optional tenant ID for database lookup of authorization_token
        authorization_token: Optional authorization token for authentication (if not provided and tenant_id is given, will be fetched from database)
        custom_headers: Optional custom HTTP headers
    """
    # Get authorization token from database if not provided
    if authorization_token is None and tenant_id:
        authorization_token = get_mcp_authorization_token_by_name_and_url(
            mcp_name=mcp_server_name, mcp_server=remote_mcp_server, tenant_id=tenant_id
        )

    # Get custom headers from database if not provided
    if custom_headers is None and tenant_id:
        custom_headers = get_mcp_custom_headers_by_name_and_url(
            mcp_name=mcp_server_name, mcp_server=remote_mcp_server, tenant_id=tenant_id
        )
    if tenant_id and "/mcp/" in remote_mcp_server:
        custom_headers = {
            **(custom_headers or {}),
            "X-Tenant-ID": str(tenant_id),
            "X-Nexent-Internal-Token": TOKEN,
        }

    tools_info = []

    try:
        transport = _create_mcp_transport(
            remote_mcp_server, authorization_token, custom_headers
        )
        client = Client(transport=transport, timeout=RUNTIME_MCP_TOOL_TIMEOUT_SECONDS)
        async with AsyncExitStack() as stack:
            await asyncio.wait_for(
                stack.enter_async_context(client),
                timeout=MCP_REQUEST_TIMEOUT_SECONDS,
            )
            # List available operations
            tools = await client.list_tools()

            for tool in tools:
                if (
                    isinstance(tool.meta, dict)
                    and tool.meta.get("nexent_internal") is True
                ):
                    continue

                input_schema = {
                    k: v
                    for k, v in jsonref.replace_refs(tool.inputSchema).items()
                    if k != "$defs"
                }
                # make sure mandatory `description` and `type` is provided for each argument:
                for k, v in input_schema["properties"].items():
                    if "description" not in v:
                        input_schema["properties"][k]["description"] = (
                            "see tool description"
                        )
                    if "type" not in v:
                        input_schema["properties"][k]["type"] = "string"

                sanitized_tool_name = _sanitize_function_name(tool.name)
                tool_description = tool.description or ""
                tool_info = ToolInfo(
                    name=sanitized_tool_name,
                    description=tool_description,
                    params=[],
                    source=ToolSourceEnum.MCP.value,
                    inputs=str(input_schema["properties"]),
                    # MCP results may contain text, structured data, images, audio, or files.
                    # "object" matches the runtime adapter and avoids advertising every result as text.
                    output_type="object",
                    class_name=sanitized_tool_name,
                    usage=mcp_server_name,
                    origin_name=tool.name,
                    category=None,
                    is_user_selectable=True,
                )
                tools_info.append(tool_info)
            return tools_info
    except BaseException as e:
        logger.error(
            f"failed to get tool from remote MCP server, detail: {e}", exc_info=True
        )
        # Convert all failures (including SystemExit) to domain error to avoid process exit
        raise MCPConnectionError(
            f"failed to get tool from remote MCP server, detail: {e}"
        )
