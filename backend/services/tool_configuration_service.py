import asyncio
import importlib
import inspect
import json
import logging
from typing import Any, List
from urllib.parse import urljoin

from fastapi import Header

from pydantic_core import PydanticUndefined
from smolagents import ToolCollection

from database.agent_db import (
    query_tool_instances_by_id,
    create_or_update_tool_by_tool_info,
    update_tool_table_from_scan_tool_list
)
from consts.model import ToolInstanceInfoRequest, ToolInfo, ToolSourceEnum
from services.tenant_config_service import get_remote_mcp_server_list
from utils.auth_utils import get_current_user_id
from fastapi import Header

from utils.config_utils import config_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tool config")

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
            class_name=tool_class.__name__
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

async def get_all_mcp_tools(tenant_id: str, user_id: str) -> List[ToolInfo]:
    """
    Get metadata for all tools available from the MCP service

    Returns:
        List of ToolInfo objects for MCP tools, or empty list if connection fails
    """
    remote_mcp_server_info = await get_remote_mcp_server_list(tenant_id, user_id)


    mcp_server_name_list = [item["remote_mcp_server_name"] for item in remote_mcp_server_info]
    tools_info = await scan_all_mcp_tools(mcp_server_list=mcp_server_name_list)
    return tools_info



def search_tool_info_impl(agent_id: int, tool_id: int, authorization: str = Header(None)):
    """
    Search for tool configuration information by agent ID and tool ID
    
    Args:
        agent_id: Agent ID
        tool_id: Tool ID
        
    Returns:
        Dictionary containing tool parameters and enabled status
        
    Raises:
        ValueError: If database query fails
    """
    user_id, tenant_id = get_current_user_id(authorization)
    try:
        tool_instance = query_tool_instances_by_id(agent_id, tool_id, tenant_id, user_id)
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
    """异步获取远程MCP服务器的工具信息，避免阻塞事件循环"""
    def _get_tools_from_mcp_sync(mcp_url):
        """同步获取MCP工具的辅助函数，在线程池中执行"""
        try:
            tools_info = []
            with ToolCollection.from_mcp({"url": mcp_url}) as tool_collection:
                # iterate all MCP tools
                for tool_class in tool_collection.tools:
                    tool_info = ToolInfo(
                        name=f"remote_{mcp_server_name}_{getattr(tool_class, 'name')}",
                        description=getattr(tool_class, 'description'),
                        params=[],
                        source=ToolSourceEnum.MCP.value,
                        inputs=str(getattr(tool_class, 'inputs')),
                        output_type=getattr(tool_class, 'output_type'),
                        class_name=f"remote_{mcp_server_name}_{getattr(tool_class, 'name')}"
                    )

                    tools_info.append(tool_info)
            return tools_info
        except Exception as e:
            logger.error(f"mcp connection error: {str(e)}")
            return []

    loop = asyncio.get_event_loop()
    tools_list = await loop.run_in_executor(None, _get_tools_from_mcp_sync, remote_mcp_server)
    return tools_list


async def scan_all_mcp_tools(mcp_server_list: List[str]):
    """异步获取远程MCP服务器的工具信息，避免阻塞事件循环"""
    def _get_tools_from_nexent_mcp_sync(server_name_list: List[str]):
        """同步获取MCP工具的辅助函数，在线程池中执行"""
        try:
            tools_info = []
            mcp_url = urljoin(config_manager.get_config("NEXENT_MCP_SERVER"), "sse")
            with ToolCollection.from_mcp({"url": mcp_url}) as tool_collection:
                # iterate all MCP tools
                for tool_class in tool_collection.tools:
                    try:
                        tool_name_split = getattr(tool_class, 'name').split('_')
                        if tool_name_split[0]=='remote' and tool_name_split[1] not in server_name_list:
                            continue
                    except Exception as e:
                        logging.info(f"split tool name {getattr(tool_class, 'name')} error, detail: {e}")
                        continue

                    tool_info = ToolInfo(
                        name=getattr(tool_class, 'name'),
                        description=getattr(tool_class, 'description'),
                        params=[],
                        source=ToolSourceEnum.MCP.value,
                        inputs=str(getattr(tool_class, 'inputs')),
                        output_type=getattr(tool_class, 'output_type'),
                        class_name=getattr(tool_class, 'name')
                    )

                    tools_info.append(tool_info)
            return tools_info
        except Exception as e:
            logger.error(f"mcp connection error: {str(e)}")
            return []

    loop = asyncio.get_event_loop()
    tools_list = await loop.run_in_executor(None, _get_tools_from_nexent_mcp_sync, mcp_server_list)
    return tools_list

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
        mcp_tools = await get_all_mcp_tools(tenant_id, user_id)
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
