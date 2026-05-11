import asyncio
import logging
import re
from threading import Thread
from typing import Any, Callable, Dict, List, Optional

import httpx
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Query
from fastmcp import FastMCP
from fastmcp.tools.tool import ToolResult

from database.outer_api_tool_db import query_available_openapi_services
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

_openapi_mcp_services: Dict[str, FastMCP] = {}


# FastAPI app for management endpoints (runs alongside the MCP server)
_mcp_management_app = None


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
                result = refresh_openapi_services_by_tenant(tenant_id)
                return {
                    "status": "success",
                    "data": result
                }
            except Exception as e:
                logger.error(f"Failed to refresh outer API tools: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @_mcp_management_app.post("/tools/openapi_service/refresh")
        async def refresh_openapi_services_endpoint(
            tenant_id: str = Query(..., description="Tenant ID"),
            authorization: Optional[str] = Header(None)
        ):
            """
            Refresh OpenAPI services (using from_openapi approach) for a tenant.

            This endpoint uses FastMCP.from_openapi() to batch-load all tools
            from each OpenAPI service, replacing individual tool registration.
            """
            try:
                result = refresh_openapi_services_by_tenant(tenant_id)
                return {
                    "status": "success",
                    "data": result
                }
            except Exception as e:
                logger.error(f"Failed to refresh OpenAPI services: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @_mcp_management_app.get("/tools/openapi_service")
        async def list_openapi_services_endpoint(
            tenant_id: str = Query(..., description="Tenant ID"),
            authorization: Optional[str] = Header(None)
        ):
            """List all registered OpenAPI service names and their tool counts."""
            return {
                "status": "success",
                "data": get_registered_openapi_services()
            }

        @_mcp_management_app.post("/tools/openapi_service/{service_name}/refresh")
        async def refresh_single_openapi_service_endpoint(
            service_name: str,
            tenant_id: str = Query(..., description="Tenant ID"),
            authorization: Optional[str] = Header(None)
        ):
            """
            Refresh a single OpenAPI service after tool deletion/update.

            This allows dynamic updates without reloading all services.
            """
            try:
                result = refresh_single_openapi_service(service_name, tenant_id)
                return {
                    "status": "success",
                    "data": result
                }
            except Exception as e:
                logger.error(f"Failed to refresh OpenAPI service '{service_name}': {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @_mcp_management_app.get("/tools/outer_api")
        async def list_outer_api_tools_endpoint(
            authorization: Optional[str] = Header(None)
        ):
            """List all registered outer API tool names (legacy endpoint, now returns OpenAPI services)."""
            return {
                "status": "success",
                "data": get_registered_openapi_services()
            }

    return _mcp_management_app


def _sanitize_function_name(name: str) -> str:
    """Sanitize function name to be valid MCP tool identifier."""
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    sanitized = re.sub(r'^[^a-zA-Z]+', '', sanitized)
    if not sanitized or sanitized[0].isdigit():
        sanitized = "tool_" + sanitized
    return sanitized


# --------------------------------------------------
# OpenAPI Service Registration (using from_openapi)
# --------------------------------------------------

def register_openapi_service(
    service_name: str,
    openapi_json: Dict[str, Any],
    server_url: str
) -> bool:
    """
    Register an OpenAPI service using FastMCP.from_openapi().

    This approach batch-loads all tools from the OpenAPI spec at once,
    instead of registering each tool individually.

    Args:
        service_name: MCP service name for grouping
        openapi_json: Complete OpenAPI JSON specification
        server_url: Base URL of the REST API server

    Returns:
        True if registered successfully, False otherwise
    """
    global _openapi_mcp_services

    # Validate inputs
    if not service_name:
        logger.error("Cannot register OpenAPI service: service_name is None or empty")
        return False

    if service_name in _openapi_mcp_services:
        logger.warning(f"OpenAPI service '{service_name}' already registered, skipping")
        return False

    try:
        # Override server URL in openapi spec
        openapi_spec = openapi_json.copy()
        if server_url:
            openapi_spec["servers"] = [{"url": server_url}]

        # Create HTTP client for the underlying REST API
        client = httpx.AsyncClient(base_url=server_url, timeout=30.0)

        # Create FastMCP instance from OpenAPI spec
        mcp_server = FastMCP.from_openapi(
            openapi_spec=openapi_spec,
            client=client,
            name=service_name,
        )

        # Validate that mcp_server was created successfully
        if mcp_server is None:
            logger.error(f"FastMCP.from_openapi() returned None for service '{service_name}'")
            return False

        _openapi_mcp_services[service_name] = mcp_server

        # Mount to the main MCP server
        nexent_mcp.mount(service_name, mcp_server)

        logger.info(f"Registered OpenAPI service: {service_name}")
        return True

    except Exception as e:
        logger.error(f"Failed to register OpenAPI service '{service_name}': {e}", exc_info=True)
        return False


def unregister_openapi_service(service_name: str) -> bool:
    """
    Unregister an OpenAPI service.

    Note: FastMCP does not support dynamic unmount, so this just removes
    the service from the registry. A full restart or architecture change
    would be needed to actually remove it from the running server.

    Args:
        service_name: Name of the service to unregister

    Returns:
        True if unregistered, False if not found
    """
    global _openapi_mcp_services
    if service_name in _openapi_mcp_services:
        del _openapi_mcp_services[service_name]
        logger.info(f"Unregistered OpenAPI service from registry: {service_name}")
        return True
    return False


def get_registered_openapi_services() -> List[Dict[str, Any]]:
    """
    Get information about registered OpenAPI services.

    Returns:
        List of service info dictionaries
    """
    return [
        {
            "service_name": name,
            "status": "registered"
        }
        for name in _openapi_mcp_services.keys()
    ]


def refresh_openapi_services_by_tenant(tenant_id: str) -> Dict[str, Any]:
    """
    Refresh all OpenAPI services for a tenant using from_openapi approach.

    Args:
        tenant_id: Tenant ID to load services for

    Returns:
        Dictionary with refresh result counts
    """
    global _openapi_mcp_services

    # Clear all mounted servers from both lists
    # NOTE: Both nexent_mcp._mounted_servers and _tool_manager._mounted_servers
    # must be cleared, otherwise tools remain visible via MCP protocol
    _openapi_mcp_services.clear()
    nexent_mcp._mounted_servers.clear()
    if hasattr(nexent_mcp._tool_manager, '_mounted_servers'):
        nexent_mcp._tool_manager._mounted_servers.clear()

    # Re-mount local_mcp_service after clearing
    nexent_mcp.mount(local_mcp_service, local_mcp_service.name)

    # Query all available OpenAPI services from database
    services = query_available_openapi_services(tenant_id)

    registered_count = 0
    skipped_count = 0

    for service in services:
        service_name = service.get("mcp_service_name")
        openapi_json = service.get("openapi_json")
        server_url = service.get("server_url")

        if not openapi_json:
            logger.warning(f"Service '{service_name}' has no OpenAPI JSON, skipping")
            skipped_count += 1
            continue

        if register_openapi_service(service_name, openapi_json, server_url):
            registered_count += 1
        else:
            skipped_count += 1

    logger.info(
        f"OpenAPI services refresh complete for tenant {tenant_id}: "
        f"{registered_count} registered, {skipped_count} skipped"
    )
    return {
        "registered": registered_count,
        "skipped": skipped_count,
        "total": len(services)
    }


def refresh_single_openapi_service(service_name: str, tenant_id: str) -> Dict[str, Any]:
    """
    Refresh a single OpenAPI service after tool deletion/update.

    This allows dynamic updates by:
    1. Removing the old service instance from memory
    2. Reloading from database with fresh data
    3. Re-registering the service

    Args:
        service_name: Name of the service to refresh
        tenant_id: Tenant ID

    Returns:
        Dictionary with refresh result
    """
    global _openapi_mcp_services

    # Remove old service instance from memory
    if service_name in _openapi_mcp_services:
        del _openapi_mcp_services[service_name]
        logger.info(f"Removed old instance of service '{service_name}'")

    # Query fresh data from database
    services = query_available_openapi_services(tenant_id)
    service_data = None
    for svc in services:
        if svc.get("mcp_service_name") == service_name:
            service_data = svc
            break

    if not service_data:
        # Service was deleted - remove from both mounted servers lists only
        # Do NOT clear local_mcp_service
        if hasattr(nexent_mcp, '_mounted_servers'):
            for mounted in list(nexent_mcp._mounted_servers):
                if mounted.prefix == service_name:
                    nexent_mcp._mounted_servers.remove(mounted)
        # Also clear from tool manager's mounted servers
        if hasattr(nexent_mcp._tool_manager, '_mounted_servers'):
            for mounted in list(nexent_mcp._tool_manager._mounted_servers):
                if mounted.prefix == service_name:
                    nexent_mcp._tool_manager._mounted_servers.remove(mounted)
        logger.info(f"Service '{service_name}' deleted, removed from MCP registry")
        return {
            "status": "deleted",
            "service_name": service_name
        }

    # Re-register with fresh data
    openapi_json = service_data.get("openapi_json")
    server_url = service_data.get("server_url")

    if not openapi_json:
        logger.warning(f"Service '{service_name}' has no OpenAPI JSON")
        return {
            "status": "error",
            "service_name": service_name,
            "error": "No OpenAPI JSON found"
        }

    success = register_openapi_service(service_name, openapi_json, server_url)
    return {
        "status": "refreshed" if success else "error",
        "service_name": service_name,
        "server_url": server_url
    }


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
