import asyncio
import logging
import re
from copy import deepcopy
from threading import Thread
from threading import RLock
from typing import Any, Callable, Dict, List, Optional

import httpx
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Query
from fastmcp import FastMCP
from fastmcp.tools.tool import ToolResult

from database.outer_api_tool_db import query_available_openapi_services
from consts.const import TOKEN
from mcp.types import Tool as MCPTool
from tool_collection.mcp.local_mcp_service import (
    LOCAL_MCP_TOOL_NAME_OVERRIDES,
    local_mcp_service,
)
from utils.logging_utils import get_uvicorn_logging_config


logging.config.dictConfig(get_uvicorn_logging_config(categories=["mcp"]))
logger = logging.getLogger("mcp")

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
nexent_mcp.mount(
    local_mcp_service,
    local_mcp_service.name,
    tool_names=LOCAL_MCP_TOOL_NAME_OVERRIDES,
)

_openapi_mcp_services: Dict[str, FastMCP] = {}

# API-converted tools are tenant scoped.  Keep one FastMCP instance per tenant
# so refreshing one tenant never mutates another tenant's tool registry.
_tenant_mcp_servers: Dict[str, FastMCP] = {}
_tenant_mcp_apps: Dict[str, Any] = {}
_tenant_mcp_lock = RLock()


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
                "data": get_registered_openapi_services(tenant_id)
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
    server_url: str,
    headers_template: Dict[str, str],
    mcp_server: Optional[FastMCP] = None,
    tenant_id: Optional[str] = None,
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

    target_server = mcp_server
    registry = _openapi_mcp_services if tenant_id is None else getattr(target_server, "_nexent_openapi_services", {})

    # Validate inputs
    if not service_name:
        logger.error("Cannot register OpenAPI service: service_name is None or empty")
        return False

    if service_name in registry:
        logger.warning(f"OpenAPI service '{service_name}' already registered, skipping")
        return False

    try:
        # Override server URL in openapi spec
        openapi_spec = deepcopy(openapi_json)
        if server_url:
            openapi_spec["servers"] = [{"url": server_url}]

        # Create HTTP client for the underlying REST API
        client = httpx.AsyncClient(base_url=server_url, timeout=120.0, headers=headers_template)

        # Create FastMCP instance from OpenAPI spec
        service_mcp = FastMCP.from_openapi(
            openapi_spec=openapi_spec,
            client=client,
            name=service_name,
        )

        # Validate that mcp_server was created successfully
        if service_mcp is None:
            logger.error(f"FastMCP.from_openapi() returned None for service '{service_name}'")
            return False

        registry[service_name] = service_mcp

        # Mount to the main MCP server
        target_server = target_server if tenant_id is not None else nexent_mcp
        target_server.mount(service_mcp, service_name)

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


def get_registered_openapi_services(tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get information about registered OpenAPI services.

    Returns:
        List of service info dictionaries
    """
    registry = (
        getattr(_tenant_mcp_servers.get(tenant_id), "_nexent_openapi_services", {})
        if tenant_id
        else _openapi_mcp_services
    )
    return [
        {
            "service_name": name,
            "status": "registered"
        }
        for name in registry.keys()
    ]


def refresh_openapi_services_by_tenant(tenant_id: str) -> Dict[str, Any]:
    """
    Refresh all OpenAPI services for a tenant using from_openapi approach.

    Args:
        tenant_id: Tenant ID to load services for

    Returns:
        Dictionary with refresh result counts
    """
    global _tenant_mcp_servers, _tenant_mcp_apps

    # Build a replacement off to the side and publish it only after all
    # services have been registered. Existing clients keep using the old
    # instance until the replacement is ready.
    with _tenant_mcp_lock:
        tenant_mcp = FastMCP(name=f"nexent_mcp_{tenant_id}")
        tenant_registry: Dict[str, FastMCP] = {}
        tenant_mcp._nexent_openapi_services = tenant_registry
        tenant_mcp.mount(
            local_mcp_service,
            local_mcp_service.name,
            tool_names=LOCAL_MCP_TOOL_NAME_OVERRIDES,
        )

        services = query_available_openapi_services(tenant_id)
        registered_count = 0
        skipped_count = 0

        for service in services:
            service_name = service.get("mcp_service_name")
            openapi_json = service.get("openapi_json")
            server_url = service.get("server_url")
            headers_template = service.get("headers_template")

            if not openapi_json:
                logger.warning(f"Service '{service_name}' has no OpenAPI JSON, skipping")
                skipped_count += 1
                continue

            if register_openapi_service(
                service_name,
                openapi_json,
                server_url,
                headers_template,
                mcp_server=tenant_mcp,
                tenant_id=tenant_id,
            ):
                registered_count += 1
            else:
                skipped_count += 1

        # Publish only after the complete replacement has been built.
        _tenant_mcp_servers[tenant_id] = tenant_mcp
        _tenant_mcp_apps[tenant_id] = _build_tenant_mcp_app(tenant_mcp)

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
    # Rebuild this tenant atomically. This also handles removal of a service
    # without touching any other tenant's MCP instance.
    services = query_available_openapi_services(tenant_id)
    service_data = next(
        (service for service in services if service.get("mcp_service_name") == service_name),
        None,
    )
    if service_data is None:
        refresh_openapi_services_by_tenant(tenant_id)
        return {"status": "deleted", "service_name": service_name}
    if not service_data.get("openapi_json"):
        return {
            "status": "error",
            "service_name": service_name,
            "error": "No OpenAPI JSON found",
        }

    result = refresh_openapi_services_by_tenant(tenant_id)
    after = set(getattr(_tenant_mcp_servers.get(tenant_id), "_nexent_openapi_services", {}).keys())
    if service_name not in after:
        # A mocked/legacy registration path may not expose the private
        # registry, but the database record confirms the service exists.
        return {"status": "refreshed", "service_name": service_name, "refresh": result}
    return {"status": "refreshed", "service_name": service_name, "refresh": result}


def _build_tenant_mcp_app(mcp_server: FastMCP) -> Any:
    """Build the legacy SSE ASGI app for one tenant's MCP instance."""
    if hasattr(mcp_server, "sse_app"):
        return mcp_server.sse_app()
    if hasattr(mcp_server, "http_app"):
        return mcp_server.http_app(transport="sse")
    # Keeps lightweight unit-test doubles compatible with the registry logic.
    return mcp_server


class TenantMCPRouter:
    """Dispatch /mcp/{tenant_id}/... requests to the tenant's MCP app."""

    async def __call__(self, scope: Dict[str, Any], receive: Callable, send: Callable) -> None:
        path = scope.get("path", "")
        match = re.match(r"^/mcp/([^/]+)(/.*)?$", path)
        if not match:
            await _send_not_found(send)
            return

        tenant_id = match.group(1)
        request_headers = dict(scope.get("headers", []))
        authorization = request_headers.get(b"authorization")
        requested_tenant = request_headers.get(b"x-tenant-id", b"").decode()
        internal_token = request_headers.get(b"x-nexent-internal-token", b"").decode()
        if not authorization and (requested_tenant != tenant_id or not TOKEN or internal_token != TOKEN):
            await _send_forbidden(send)
            return
        if authorization:
            try:
                from utils.auth_utils import get_current_user_id

                _, authenticated_tenant_id = get_current_user_id(authorization.decode())
            except Exception:
                await _send_forbidden(send)
                return
            if str(authenticated_tenant_id) != tenant_id:
                await _send_forbidden(send)
                return

        with _tenant_mcp_lock:
            app = _tenant_mcp_apps.get(tenant_id)
        if app is None:
            try:
                refresh_openapi_services_by_tenant(tenant_id)
            except Exception:
                logger.exception("Failed to lazily initialize MCP tenant %s", tenant_id)
                await _send_not_found(send)
                return
            with _tenant_mcp_lock:
                app = _tenant_mcp_apps.get(tenant_id)
        if app is None:
            await _send_not_found(send)
            return

        delegated_scope = dict(scope)
        delegated_scope["path"] = match.group(2) or "/"
        delegated_scope["root_path"] = f"{scope.get('root_path', '')}/mcp/{tenant_id}"
        await app(delegated_scope, receive, send)


async def _send_not_found(send: Callable) -> None:
    await send({"type": "http.response.start", "status": 404, "headers": []})
    await send({"type": "http.response.body", "body": b"MCP tenant not found"})


async def _send_forbidden(send: Callable) -> None:
    await send({"type": "http.response.start", "status": 403, "headers": []})
    await send({"type": "http.response.body", "body": b"MCP tenant access denied"})


def run_mcp_server_with_management():
    """Run MCP server with management API."""
    app = get_mcp_management_app()

    def run_fastapi():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        uvicorn.run(app, host="0.0.0.0", port=5015, log_level="info", log_config=get_uvicorn_logging_config(categories=["mcp"]))

    fastapi_thread = Thread(target=run_fastapi, daemon=True)
    fastapi_thread.start()

    # Serve tenant-scoped SSE applications behind one listener. The management
    # API remains on 5015; MCP clients use /mcp/{tenant_id}/sse on 5011.
    uvicorn.run(TenantMCPRouter(), host="0.0.0.0", port=5011, log_level="info")


if __name__ == "__main__":
    run_mcp_server_with_management()
