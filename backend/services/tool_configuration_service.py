import importlib
import inspect
import json
import logging
import time
from typing import Any, List, Optional, Dict
from urllib.parse import urljoin

import jsonref
import requests
from fastmcp import Client
from fastmcp.client.transports import SSETransport, StreamableHttpTransport
from pydantic_core import PydanticUndefined

from consts.const import DATA_PROCESS_SERVICE, LOCAL_MCP_SERVER, MCP_MANAGEMENT_API
from consts.exceptions import MCPConnectionError, NotFoundException, ToolExecutionException
from consts.model import ToolInstanceInfoRequest, ToolInfo, ToolSourceEnum, ToolValidateRequest
from database.client import minio_client
from database.outer_api_tool_db import (
    delete_outer_api_tool as db_delete_outer_api_tool,
    query_outer_api_tool_by_id,
    query_outer_api_tools_by_tenant,
    query_available_outer_api_tools,
    sync_outer_api_tools,
)
from database.remote_mcp_db import (
    get_mcp_authorization_token_by_name_and_url,
    get_mcp_records_by_tenant,
    get_mcp_server_by_name_and_tenant,
)
from database.tool_db import (
    check_tool_list_initialized,
    create_or_update_tool_by_tool_info,
    query_all_tools,
    query_tool_instances_by_id,
    search_last_tool_instance_by_tool_id,
    update_tool_table_from_scan_tool_list,
)
from mcpadapt.smolagents_adapter import _sanitize_function_name
from services.file_management_service import get_llm_model
from services.vectordatabase_service import get_embedding_model, get_rerank_model, get_vector_db_core
from database.client import minio_client
from services.image_service import get_vlm_model
from services.vectordatabase_service import get_embedding_model, get_vector_db_core
from utils.langchain_utils import discover_langchain_modules
from utils.tool_utils import get_local_tools_classes, get_local_tools_description_zh

logger = logging.getLogger("tool_configuration_service")


def _create_mcp_transport(url: str, authorization_token: Optional[str] = None):
    """
    Create appropriate MCP transport based on URL ending.

    Args:
        url: MCP server URL
        authorization_token: Optional authorization token

    Returns:
        Transport instance (SSETransport or StreamableHttpTransport)
    """
    url_stripped = url.strip()
    headers = {"Authorization": authorization_token} if authorization_token else {}

    if url_stripped.endswith("/sse"):
        return SSETransport(url=url_stripped, headers=headers)
    elif url_stripped.endswith("/mcp"):
        return StreamableHttpTransport(url=url_stripped, headers=headers)
    else:
        # Default to StreamableHttpTransport for unrecognized formats
        return StreamableHttpTransport(url=url_stripped, headers=headers)


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
        # Get class-level init_param_descriptions for fallback
        init_param_descriptions = getattr(tool_class, 'init_param_descriptions', {})

        init_params_list = []
        sig = inspect.signature(tool_class.__init__)
        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue

            # Check if parameter has a default value and if it should be excluded
            if param.default != inspect.Parameter.empty:
                if hasattr(param.default, 'exclude') and param.default.exclude:
                    continue

            # Get description in both languages
            param_description = param.default.description if hasattr(param.default, 'description') else ""

            # First try to get from param.default.description_zh (FieldInfo)
            param_description_zh = param.default.description_zh if hasattr(param.default, 'description_zh') else None

            # Fallback to init_param_descriptions if not found
            if param_description_zh is None and param_name in init_param_descriptions:
                param_description_zh = init_param_descriptions[param_name].get('description_zh')

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
            if getattr(param.default, "json_schema_extra", None):
                optional_override = param.default.json_schema_extra.get("optional")
                if optional_override is not None:
                    param_info["optional"] = optional_override

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
                tools_info.extend(await get_tool_from_remote_mcp_server(
                    mcp_server_name=record["mcp_name"],
                    remote_mcp_server=record["mcp_server"],
                    tenant_id=tenant_id
                ))
            except Exception as e:
                logger.error(f"mcp connection error: {str(e)}")

    default_mcp_url = urljoin(LOCAL_MCP_SERVER, "sse")
    tools_info.extend(await get_tool_from_remote_mcp_server(
        mcp_server_name="outer-apis",
        remote_mcp_server=default_mcp_url,
        tenant_id=None
    ))
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


async def get_tool_from_remote_mcp_server(
    mcp_server_name: str,
    remote_mcp_server: str,
    tenant_id: Optional[str] = None,
    authorization_token: Optional[str] = None
):
    """
    Get the tool information from the remote MCP server, avoid blocking the event loop

    Args:
        mcp_server_name: Name of the MCP server
        remote_mcp_server: URL of the MCP server
        tenant_id: Optional tenant ID for database lookup of authorization_token
        authorization_token: Optional authorization token for authentication (if not provided and tenant_id is given, will be fetched from database)
    """
    # Get authorization token from database if not provided
    if authorization_token is None and tenant_id:
        authorization_token = get_mcp_authorization_token_by_name_and_url(
            mcp_name=mcp_server_name,
            mcp_server=remote_mcp_server,
            tenant_id=tenant_id
        )

    tools_info = []

    try:
        transport = _create_mcp_transport(remote_mcp_server, authorization_token)
        client = Client(transport=transport, timeout=10)
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

    _refresh_outer_api_tools_in_mcp(tenant_id)

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
    inputs: Optional[Dict[str, Any]],
    authorization_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Common method to call MCP tool with connection handling.

    Args:
        mcp_url: MCP server URL
        tool_name: Name of the tool to call
        inputs: Parameters to pass to the tool
        authorization_token: Optional authorization token for authentication

    Returns:
        Dict containing tool execution result

    Raises:
        MCPConnectionError: If MCP connection fails
    """
    transport = _create_mcp_transport(mcp_url, authorization_token)
    client = Client(transport=transport)
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

    # Get authorization token from database
    authorization_token = None
    if tenant_id:
        authorization_token = get_mcp_authorization_token_by_name_and_url(
            mcp_name=usage,
            mcp_server=actual_mcp_url,
            tenant_id=tenant_id
        )

    return await _call_mcp_tool(actual_mcp_url, tool_name, inputs, authorization_token)


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

        runtime_inputs = dict(inputs or {})

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
            # Compatibility: historically index_names might be sent in runtime inputs.
            # knowledge_base_search now treats index_names as init params (tool config),
            # not forward() inputs.
            if "index_names" in runtime_inputs and "index_names" not in instantiation_params:
                instantiation_params["index_names"] = runtime_inputs.pop("index_names")

            is_multimodal = instantiation_params.pop("multimodal", False)
            embedding_model = get_embedding_model(tenant_id=tenant_id, is_multimodal=is_multimodal)
            vdb_core = get_vector_db_core()

            # Get rerank configuration
            rerank = instantiation_params.get("rerank", False)
            rerank_model_name = instantiation_params.get("rerank_model_name", "")
            rerank_model = None
            if rerank and rerank_model_name:
                rerank_model = get_rerank_model(tenant_id=tenant_id, model_name=rerank_model_name)

            params = {
                **instantiation_params,
                'vdb_core': vdb_core,
                'embedding_model': embedding_model,
                'rerank_model': rerank_model,
            }
            tool_instance = tool_class(**params)
        elif tool_name in ["dify_search", "datamate_search"]:
            # Get rerank configuration for dify and datamate search tools
            rerank = instantiation_params.get("rerank", False)
            rerank_model_name = instantiation_params.get("rerank_model_name", "")
            rerank_model = None
            if rerank and rerank_model_name:
                rerank_model = get_rerank_model(tenant_id=tenant_id, model_name=rerank_model_name)

            params = {
                **instantiation_params,
                'rerank_model': rerank_model,
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

        # Only pass declared runtime inputs to forward() to avoid unexpected kwargs.
        declared_inputs = getattr(tool_class, "inputs", {}) or {}
        allowed_input_names = (
            set(declared_inputs.keys()) if isinstance(declared_inputs, dict) else set()
        )
        filtered_runtime_inputs = (
            {k: v for k, v in runtime_inputs.items() if k in allowed_input_names}
            if allowed_input_names
            else runtime_inputs
        )

        result = tool_instance.forward(**filtered_runtime_inputs)
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
            if usage == "outer-apis":
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


# --------------------------------------------------
# Outer API Tools (OpenAPI to MCP Conversion)
# --------------------------------------------------

def parse_openapi_to_mcp_tools(openapi_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Parse OpenAPI JSON and convert it to a list of MCP tool definitions.

    Args:
        openapi_json: OpenAPI 3.x specification as dictionary

    Returns:
        List of tool definition dictionaries suitable for storage and MCP registration
    """
    tools = []
    paths = openapi_json.get("paths", {})

    servers = openapi_json.get("servers", [])
    base_url = servers[0].get("url", "") if servers else ""

    components = openapi_json.get("components", {})
    schemas = components.get("schemas", {})

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue

        for method, operation in path_item.items():
            if method.upper() not in ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]:
                continue

            if not isinstance(operation, dict):
                continue

            operation_id = operation.get("operationId") or _generate_operation_id(method.upper(), path)
            tool_name = _sanitize_function_name(operation_id)

            summary = operation.get("summary", "")
            description = operation.get("description", summary)
            if not description:
                description = f"{method.upper()} {path}"

            input_schema = _parse_request_body(operation, schemas)

            full_url = base_url.rstrip("/") + "/" + path.lstrip("/") if base_url else path

            tool_def = {
                "name": tool_name,
                "description": description,
                "method": method.upper(),
                "url": full_url,
                "headers_template": {},
                "query_template": _parse_parameters(operation.get("parameters", []), "query"),
                "body_template": _parse_request_body_template(operation, schemas),
                "input_schema": input_schema
            }
            tools.append(tool_def)

    return tools


def _generate_operation_id(method: str, path: str) -> str:
    """Generate operation ID from method and path."""
    path_clean = path.strip("/").replace("/", "_").replace("-", "_").replace("{", "").replace("}", "")
    return f"{method.lower()}_{path_clean}"


def _resolve_ref(ref: str, schemas: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolve a $ref reference to its actual schema.

    Args:
        ref: Reference string like "#/components/schemas/CountOutput"
        schemas: Dictionary of schemas from components (already extracted from components/schemas)

    Returns:
        Resolved schema dictionary
    """
    if not ref.startswith("#/"):
        return {}

    parts = ref.lstrip("#/").split("/")

    if len(parts) >= 2 and parts[-2] == "schemas":
        schema_name = parts[-1]
        if schema_name in schemas:
            return schemas[schema_name]
        return {}

    if len(parts) == 1:
        schema_name = parts[0]
        if schema_name in schemas:
            return schemas[schema_name]
        return {}

    return {}


def _resolve_schema(schema: Dict[str, Any], schemas: Dict[str, Any], depth: int = 0) -> Dict[str, Any]:
    """
    Recursively resolve schema, handling $ref and nested schemas.

    Args:
        schema: Schema dictionary, possibly containing $ref
        schemas: Dictionary of schemas from components
        depth: Current recursion depth to prevent infinite loops

    Returns:
        Fully resolved schema dictionary
    """
    if depth > 10:
        return schema

    if "$ref" in schema:
        resolved = _resolve_ref(schema["$ref"], schemas)
        return _resolve_schema(resolved, schemas, depth + 1)

    result = schema.copy()

    if "items" in result:
        result["items"] = _resolve_schema(result["items"], schemas, depth + 1)

    if "properties" in result:
        resolved_properties = {}
        for prop_name, prop_schema in result["properties"].items():
            resolved_properties[prop_name] = _resolve_schema(prop_schema, schemas, depth + 1)
        result["properties"] = resolved_properties

    if "allOf" in result:
        resolved_allof = []
        for sub_schema in result["allOf"]:
            resolved_allof.append(_resolve_schema(sub_schema, schemas, depth + 1))
        result["allOf"] = resolved_allof

    if "anyOf" in result:
        resolved_anyof = []
        for sub_schema in result["anyOf"]:
            resolved_anyof.append(_resolve_schema(sub_schema, schemas, depth + 1))
        result["anyOf"] = resolved_anyof

    if "oneOf" in result:
        resolved_oneof = []
        for sub_schema in result["oneOf"]:
            resolved_oneof.append(_resolve_schema(sub_schema, schemas, depth + 1))
        result["oneOf"] = resolved_oneof

    return result


def _parse_parameters(parameters: List[Dict], param_type: str) -> Dict[str, Any]:
    """Parse OpenAPI parameters of specified type."""
    result = {}
    for param in parameters:
        if param.get("in") == param_type:
            param_name = param.get("name", "")
            schema = param.get("schema", {"type": "string"})
            result[param_name] = {
                "required": param.get("required", False),
                "description": param.get("description", ""),
                "schema": schema
            }
    return result


def _parse_request_body(operation: Dict[str, Any], schemas: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse OpenAPI requestBody to MCP input schema.
    Handles $ref references and nested schemas.

    Args:
        operation: OpenAPI operation dictionary
        schemas: Dictionary of schemas from components

    Returns:
        MCP-compatible input schema
    """
    input_schema = {
        "type": "object",
        "properties": {},
        "required": []
    }

    parameters = operation.get("parameters", [])
    for param in parameters:
        if param.get("in") == "query":
            param_name = param.get("name", "")
            schema = param.get("schema", {"type": "string"})
            resolved_schema = _resolve_schema(schema, schemas)
            input_schema["properties"][param_name] = {
                "type": resolved_schema.get("type", "string"),
                "description": param.get("description", "")
            }
            if param.get("required"):
                input_schema["required"].append(param_name)

    request_body = operation.get("requestBody", {})
    if request_body:
        content = request_body.get("content", {})
        json_content = content.get("application/json", {})
        json_schema = json_content.get("schema", {})

        resolved_schema = _resolve_schema(json_schema, schemas)

        if resolved_schema.get("type") == "object" and "properties" in resolved_schema:
            for prop_name, prop_schema in resolved_schema["properties"].items():
                if prop_name not in input_schema["properties"]:
                    input_schema["properties"][prop_name] = {
                        "type": prop_schema.get("type", "string"),
                        "description": prop_schema.get("description", "")
                    }

            required_props = resolved_schema.get("required", [])
            for req in required_props:
                if req not in input_schema["required"]:
                    input_schema["required"].append(req)

    return input_schema


def _parse_request_body_template(operation: Dict[str, Any], schemas: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse OpenAPI requestBody to extract template for request body.
    Handles $ref references.

    Args:
        operation: OpenAPI operation dictionary
        schemas: Dictionary of schemas from components

    Returns:
        Template dictionary with default values
    """
    request_body = operation.get("requestBody", {})
    if not request_body:
        return {}

    content = request_body.get("content", {})
    json_content = content.get("application/json", {})
    json_schema = json_content.get("schema", {})

    resolved_schema = _resolve_schema(json_schema, schemas)

    if resolved_schema.get("type") == "object" and "properties" in resolved_schema:
        template = {}
        for prop_name, prop_schema in resolved_schema["properties"].items():
            default_value = prop_schema.get("example") or prop_schema.get("default")
            if default_value is not None:
                template[prop_name] = default_value
        return template

    return {}


def import_openapi_json(openapi_json: Dict[str, Any], tenant_id: str, user_id: str) -> Dict[str, Any]:
    """
    Import OpenAPI JSON and convert/sync tools to database.

    Args:
        openapi_json: OpenAPI 3.x specification as dictionary
        tenant_id: Tenant ID for multi-tenancy
        user_id: User ID for audit

    Returns:
        Dictionary with import result (created, updated, deleted counts)
    """
    tools = parse_openapi_to_mcp_tools(openapi_json)
    result = sync_outer_api_tools(tools, tenant_id, user_id)
    result["total_tools"] = len(tools)
    logger.info(f"Imported {len(tools)} tools from OpenAPI JSON for tenant {tenant_id}")
    return result


def list_outer_api_tools(tenant_id: str) -> List[Dict[str, Any]]:
    """
    List all outer API tools for a tenant.

    Args:
        tenant_id: Tenant ID

    Returns:
        List of tool dictionaries
    """
    return query_outer_api_tools_by_tenant(tenant_id)


def get_outer_api_tool(tool_id: int, tenant_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a specific outer API tool by ID.

    Args:
        tool_id: Tool ID
        tenant_id: Tenant ID

    Returns:
        Tool dictionary or None
    """
    return query_outer_api_tool_by_id(tool_id, tenant_id)


def delete_outer_api_tool(tool_id: int, tenant_id: str, user_id: str) -> bool:
    """
    Delete an outer API tool.

    Args:
        tool_id: Tool ID
        tenant_id: Tenant ID
        user_id: User ID for audit

    Returns:
        True if deleted, False if not found
    """
    # Get tool info before deletion to get the tool name
    tool_info = query_outer_api_tool_by_id(tool_id, tenant_id)
    tool_name = tool_info.get("name") if tool_info else None

    # Delete from database
    deleted = db_delete_outer_api_tool(tool_id, tenant_id, user_id)

    if deleted and tool_name:
        # Also remove from MCP server
        _remove_outer_api_tool_from_mcp(tool_name, tenant_id)

    return deleted


def _remove_outer_api_tool_from_mcp(tool_name: str, tenant_id: str) -> bool:
    """
    Remove a specific outer API tool from the MCP server via HTTP API.

    Args:
        tool_name: Name of the tool to remove
        tenant_id: Tenant ID

    Returns:
        True if removed successfully, False otherwise
    """
    remove_url = f"{MCP_MANAGEMENT_API}/tools/outer_api/{tool_name}"
    try:
        response = requests.delete(remove_url, timeout=10)
        if response.ok:
            logger.info(f"Removed outer API tool '{tool_name}' from MCP server")
            return True
        else:
            logger.warning(f"Failed to remove tool '{tool_name}' from MCP: {response.status_code}")
            return False
    except requests.RequestException as e:
        logger.warning(f"Failed to remove tool '{tool_name}' from MCP: {e}")
        return False


def _refresh_outer_api_tools_in_mcp(tenant_id: str) -> Dict[str, Any]:
    """
    Refresh outer API tools in MCP server via HTTP API.

    Includes retry logic to handle cases where the MCP Server's management API
    might not be fully ready immediately after a restart.

    Args:
        tenant_id: Tenant ID

    Returns:
        Dictionary with refresh result
    """
    refresh_url = f"{MCP_MANAGEMENT_API}/tools/outer_api/refresh"
    max_retries = 3
    retry_delay = 1.0

    for attempt in range(max_retries):
        try:
            response = requests.post(
                refresh_url,
                params={"tenant_id": tenant_id},
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Refreshed outer API tools for tenant {tenant_id}: {result}")
            return result.get("data", {})
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                logger.warning(
                    f"Failed to refresh outer API tools (attempt {attempt + 1}/{max_retries}): {e}. "
                    f"Retrying in {retry_delay}s..."
                )
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                logger.error(f"Failed to refresh outer API tools after {max_retries} attempts: {e}")
                return {"error": str(e)}
        except Exception as e:
            logger.warning(f"Failed to refresh outer API tools in MCP: {e}")
            return {"error": str(e)}
