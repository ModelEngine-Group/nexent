import importlib
import inspect
import json
import logging
from typing import Any, List
from urllib.parse import urljoin

from pydantic_core import PydanticUndefined
from fastmcp import Client
import jsonref

from database.agent_db import (
    query_tool_instances_by_id,
    create_or_update_tool_by_tool_info,
    update_tool_table_from_scan_tool_list
)
from consts.model import ToolInstanceInfoRequest, ToolInfo, ToolSourceEnum
from database.remote_mcp_db import get_mcp_records_by_tenant
from utils.auth_utils import get_current_user_id
from fastapi import Header

from utils.config_utils import config_manager

logger = logging.getLogger("tool_configuration_service")

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
        "Any": "any"
    }

    # Return mapped type, or original type name if no mapping exists
    return type_mapping.get(type_name, type_name)

def get_local_tools() -> List[ToolInfo]:
    """
    Get metadata for all locally available tools

    Returns:
        List of ToolInfo objects for local tools
    """
    tools_info = []
    tools_classes = get_local_tools_classes()
    for tool_class in tools_classes:
        init_params_list = []
        sig = inspect.signature(tool_class.__init__)
        for param_name, param in sig.parameters.items():
            if param_name == "self" or param.default.exclude:
                continue

            param_info = {
                "type": python_type_to_json_schema(param.annotation),
                "name": param_name,
                "description": param.default.description
            }
            if param.default.default is PydanticUndefined:
                param_info["optional"] = False
            else:
                param_info["default"] = param.default.default
                param_info["optional"] = True

            init_params_list.append(param_info)

        # get tool fixed attributes
        tool_info = ToolInfo(
            name=getattr(tool_class, 'name'),
            description=getattr(tool_class, 'description'),
            params=init_params_list,
            source=ToolSourceEnum.LOCAL.value,
            inputs=json.dumps(getattr(tool_class, 'inputs'), ensure_ascii=False),
            output_type=getattr(tool_class, 'output_type'),
            class_name=tool_class.__name__,
            usage=None
        )
        tools_info.append(tool_info)
    return tools_info

def get_local_tools_classes() -> List[type]:
    """
    Get all tool classes from the nexent.core.tools package

    Returns:
        List of tool class objects
    """
    tools_package = importlib.import_module('nexent.core.tools')
    tools_classes = []
    for name in dir(tools_package):
        obj = getattr(tools_package, name)
        if inspect.isclass(obj):
            tools_classes.append(obj)
    return tools_classes

async def get_all_mcp_tools(tenant_id: str) -> List[ToolInfo]:
    """
    Get metadata for all tools available from the MCP service

    Returns:
        List of ToolInfo objects for MCP tools, or empty list if connection fails
    """
    mcp_info = get_mcp_records_by_tenant(tenant_id=tenant_id)
    tools_info = []
    for record in mcp_info:
        # only update connected server
        if record["status"]:
            try:
                tools_info.extend(await get_tool_from_remote_mcp_server(mcp_server_name=record["mcp_name"],
                                                                    remote_mcp_server=record["mcp_server"]))
            except Exception as e:
                logger.error(f"mcp connection error: {str(e)}")

    default_mcp_url = urljoin(config_manager.get_config("NEXENT_MCP_SERVER"), "sse")
    tools_info.extend(await get_tool_from_remote_mcp_server(mcp_server_name="nexent",
                                                            remote_mcp_server=default_mcp_url))
    return tools_info

def search_tool_info_impl(agent_id: int, tool_id: int, authorization: str = Header(None)):
    """
    Search for tool configuration information by agent ID and tool ID

    Args:
        agent_id: Agent ID
        tool_id: Tool ID
        authorization:

    Returns:
        Dictionary containing tool parameters and enabled status

    Raises:
        ValueError: If database query fails
    """
    _, tenant_id = get_current_user_id(authorization)
    try:
        # now only admin can modify the tool, user_id is not used
        tool_instance = query_tool_instances_by_id(agent_id, tool_id, tenant_id, user_id=None)
    except Exception as e:
        logger.error(f"search_tool_info_impl error in query_tool_instances_by_id, detail: {e}")
        raise ValueError(f"search_tool_info_impl error in query_tool_instances_by_id, detail: {e}")

    if tool_instance:
        return {
            "params": tool_instance["params"],
            "enabled": tool_instance["enabled"]
        }
    else:
        return {
            "params": None,
            "enabled": False
        }


def update_tool_info_impl(request: ToolInstanceInfoRequest, authorization: str = Header(None)):
    """
    Update tool configuration information

    Args:
        request: ToolInstanceInfoRequest containing tool configuration data

    Returns:
        Dictionary containing the updated tool instance

    Raises:
        ValueError: If database update fails
    """
    user_id, tenant_id = get_current_user_id(authorization)
    try:
        tool_instance = create_or_update_tool_by_tool_info(request, tenant_id, user_id)
    except Exception as e:
        logger.error(f"update_tool_info_impl error in create_or_update_tool, detail: {e}")
        raise ValueError(f"update_tool_info_impl error in create_or_update_tool, detail: {e}")

    return {
        "tool_instance": tool_instance
    }


async def get_tool_from_remote_mcp_server(mcp_server_name: str, remote_mcp_server: str):
    """get the tool information from the remote MCP server, avoid blocking the event loop"""
    tools_info = []
    client = Client(remote_mcp_server, timeout=10)
    async with client:
        # List available operations
        tools = await client.list_tools()

        for tool in tools:
            input_schema = {
                k: v
                for k, v in jsonref.replace_refs(tool.inputSchema).items()
                if k != "$defs"
            }
            # make sure mandatory `description` and `type` is provided for each argument:
            for k, v in input_schema["properties"].items():
                if "description" not in v:
                    input_schema["properties"][k]["description"] = "see tool description"
                if "type" not in v:
                    input_schema["properties"][k]["type"] = "string"

            tool_info = ToolInfo(name=tool.name,
                                description=tool.description,
                                params=[],
                                source=ToolSourceEnum.MCP.value,
                                inputs=str(input_schema["properties"]),
                                output_type="string",
                                class_name=tool.name,
                                usage=mcp_server_name)
            tools_info.append(tool_info)
        return tools_info


async def update_tool_list(tenant_id: str, user_id: str):
    """
        Scan and gather all available tools from both local and MCP sources

        Args:
            tenant_id: Tenant ID for MCP tools (required for MCP tools)
            user_id: User ID for MCP tools (required for MCP tools)

        Returns:
            List of ToolInfo objects containing tool metadata
        """
    local_tools = get_local_tools()
    try:
        mcp_tools = await get_all_mcp_tools(tenant_id)
    except Exception as e:
        logger.error(f"failed to get all mcp tools, detail: {e}")
        raise Exception(f"failed to get all mcp tools, detail: {e}")

    try:
        update_tool_table_from_scan_tool_list(tenant_id=tenant_id,
                                              user_id=user_id,
                                              tool_list=local_tools+mcp_tools)
    except Exception as e:
        logger.error(f"failed to update tool list to PG, detail: {e}")
        raise Exception(f"failed to update tool list to PG, detail: {e}")
