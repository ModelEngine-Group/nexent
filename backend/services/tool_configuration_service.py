import importlib
import inspect
import json
import logging
from typing import Any, List, Optional, Dict
from urllib.parse import urljoin

from pydantic_core import PydanticUndefined
from fastmcp import Client
import jsonref
from mcpadapt.smolagents_adapter import _sanitize_function_name

from consts.const import LOCAL_MCP_SERVER, DATA_PROCESS_SERVICE
from consts.exceptions import MCPConnectionError, ToolExecutionException, NotFoundException
from consts.model import ToolInstanceInfoRequest, ToolInfo, ToolSourceEnum, ToolValidateRequest
from database.remote_mcp_db import get_mcp_records_by_tenant, get_mcp_server_by_name_and_tenant
from database.tool_db import (
    create_or_update_tool_by_tool_info,
    query_all_tools,
    query_tool_instances_by_id,
    update_tool_table_from_scan_tool_list,
    search_last_tool_instance_by_tool_id,
    check_tool_list_initialized,
)
from services.file_management_service import get_llm_model
from services.vectordatabase_service import get_embedding_model, get_vector_db_core
from database.client import minio_client
from services.image_service import get_vlm_model

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

            # Get description in both languages
            param_description = param.default.description if hasattr(param.default, 'description') else ""
            param_description_zh = param.default.description_zh if hasattr(param.default, 'description_zh') else None

            param_info = {
                "type": python_type_to_json_schema(param.annotation),
                "name": param_name,
                "description": param_description,
                "description_zh": param_description_zh
            }
            if param.default.default is PydanticUndefined:
                param_info["optional"] = False
            else:
                param_info["default"] = param.default.default
                param_info["optional"] = True

            init_params_list.append(param_info)

        # Get tool fixed attributes with bilingual support
        tool_description_zh = getattr(tool_class, 'description_zh', None)
        tool_inputs = getattr(tool_class, 'inputs', {})

        # Process inputs to add bilingual descriptions
        processed_inputs = {}
        if isinstance(tool_inputs, dict):
            for key, value in tool_inputs.items():
                if isinstance(value, dict):
                    processed_inputs[key] = {
                        **value,
                        "description_zh": value.get("description_zh")
                    }
                else:
                    processed_inputs[key] = value

        tool_info = ToolInfo(
            name=getattr(tool_class, 'name'),
            description=getattr(tool_class, 'description'),
            description_zh=tool_description_zh,
            params=init_params_list,
            source=ToolSourceEnum.LOCAL.value,
            inputs=json.dumps(processed_inputs, ensure_ascii=False),
            output_type=getattr(tool_class, 'output_type'),
            category=getattr(tool_class, 'category'),
            class_name=tool_class.__name__,
            usage=None,
            origin_name=getattr(tool_class, 'name')
        )
        tools_info.append(tool_info)
    return tools_info


def get_local_tools_description_zh() -> Dict[str, Dict]:
    """
    Get description_zh for all local tools from SDK (not persisted to DB).

    Returns:
        Dict mapping tool name to {"description_zh": ..., "params": [...], "inputs": {...}}
    """
    tools_classes = get_local_tools_classes()
    result = {}
    for tool_class in tools_classes:
        tool_name = getattr(tool_class, 'name')

        # Get tool-level description_zh
        description_zh = getattr(tool_class, 'description_zh', None)

        # Get class-level init_param_descriptions for fallback
        init_param_descriptions = getattr(tool_class, 'init_param_descriptions', {})

        # Get param-level description_zh
        init_params_list = []
        sig = inspect.signature(tool_class.__init__)
        for param_name, param in sig.parameters.items():
            if param_name == "self" or param.default.exclude:
                continue

            # First try to get from param.default.description_zh (FieldInfo)
            param_description_zh = param.default.description_zh if hasattr(param.default, 'description_zh') else None

            # Fallback to init_param_descriptions if not found
            if param_description_zh is None and param_name in init_param_descriptions:
                param_description_zh = init_param_descriptions[param_name].get('description_zh')

            init_params_list.append({
                "name": param_name,
                "description_zh": param_description_zh
            })

        # Get inputs description_zh
        tool_inputs = getattr(tool_class, 'inputs', {})
        inputs_description_zh = {}
        if isinstance(tool_inputs, dict):
            for key, value in tool_inputs.items():
                if isinstance(value, dict) and value.get("description_zh"):
                    inputs_description_zh[key] = {
                        "description_zh": value.get("description_zh")
                    }

        result[tool_name] = {
            "description_zh": description_zh,
            "params": init_params_list,
            "inputs": inputs_description_zh
        }
    return result


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


# --------------------------------------------------
# LangChain tools discovery (functions decorated with @tool)
# --------------------------------------------------

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
        category=None
    )
    return tool_info


def get_langchain_tools() -> List[ToolInfo]:
    """Discover LangChain tools in the specified directory.

    We dynamically import every `*.py` file and extract objects that look like
    LangChain tools (based on presence of `name` & `description`).  Any valid
    tool is converted to ToolInfo with source = "langchain".
    """
    from utils.langchain_utils import discover_langchain_modules

    tools_info: List[ToolInfo] = []
    # Discover all objects that look like LangChain tools
    discovered_tools = discover_langchain_modules()

    # Process discovered tools
    for obj, filename in discovered_tools:
        try:
            tool_info = _build_tool_info_from_langchain(obj)
            tools_info.append(tool_info)
        except Exception as e:
            logger.warning(
                f"Error processing LangChain tool in {filename}: {e}")

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
        # only update connected server
        if record["status"]:
            try:
                tools_info.extend(await get_tool_from_remote_mcp_server(mcp_server_name=record["mcp_name"],
                                                                        remote_mcp_server=record["mcp_server"]))
            except Exception as e:
                logger.error(f"mcp connection error: {str(e)}")

    default_mcp_url = urljoin(LOCAL_MCP_SERVER, "sse")
    tools_info.extend(await get_tool_from_remote_mcp_server(mcp_server_name="nexent",
                                                            remote_mcp_server=default_mcp_url))
    return tools_info


def search_tool_info_impl(agent_id: int, tool_id: int, tenant_id: str):
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
    tool_instance = query_tool_instances_by_id(
        agent_id, tool_id, tenant_id)

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


def update_tool_info_impl(tool_info: ToolInstanceInfoRequest, tenant_id: str, user_id: str):
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
    # Use version_no from request if provided, otherwise default to 0
    version_no = getattr(tool_info, 'version_no', 0)
    tool_instance = create_or_update_tool_by_tool_info(
        tool_info, tenant_id, user_id, version_no=version_no)
    return {
        "tool_instance": tool_instance
    }


async def get_tool_from_remote_mcp_server(mcp_server_name: str, remote_mcp_server: str):
    """get the tool information from the remote MCP server, avoid blocking the event loop"""
    tools_info = []

    try:
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

                sanitized_tool_name = _sanitize_function_name(tool.name)
                tool_info = ToolInfo(name=sanitized_tool_name,
                                     description=tool.description,
                                     params=[],
                                     source=ToolSourceEnum.MCP.value,
                                     inputs=str(input_schema["properties"]),
                                     output_type="string",
                                     class_name=sanitized_tool_name,
                                     usage=mcp_server_name,
                                     origin_name=tool.name,
                                     category=None)
                tools_info.append(tool_info)
            return tools_info
    except BaseException as e:
        logger.error(
            f"failed to get tool from remote MCP server, detail: {e}", exc_info=True)
        # Convert all failures (including SystemExit) to domain error to avoid process exit
        raise MCPConnectionError(
            f"failed to get tool from remote MCP server, detail: {e}")


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
        Scan and gather all available tools from both local and MCP sources

        Args:
            tenant_id: Tenant ID for MCP tools (required for MCP tools)
            user_id: User ID for MCP tools (required for MCP tools)

        Returns:
            List of ToolInfo objects containing tool metadata
        """
    local_tools = get_local_tools()
    # Discover LangChain tools (decorated functions) and include them in the
    langchain_tools = get_langchain_tools()

    try:
        mcp_tools = await get_all_mcp_tools(tenant_id)
    except Exception as e:
        logger.error(f"failed to get all mcp tools, detail: {e}")
        raise MCPConnectionError(f"failed to get all mcp tools, detail: {e}")

    update_tool_table_from_scan_tool_list(tenant_id=tenant_id,
                                          user_id=user_id,
                                          tool_list=local_tools+mcp_tools+langchain_tools)


async def list_all_tools(tenant_id: str):
    """
    List all tools for a given tenant
    """
    tools_info = query_all_tools(tenant_id)

    # Get description_zh from SDK for local tools (not persisted to DB)
    local_tool_descriptions = get_local_tools_description_zh()

    # only return the fields needed
    formatted_tools = []
    for tool in tools_info:
        tool_name = tool.get("name")

        # Merge description_zh from SDK for local tools
        if tool.get("source") == "local" and tool_name in local_tool_descriptions:
            sdk_info = local_tool_descriptions[tool_name]
            description_zh = sdk_info.get("description_zh")

            # Merge params description_zh from SDK (independent of tool-level description_zh)
            params = tool.get("params", [])
            if params:
                for param in params:
                    if not param.get("description_zh"):
                        # Find matching param in SDK
                        for sdk_param in sdk_info.get("params", []):
                            if sdk_param.get("name") == param.get("name"):
                                param["description_zh"] = sdk_param.get("description_zh")
                                break

            # Merge inputs description_zh from SDK
            inputs_str = tool.get("inputs", "{}")
            try:
                inputs = json.loads(inputs_str) if isinstance(inputs_str, str) else inputs_str
                if isinstance(inputs, dict):
                    for key, value in inputs.items():
                        if isinstance(value, dict) and not value.get("description_zh"):
                            # Find matching input in SDK
                            sdk_inputs = sdk_info.get("inputs", {})
                            if key in sdk_inputs:
                                value["description_zh"] = sdk_inputs[key].get("description_zh")
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
            "category": tool.get("category")
        }
        formatted_tools.append(formatted_tool)

    return formatted_tools


def load_last_tool_config_impl(tool_id: int, tenant_id: str, user_id: str):
    """
    Load the last tool configuration for a given tool ID
    """
    tool_instance = search_last_tool_instance_by_tool_id(
        tool_id, tenant_id, user_id)
    if tool_instance is None:
        raise ValueError(
            f"Tool configuration not found for tool ID: {tool_id}")
    return tool_instance.get("params", {})


async def _call_mcp_tool(
    mcp_url: str,
    tool_name: str,
    inputs: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Common method to call MCP tool with connection handling.

    Args:
        mcp_url: MCP server URL
        tool_name: Name of the tool to call
        inputs: Parameters to pass to the tool

    Returns:
        Dict containing tool execution result

    Raises:
        MCPConnectionError: If MCP connection fails
    """
    client = Client(mcp_url)
    async with client:
        # Check if connected
        if not client.is_connected():
            logger.error("Failed to connect to MCP server")
            raise MCPConnectionError("Failed to connect to MCP server")

        # Call the tool
        result = await client.call_tool(
            name=tool_name,
            arguments=inputs
        )
        return result.content[0].text


async def _validate_mcp_tool_nexent(
    tool_name: str,
    inputs: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Validate MCP tool using local nexent server.

    Args:
        tool_name: Name of the tool to test
        inputs: Parameters to pass to the tool

    Returns:
        Dict containing validation result

    Raises:
        MCPConnectionError: If MCP connection fails
    """
    actual_mcp_url = urljoin(LOCAL_MCP_SERVER, "sse")
    return await _call_mcp_tool(actual_mcp_url, tool_name, inputs)


async def _validate_mcp_tool_remote(
    tool_name: str,
    inputs: Optional[Dict[str, Any]],
    usage: str,
    tenant_id: Optional[str]
) -> Dict[str, Any]:
    """
    Validate MCP tool using remote server from database.

    Args:
        tool_name: Name of the tool to test
        inputs: Parameters to pass to the tool
        usage: MCP name for database lookup
        tenant_id: Tenant ID for database queries

    Returns:
        Dict containing validation result

    Raises:
        NotFoundException: If MCP server not found
        MCPConnectionError: If MCP connection fails
    """
    # Query mcp_record_t table to get mcp_server by mcp_name
    actual_mcp_url = get_mcp_server_by_name_and_tenant(usage, tenant_id)
    if not actual_mcp_url:
        raise NotFoundException(f"MCP server not found for name: {usage}")

    return await _call_mcp_tool(actual_mcp_url, tool_name, inputs)


def _get_tool_class_by_name(tool_name: str) -> Optional[type]:
    """
    Get tool class by tool name from nexent.core.tools package.

    Args:
        tool_name: Name of the tool to find

    Returns:
        Tool class if found, None otherwise
    """
    try:
        tools_package = importlib.import_module('nexent.core.tools')
        for name in dir(tools_package):
            obj = getattr(tools_package, name)
            if inspect.isclass(obj) and hasattr(obj, 'name') and obj.name == tool_name:
                return obj
        return None
    except Exception as e:
        logger.error(f"Failed to get tool class for {tool_name}: {e}")
        return None


def _validate_local_tool(
    tool_name: str,
    inputs: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    tenant_id: Optional[str] = None,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate local tool by actually instantiating and calling it.

    Args:
        tool_name: Name of the tool to test
        inputs: Parameters to pass to the tool's forward method
        params: Configuration parameters for tool initialization
        tenant_id: Tenant ID for knowledge base tools (optional)
        user_id: User ID for knowledge base tools (optional)

    Returns:
        Dict[str, Any]: The actual result returned by the tool's forward method,
                       serving as proof that the tool works correctly

    Raises:
        NotFoundException: If tool class not found
        ToolExecutionException: If tool execution fails
    """
    try:
        # Get tool class by name
        tool_class = _get_tool_class_by_name(tool_name)
        if not tool_class:
            raise NotFoundException(f"Tool class not found for {tool_name}")

        # Parse instantiation parameters first
        instantiation_params = params or {}
        # Get signature and extract default values for all parameters
        sig = inspect.signature(tool_class.__init__)

        # Extract default values for all parameters not provided in instantiation_params
        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue

            # If parameter not provided, extract default value
            if param_name not in instantiation_params:
                if param.default is PydanticUndefined:
                    continue
                elif hasattr(param.default, 'default'):
                    # This is a Field object, extract its default value
                    if param.default.default is not PydanticUndefined:
                        instantiation_params[param_name] = param.default.default
                else:
                    instantiation_params[param_name] = param.default

        if tool_name == "knowledge_base_search":
            embedding_model = get_embedding_model(tenant_id=tenant_id)
            vdb_core = get_vector_db_core()
            params = {
                **instantiation_params,
                'vdb_core': vdb_core,
                'embedding_model': embedding_model,
            }
            tool_instance = tool_class(**params)
        elif tool_name == "analyze_image":
            if not tenant_id or not user_id:
                raise ToolExecutionException(
                    f"Tenant ID and User ID are required for {tool_name} validation")
            image_to_text_model = get_vlm_model(tenant_id=tenant_id)
            params = {
                **instantiation_params,
                'vlm_model': image_to_text_model,
                'storage_client': minio_client
            }
            tool_instance = tool_class(**params)
        elif tool_name == "analyze_text_file":
            if not tenant_id or not user_id:
                raise ToolExecutionException(
                    f"Tenant ID and User ID are required for {tool_name} validation")
            long_text_to_text_model = get_llm_model(tenant_id=tenant_id)
            params = {
                **instantiation_params,
                'llm_model': long_text_to_text_model,
                'storage_client': minio_client,
                "data_process_service_url": DATA_PROCESS_SERVICE
            }
            tool_instance = tool_class(**params)
        else:
            tool_instance = tool_class(**instantiation_params)

        result = tool_instance.forward(**(inputs or {}))
        return result
    except Exception as e:
        logger.error(f"Local tool validation failed for {tool_name}: {e}")
        raise ToolExecutionException(
            f"Local tool {tool_name} validation failed: {str(e)}")


def _validate_langchain_tool(
    tool_name: str,
    inputs: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Validate LangChain tool by actually executing it.

    Args:
        tool_name: Name of the tool to test
        inputs: Parameters to pass to the tool for execution test

    Returns:
        Dict containing validation result - success returns result

    Raises:
        NotFoundException: If tool not found in LangChain tools
        ToolExecutionException: If tool execution fails
    """
    try:
        from utils.langchain_utils import discover_langchain_modules

        # Discover all LangChain tools
        discovered_tools = discover_langchain_modules()

        # Find the target tool by name
        target_tool = None
        for obj, filename in discovered_tools:
            if hasattr(obj, 'name') and obj.name == tool_name:
                target_tool = obj
                break

        if not target_tool:
            raise NotFoundException(
                f"Tool '{tool_name}' not found in LangChain tools")

        # Execute the tool directly
        result = target_tool.invoke(inputs or {})
        return result
    except Exception as e:
        logger.error(f"LangChain tool '{tool_name}' validation failed: {e}")
        raise ToolExecutionException(
            f"LangChain tool '{tool_name}' validation failed: {e}")


async def validate_tool_impl(
    request: ToolValidateRequest,
    tenant_id: Optional[str] = None,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate a tool from various sources (MCP, local, or LangChain).

    Args:
        request: Tool validation request containing tool details
        tenant_id: Tenant ID for database queries (optional)
        user_id: User ID for database queries (optional)

    Returns:
        Dict containing validation result - success returns tool result, failure returns error message

    Raises:
        NotFoundException: If tool is not found
        MCPConnectionError: If MCP connection fails
        ToolExecutionException: If tool execution fails
        Exception: If unsupported tool source is provided
    """
    try:
        tool_name, inputs, source, usage, params = (
            request.name, request.inputs, request.source, request.usage, request.params)
        if source == ToolSourceEnum.MCP.value:
            if usage == "nexent":
                return await _validate_mcp_tool_nexent(tool_name, inputs)
            else:
                return await _validate_mcp_tool_remote(tool_name, inputs, usage, tenant_id)
        elif source == ToolSourceEnum.LOCAL.value:
            return _validate_local_tool(tool_name, inputs, params, tenant_id, user_id)
        elif source == ToolSourceEnum.LANGCHAIN.value:
            return _validate_langchain_tool(tool_name, inputs)
        else:
            raise Exception(f"Unsupported tool source: {source}")

    except NotFoundException as e:
        logger.error(f"Tool not found: {e}")
        raise NotFoundException(str(e))
    except MCPConnectionError as e:
        logger.error(f"MCP connection failed: {e}")
        raise MCPConnectionError(str(e))
    except Exception as e:
        logger.error(f"Validate Tool failed: {e}")
        raise ToolExecutionException(str(e))
