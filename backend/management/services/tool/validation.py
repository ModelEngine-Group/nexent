# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import importlib
import inspect
from contextlib import AsyncExitStack
from typing import Any, Dict, Optional
from urllib.parse import urljoin

from consts.const import (
    AIDP_API_KEY,
    AIDP_SERVER_URL,
    AIDP_TENANT_ID,
    DATA_PROCESS_SERVICE,
    LOCAL_MCP_SERVER,
    MCP_REQUEST_TIMEOUT_SECONDS,
    RUNTIME_MCP_TOOL_TIMEOUT_SECONDS,
    TOKEN,
)
from consts.exceptions import (
    MCPConnectionError,
    NotFoundException,
    ToolExecutionException,
)
from consts.model import ToolSourceEnum, ToolValidateRequest
from database.client import minio_client
from database.knowledge_db import get_knowledge_name_map_by_index_names
from database.remote_mcp_db import (
    get_mcp_authorization_token_by_name_and_url,
    get_mcp_custom_headers_by_name_and_url,
    get_mcp_server_by_name_and_tenant,
)
from fastmcp import Client
from management.services.file.service import validate_urls_access
from management.services.knowledge_base.service import (
    get_embedding_model_by_index_name,
    get_vector_db_core,
)
from management.services.mcp.addressing import get_tenant_local_mcp_server
from management.services.model.adapter import get_llm_adapter, get_vlm_adapter
from management.services.model.resolver import get_rerank_model
from management.services.tool.common import (
    logger,
)
from management.services.tool.langchain import discover_langchain_modules
from nexent.core.concurrency import run_blocking
from nexent.monitor import set_monitoring_context, set_monitoring_operation
from pydantic_core import PydanticUndefined


async def _call_mcp_tool(
    mcp_url: str,
    tool_name: str,
    inputs: Optional[Dict[str, Any]],
    authorization_token: Optional[str] = None,
    custom_headers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Common method to call MCP tool with connection handling.

    Args:
        mcp_url: MCP server URL
        tool_name: Name of the tool to call
        inputs: Parameters to pass to the tool
        authorization_token: Optional authorization token for authentication
        custom_headers: Optional custom HTTP headers

    Returns:
        Dict containing tool execution result

    Raises:
        MCPConnectionError: If MCP connection fails
    """
    transport = _create_mcp_transport(mcp_url, authorization_token, custom_headers)
    client = Client(transport=transport, timeout=RUNTIME_MCP_TOOL_TIMEOUT_SECONDS)
    async with AsyncExitStack() as stack:
        await asyncio.wait_for(
            stack.enter_async_context(client),
            timeout=MCP_REQUEST_TIMEOUT_SECONDS,
        )
        # Check if connected
        if not client.is_connected():
            logger.error("Failed to connect to MCP server")
            raise MCPConnectionError("Failed to connect to MCP server")

        # Call the tool
        try:
            result = await asyncio.wait_for(
                client.call_tool(name=tool_name, arguments=inputs),
                timeout=RUNTIME_MCP_TOOL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise MCPConnectionError(
                f"MCP tool execution timed out after {RUNTIME_MCP_TOOL_TIMEOUT_SECONDS:g} seconds"
            ) from exc
        return result.content[0].text


async def _validate_mcp_tool_nexent(
    tool_name: str,
    inputs: Optional[Dict[str, Any]],
    tenant_id: Optional[str] = None,
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
    actual_mcp_url = (
        get_tenant_local_mcp_server(tenant_id)
        if tenant_id
        else urljoin(LOCAL_MCP_SERVER, "sse")
    )
    if tenant_id:
        return await _call_mcp_tool(
            actual_mcp_url,
            tool_name,
            inputs,
            custom_headers={
                "X-Tenant-ID": str(tenant_id),
                "X-Nexent-Internal-Token": TOKEN,
            },
        )
    return await _call_mcp_tool(actual_mcp_url, tool_name, inputs)


async def _validate_mcp_tool_remote(
    tool_name: str,
    inputs: Optional[Dict[str, Any]],
    usage: str,
    tenant_id: Optional[str],
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

    # Get authorization token and custom headers from database
    authorization_token = None
    custom_headers = None
    if tenant_id:
        authorization_token = get_mcp_authorization_token_by_name_and_url(
            mcp_name=usage, mcp_server=actual_mcp_url, tenant_id=tenant_id
        )
        custom_headers = get_mcp_custom_headers_by_name_and_url(
            mcp_name=usage, mcp_server=actual_mcp_url, tenant_id=tenant_id
        )

    return await _call_mcp_tool(
        actual_mcp_url, tool_name, inputs, authorization_token, custom_headers
    )


def _get_tool_class_by_name(tool_name: str) -> Optional[type]:
    """
    Get tool class by tool name from nexent.core.tools package.

    Args:
        tool_name: Name of the tool to find

    Returns:
        Tool class if found, None otherwise
    """
    try:
        tools_package = importlib.import_module("nexent.core.tools")
        for name in dir(tools_package):
            obj = getattr(tools_package, name)
            if inspect.isclass(obj) and hasattr(obj, "name") and obj.name == tool_name:
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
    user_id: Optional[str] = None,
    language: str = "zh",
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
        instantiation_params = dict(params or {})
        if tool_name == "deepseek_search":
            instantiation_params.pop("localization", None)
            instantiation_params.pop("max_content_chars", None)
            instantiation_params["language"] = language
            instantiation_params["observer"] = None
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
                elif hasattr(param.default, "default"):
                    # This is a Field object, extract its default value
                    if param.default.default is not PydanticUndefined:
                        instantiation_params[param_name] = param.default.default
                else:
                    instantiation_params[param_name] = param.default

        if tool_name == "knowledge_base_search":
            index_names = instantiation_params.get("index_names", [])
            is_multimodal = instantiation_params.pop("multimodal", False)

            # Must have embedding model for knowledge base search
            if not index_names or not tenant_id:
                raise ToolExecutionException(
                    "Embedding model is required for knowledge_base_search but index_names or tenant_id is missing"
                )

            embedding_model, model_id, _ = get_embedding_model_by_index_name(
                tenant_id, index_names[0]
            )
            if not embedding_model:
                raise ToolExecutionException(
                    f"No embedding model found for index '{index_names[0]}'. "
                    f"Please configure an embedding model for this knowledge base."
                )

            vdb_core = get_vector_db_core()

            # Get rerank configuration
            rerank = instantiation_params.get("rerank", False)
            rerank_model_name = instantiation_params.get("rerank_model_name", "")
            rerank_model = None
            if rerank and rerank_model_name:
                rerank_model = get_rerank_model(
                    tenant_id=tenant_id, model_name=rerank_model_name
                )

            # Build display_name to index_name mapping for LLM parameter conversion
            display_name_to_index_map = {}
            if index_names:
                knowledge_name_map = get_knowledge_name_map_by_index_names(
                    index_names,
                    tenant_id=tenant_id,
                )
                for idx_name, kb_name in knowledge_name_map.items():
                    display_name_to_index_map[kb_name] = idx_name

            params = {
                **instantiation_params,
                "vdb_core": vdb_core,
                "embedding_model": embedding_model,
                "rerank_model": rerank_model,
                "display_name_to_index_map": display_name_to_index_map,
                # Internal access control: restrict results to specific document paths (path_or_urls)
                "document_paths": instantiation_params.get("document_paths"),
            }
            tool_instance = tool_class(**params)
        elif tool_name in ["dify_search", "datamate_search"]:
            # Get rerank configuration for dify and datamate search tools
            rerank = instantiation_params.get("rerank", False)
            rerank_model_name = instantiation_params.get("rerank_model_name", "")
            rerank_model = None

            if rerank and rerank_model_name:
                rerank_model = get_rerank_model(
                    tenant_id=tenant_id, model_name=rerank_model_name
                )

            params = {
                **instantiation_params,
                "rerank_model": rerank_model,
            }
            tool_instance = tool_class(**params)
        elif tool_name == "ragflow_search":
            # RAGFlowSearchTool does not accept rerank/rerank_model_name params
            # RAGFlow handles reranking internally via its API
            filtered_params = {
                k: v
                for k, v in instantiation_params.items()
                if k not in ["rerank_model", "rerank", "rerank_model_name"]
            }
            tool_instance = tool_class(**filtered_params)
        elif tool_name in ("haotian_search", "aidp_search", "ind_aidp_search"):
            # Haotian and AIDP share the same instantiation shape: drop the
            # backend-only rerank keys and explicitly set observer=None
            # (otherwise Python falls back to the FieldInfo default, which
            # later triggers "'FieldInfo' has no attribute 'lang'" in
            # forward()).
            filtered_params = {
                k: v
                for k, v in instantiation_params.items()
                if k not in ["observer", "rerank_model", "rerank"]
            }
            filtered_params["observer"] = None
            if tool_name == "ind_aidp_search":
                # Older UI builds incorrectly sent the independent AIDP KDS
                # selection under the local-search name ``index_names``.
                # Normalize that alias without ever replacing the independent
                # connector's own URL or API key.
                legacy_index_names = filtered_params.pop("index_names", None)
                if not filtered_params.get("kds_list") and legacy_index_names:
                    filtered_params["kds_list"] = legacy_index_names
            if tool_name == "aidp_search":
                # AIDP credentials are sourced from ``consts.const`` (i.e. the
                # process environment). Inject them here exactly as
                # ``create_agent_info`` does at runtime, so validation builds
                # the same tool instance shape. Never trust client-submitted
                # credentials.
                if not AIDP_SERVER_URL:
                    raise ToolExecutionException(
                        "AIDP is not configured for this deployment: "
                        "set AIDP_SERVER_URL before testing aidp_search"
                    )
                if not AIDP_API_KEY:
                    raise ToolExecutionException(
                        "AIDP is not configured for this deployment: "
                        "set AIDP_API_KEY before testing aidp_search"
                    )
                if not tenant_id or not user_id:
                    raise ToolExecutionException(
                        "Tenant ID and User ID are required for aidp_search validation"
                    )
                snapshot = _resolve_aidp_snapshot(user_id, tenant_id)
                requested_kds = _parse_kds_list(filtered_params.get("kds_list"))
                invalid_kds = [
                    kds_id
                    for kds_id in requested_kds
                    if kds_id not in snapshot.accessible_id_set
                ]
                if invalid_kds:
                    raise ToolExecutionException(
                        "aidp_search test selection contains an unavailable knowledge base"
                    )
                filtered_params["kds_list"] = requested_kds
                filtered_params["server_url"] = AIDP_SERVER_URL
                filtered_params["api_key"] = AIDP_API_KEY
                filtered_params["tenant_id"] = AIDP_TENANT_ID
            tool_instance = tool_class(**filtered_params)
        elif tool_name == "analyze_image":
            if not tenant_id or not user_id:
                raise ToolExecutionException(
                    f"Tenant ID and User ID are required for {tool_name} validation"
                )
            selected_model_id = instantiation_params.get("selected_model_id")
            image_to_text_model = get_vlm_adapter(
                tenant_id, selected_model_id, slot="vlm"
            )
            vlm_display_name = getattr(image_to_text_model, "display_name", None)
            set_monitoring_context(tenant_id=tenant_id)
            set_monitoring_operation("tool_validation", display_name=vlm_display_name)
            params = {
                **instantiation_params,
                "vlm_model": image_to_text_model,
                "storage_client": minio_client,
                "validate_url_access": lambda urls: validate_urls_access(urls, user_id),
            }
            tool_instance = tool_class(**params)
        elif tool_name in ["analyze_audio", "analyze_video"]:
            if not tenant_id or not user_id:
                raise ToolExecutionException(
                    f"Tenant ID and User ID are required for {tool_name} validation"
                )
            selected_model_id = instantiation_params.get("selected_model_id")
            slot = "vlm4" if tool_name == "analyze_audio" else "vlm3"
            understanding_model = get_vlm_adapter(
                tenant_id, selected_model_id, slot=slot
            )
            model_display_name = getattr(understanding_model, "display_name", None)
            set_monitoring_context(tenant_id=tenant_id)
            set_monitoring_operation("tool_validation", display_name=model_display_name)
            params = {
                **instantiation_params,
                "vlm_model": understanding_model,
                "storage_client": minio_client,
                "validate_url_access": lambda urls: validate_urls_access(urls, user_id),
            }
            tool_instance = tool_class(**params)
        elif tool_name == "analyze_text_file":
            if not tenant_id or not user_id:
                raise ToolExecutionException(
                    f"Tenant ID and User ID are required for {tool_name} validation"
                )
            selected_model_id = instantiation_params.get("selected_model_id")
            long_text_to_text_model = get_llm_adapter(
                tenant_id, selected_model_id, modality="llm_long_context"
            )
            llm_display_name = getattr(long_text_to_text_model, "display_name", None)
            set_monitoring_context(tenant_id=tenant_id)
            set_monitoring_operation("tool_validation", display_name=llm_display_name)
            params = {
                **instantiation_params,
                "llm_model": long_text_to_text_model,
                "storage_client": minio_client,
                "data_process_service_url": DATA_PROCESS_SERVICE,
                "validate_url_access": lambda urls: validate_urls_access(urls, user_id),
            }
            tool_instance = tool_class(**params)
        else:
            tool_instance = tool_class(**instantiation_params)

        # # Only pass declared runtime inputs to forward() to avoid unexpected kwargs.
        # declared_inputs = getattr(tool_class, "inputs", {}) or {}
        # allowed_input_names = (
        #     set(declared_inputs.keys()) if isinstance(declared_inputs, dict) else set()
        # )
        # filtered_runtime_inputs = (
        #     {k: v for k, v in runtime_inputs.items() if k in allowed_input_names}
        #     if allowed_input_names
        #     else runtime_inputs
        # )

        result = tool_instance.forward(**(inputs or {}))
        return result
    except Exception as e:
        logger.error(f"Local tool validation failed for {tool_name}: {e}")
        raise ToolExecutionException(
            f"Local tool {tool_name} validation failed: {str(e)}"
        )


def _validate_langchain_tool(
    tool_name: str, inputs: Optional[Dict[str, Any]] = None
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
            if hasattr(obj, "name") and obj.name == tool_name:
                target_tool = obj
                break

        if not target_tool:
            raise NotFoundException(f"Tool '{tool_name}' not found in LangChain tools")

        # Execute the tool directly
        result = target_tool.invoke(inputs or {})
        return result
    except Exception as e:
        logger.error(f"LangChain tool '{tool_name}' validation failed: {e}")
        raise ToolExecutionException(
            f"LangChain tool '{tool_name}' validation failed: {e}"
        )


async def validate_tool_impl(
    request: ToolValidateRequest,
    tenant_id: Optional[str] = None,
    user_id: Optional[str] = None,
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
            request.name,
            request.inputs,
            request.source,
            request.usage,
            request.params,
        )
        if source == ToolSourceEnum.MCP.value:
            if usage == "outer-apis":
                return await _validate_mcp_tool_nexent(tool_name, inputs, tenant_id)
            else:
                return await _validate_mcp_tool_remote(
                    tool_name, inputs, usage, tenant_id
                )
        elif source == ToolSourceEnum.LOCAL.value:
            if tool_name == "deepseek_search":
                return await run_blocking(
                    "validate-local-tool", _validate_local_tool,
                    tool_name, inputs, params, tenant_id, user_id,
                    language=request.language,
                    lane="model-tool-io", owner="management.services.tool.configuration",
                )
            return await run_blocking(
                "validate-local-tool",
                _validate_local_tool,
                tool_name,
                inputs,
                params,
                tenant_id,
                user_id,
                lane="model-tool-io",
                owner="management.services.tool.configuration",
            )
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


from management.services.tool.discovery import (
    _create_mcp_transport,
    _parse_kds_list,
    _resolve_aidp_snapshot,
)
