import asyncio
import logging
import re
from threading import Thread
from typing import Any, Callable, Dict, List, Optional

import requests
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Query
from fastmcp import FastMCP
from fastmcp.tools.tool import ToolResult

from database.outer_api_tool_db import query_available_outer_api_tools
from mcp.types import Tool as MCPTool
from tool_collection.mcp.local_mcp_service import local_mcp_service
from utils.logging_utils import configure_logging

configure_logging(logging.INFO)
logger = logging.getLogger("mcp_service")

"""
hierarchical proxy architecture:
- local service layer: stable local mount service
- remote proxy layer: dynamic managed remote mcp service proxy
- outer_api layer: dynamic registered outer API tools
"""


class CustomFunctionTool:
    """
    Custom tool class that uses custom parameters schema instead of inferring from function signature.
    """
    def __init__(
        self,
        name: str,
        fn: Callable[..., Any],
        description: str,
        parameters: Dict[str, Any],
        output_schema: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.key = name
        self.fn = fn
        self.description = description
        self.parameters = parameters
        self.output_schema = output_schema
        self.tags: set = set()
        self.enabled: bool = True
        self.annotations: Optional[Any] = None

    def to_mcp_tool(self, name: str = None, **kwargs: Any) -> Any:
        """Convert to MCP tool format."""
        return MCPTool(
            name=self.name,
            description=self.description,
            inputSchema=self.parameters,
            outputSchema=self.output_schema,
        )

    async def run(self, arguments: Dict[str, Any]) -> Any:
        """Run the tool with arguments."""
        try:
            result = self.fn(**arguments)
            if hasattr(result, '__await__'):
                result = await result
            return ToolResult(content=str(result))
        except Exception as e:
            logger.error(f"Tool '{self.name}' execution failed: {e}")
            raise


nexent_mcp = FastMCP(name="nexent_mcp")
nexent_mcp.mount(local_mcp_service.name, local_mcp_service)

_registered_outer_api_tools: Dict[str, Callable] = {}


# FastAPI app for management endpoints (runs alongside the MCP server)
_mcp_management_app = None


def _require_management_authorization(authorization: Optional[str]) -> tuple[str, str]:
    """Validate the caller for MCP management endpoints."""
    try:
        from utils.auth_utils import get_current_user_id
        return get_current_user_id(authorization)
    except Exception as e:
        logger.warning(f"Unauthorized MCP management API access: {e}")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication token"
        ) from e


def get_mcp_management_app():
    """Get or create FastAPI app for MCP management endpoints."""
    global _mcp_management_app
    if _mcp_management_app is None:
        _mcp_management_app = FastAPI(title="Nexent MCP Management")

        @_mcp_management_app.post("/tools/outer_api/refresh")
        async def refresh_outer_api_tools_endpoint(
            tenant_id: str = Query(..., description="Tenant ID"),
            authorization: Optional[str] = Header(None)
        ):
            """
            Refresh outer API tools from database to MCP server.

            This endpoint is called by other services (like nexent-config)
            to notify the MCP server to reload outer API tools.
            """
            try:
                _require_management_authorization(authorization)
                result = refresh_outer_api_tools(tenant_id)
                return {
                    "status": "success",
                    "data": result
                }
            except Exception as e:
                logger.error(f"Failed to refresh outer API tools: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @_mcp_management_app.get("/tools/outer_api")
        async def list_outer_api_tools_endpoint(
            authorization: Optional[str] = Header(None)
        ):
            """List all registered outer API tool names."""
            _require_management_authorization(authorization)
            return {
                "status": "success",
                "data": get_registered_outer_api_tools()
            }

        @_mcp_management_app.delete("/tools/outer_api/{tool_name}")
        async def remove_outer_api_tool_endpoint(
            tool_name: str,
            authorization: Optional[str] = Header(None)
        ):
            """
            Remove a specific outer API tool from the MCP server.

            Args:
                tool_name: Name of the tool to remove

            Returns:
                Success status
            """
            try:
                _require_management_authorization(authorization)
                sanitized_name = _sanitize_function_name(tool_name)
                result = remove_outer_api_tool(sanitized_name)
                if result:
                    return {
                        "status": "success",
                        "message": f"Tool '{sanitized_name}' removed"
                    }
                else:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Tool '{sanitized_name}' not found"
                    )
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to remove outer API tool '{tool_name}': {e}")
                raise HTTPException(status_code=500, detail=str(e))

    return _mcp_management_app


def _sanitize_function_name(name: str) -> str:
    """Sanitize function name to be valid MCP tool identifier."""
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    sanitized = re.sub(r'^[^a-zA-Z]+', '', sanitized)
    if not sanitized or sanitized[0].isdigit():
        sanitized = "tool_" + sanitized
    return sanitized


def _build_headers(headers_template: Dict[str, Any], kwargs: Dict[str, Any]) -> Dict[str, str]:
    """Build request headers from template."""
    headers = {}
    for key, value in headers_template.items():
        if isinstance(value, str) and "{" in value:
            try:
                headers[key] = value.format(**kwargs)
            except KeyError:
                headers[key] = value
        else:
            headers[key] = value
    return headers


def _build_url(url_template: str, kwargs: Dict[str, Any]) -> str:
    """Build URL from template, replacing path parameters."""
    path_params = re.findall(r'\{(\w+)\}', url_template)
    for param in path_params:
        if param in kwargs:
            url_template = url_template.replace(f'{{{param}}}', str(kwargs[param]))
    return url_template


def _build_query_params(query_template: Dict[str, Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Build query parameters from template."""
    params = {}
    for key, value in query_template.items():
        if key in kwargs:
            params[key] = kwargs[key]
        elif isinstance(value, dict) and "default" in value:
            params[key] = value["default"]
        else:
            params[key] = value
    return params


def _build_request_body(body_template: Dict[str, Any], kwargs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build request body from template and kwargs."""
    body = {}
    for key, value in body_template.items():
        if key in kwargs:
            body[key] = kwargs[key]
        elif value is not None:
            body[key] = value
    for key, value in kwargs.items():
        if key not in body and key not in _get_non_body_keys():
            body[key] = value
    return body if body else None


def _get_non_body_keys() -> set:
    """Get keys that should not be included in body."""
    return {"url", "method", "headers", "params", "json", "data"}


def _register_single_outer_api_tool(api_def: Dict[str, Any]) -> bool:
    """
    Register a single outer API tool to the MCP server.

    Args:
        api_def: Tool definition from database

    Returns:
        True if registered successfully, False otherwise
    """
    try:
        tool_name = _sanitize_function_name(api_def.get("name", "unnamed_tool"))

        if tool_name in _registered_outer_api_tools:
            logger.warning(f"Tool '{tool_name}' already registered, skipping")
            return False

        method = api_def.get("method", "GET").upper()
        url_template = api_def.get("url", "")
        headers_template = api_def.get("headers_template") or {}
        query_template = api_def.get("query_template") or {}
        body_template = api_def.get("body_template") or {}
        input_schema = api_def.get("input_schema") or {}

        _registered_outer_api_tools[tool_name] = {
            "api_def": api_def
        }

        flat_input_schema = _build_flat_input_schema(input_schema)

        async def tool_func(**kwargs: Any) -> str:
            """Execute the outer API call."""
            try:
                url = _build_url(url_template, kwargs)
                headers = _build_headers(headers_template, kwargs)
                query_params = _build_query_params(query_template, kwargs)
                body = _build_request_body(body_template, kwargs) if method in ["POST", "PUT", "PATCH"] else None

                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=query_params,
                    json=body
                )

                response.raise_for_status()
                return response.text

            except requests.RequestException as e:
                logger.error(f"Outer API tool '{tool_name}' failed: {e}")
                return f"Error: {str(e)}"
            except Exception as e:
                logger.error(f"Outer API tool '{tool_name}' unexpected error: {e}")
                return f"Error: {str(e)}"

        logger.info(f"Flat input schema for '{tool_name}': {flat_input_schema}")

        tool = CustomFunctionTool(
            name=tool_name,
            fn=tool_func,
            description=api_def.get("description", f"Outer API tool: {tool_name}"),
            parameters=flat_input_schema,
        )

        nexent_mcp.add_tool(tool)

        logger.info(f"Registered outer API tool: {tool_name}")
        return True

    except Exception as e:
        logger.error(f"Failed to register outer API tool '{api_def.get('name')}': {e}", exc_info=True)
        return False


def _build_flat_input_schema(input_schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a flat input schema from the OpenAPI input schema.

    If the input schema has a nested structure (with a single property containing
    an object schema), extract the inner properties to create a flat schema.

    Args:
        input_schema: Input schema from OpenAPI

    Returns:
        Flattened JSON schema for MCP tool parameters
    """
    if not input_schema:
        return {"type": "object", "properties": {}}

    logger.debug(f"Original input_schema: {input_schema}")

    properties = input_schema.get("properties", {})
    required = input_schema.get("required", []) or []

    if len(properties) == 1:
        single_key = list(properties.keys())[0]
        single_prop = properties[single_key]

        if single_prop.get("type") == "object" and "properties" in single_prop:
            logger.debug(f"Flattening nested schema with key '{single_key}'")
            return {
                "type": "object",
                "properties": single_prop.get("properties", {}),
                "required": single_prop.get("required", []) or []
            }

    result = {
        "type": "object",
        "properties": properties,
        "required": required if required else None
    }
    logger.debug(f"Processed input_schema: {result}")
    return result


def register_outer_api_tools(tenant_id: str) -> Dict[str, int]:
    """
    Register all outer API tools from database to the MCP server.

    Args:
        tenant_id: Tenant ID to load tools for

    Returns:
        Dictionary with counts of registered tools
    """
    tools = query_available_outer_api_tools(tenant_id)

    registered_count = 0
    skipped_count = 0

    for tool in tools:
        if _register_single_outer_api_tool(tool):
            registered_count += 1
        else:
            skipped_count += 1

    logger.info(f"Outer API tools registration complete: {registered_count} registered, {skipped_count} skipped")
    return {
        "registered": registered_count,
        "skipped": skipped_count,
        "total": len(tools)
    }


def refresh_outer_api_tools(tenant_id: str) -> Dict[str, int]:
    """
    Refresh all outer API tools: unregister all, then re-register from database.

    Args:
        tenant_id: Tenant ID to load tools for

    Returns:
        Dictionary with counts of refreshed tools
    """
    unregister_all_outer_api_tools()
    return register_outer_api_tools(tenant_id)


def unregister_all_outer_api_tools() -> int:
    """
    Unregister all outer API tools from the MCP server.

    Returns:
        Number of tools unregistered
    """
    global _registered_outer_api_tools
    count = len(_registered_outer_api_tools)
    _registered_outer_api_tools.clear()
    logger.info(f"Unregistered {count} outer API tools")
    return count


def unregister_outer_api_tool(tool_name: str) -> bool:
    """
    Unregister a specific outer API tool from the registry.

    Args:
        tool_name: Name of the tool to unregister

    Returns:
        True if unregistered, False if not found
    """
    sanitized_name = _sanitize_function_name(tool_name)
    if sanitized_name in _registered_outer_api_tools:
        del _registered_outer_api_tools[sanitized_name]
        logger.info(f"Unregistered outer API tool from registry: {sanitized_name}")
        return True
    return False


def remove_outer_api_tool(tool_name: str) -> bool:
    """
    Remove a specific outer API tool from both the registry and MCP server.

    Args:
        tool_name: Name of the tool to remove

    Returns:
        True if removed, False if not found
    """
    sanitized_name = _sanitize_function_name(tool_name)

    # Remove from registry
    if sanitized_name in _registered_outer_api_tools:
        del _registered_outer_api_tools[sanitized_name]

    # Remove from MCP server
    try:
        nexent_mcp.remove_tool(sanitized_name)
        logger.info(f"Removed outer API tool from MCP server: {sanitized_name}")
        return True
    except Exception as e:
        logger.warning(f"Tool '{sanitized_name}' not found in MCP server or already removed: {e}")
        # Return True if it was in registry (db cleanup happened)
        return sanitized_name not in _registered_outer_api_tools


def get_registered_outer_api_tools() -> List[str]:
    """
    Get list of registered outer API tool names.

    Returns:
        List of tool names
    """
    return list(_registered_outer_api_tools.keys())


def run_mcp_server_with_management():
    """Run MCP server with management API."""
    app = get_mcp_management_app()

    def run_fastapi():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        uvicorn.run(app, host="0.0.0.0", port=5015, log_level="info")

    fastapi_thread = Thread(target=run_fastapi, daemon=True)
    fastapi_thread.start()

    nexent_mcp.run(transport="sse", host="0.0.0.0", port=5011)


if __name__ == "__main__":
    run_mcp_server_with_management()
