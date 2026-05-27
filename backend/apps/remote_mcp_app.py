import logging
import json
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, UploadFile, File, Form, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from http import HTTPStatus

from consts.const import ENABLE_UPLOAD_IMAGE
from consts.exceptions import (
    MCPConnectionError,
    MCPNameIllegal,
    MCPContainerError,
    McpNotFoundError,
    McpValidationError,
    McpNameConflictError,
    McpPortConflictError,
)
from consts.model import (
    MCPConfigRequest,
    AddMcpServiceRequest,
    AddContainerMcpServiceRequest,
    UpdateMcpServiceRequest,
    EnableMcpServiceRequest,
    DisableMcpServiceRequest,
    HealthcheckMcpServiceRequest,
    ListMcpServicesQuery,
)
from services.remote_mcp_service import (
    get_remote_mcp_server_list,
    check_mcp_health_and_update_db,
    delete_mcp_by_container_id,
    upload_and_start_mcp_image,
    update_remote_mcp_server_list,
    attach_mcp_container_permissions,
    get_mcp_record_by_id,
    list_mcp_service_tools_by_id,
    add_mcp_service,
    add_container_mcp_service,
    update_mcp_service,
    update_mcp_service_enabled,
    delete_mcp_service,
    check_mcp_service_health,
    check_container_port_conflict,
    suggest_container_port,
)
from services.tool_configuration_service import get_tool_from_remote_mcp_server
from services.mcp_container_service import MCPContainerManager
from utils.auth_utils import get_current_user_info

router = APIRouter(prefix="/mcp")
logger = logging.getLogger("remote_mcp_app")


# ---------------------------------------------------------------------------
# Tools Endpoint
# ---------------------------------------------------------------------------

@router.get("/tools")
async def get_tools_from_mcp(
    mcp_id: int = Query(..., description="MCP service ID"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """
    Get tools from MCP server by MCP ID.
    """
    try:
        _, tenant_id, _ = get_current_user_info(authorization, http_request)

        tools_info = await list_mcp_service_tools_by_id(
            tenant_id=tenant_id,
            mcp_id=mcp_id,
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "tools": [t.model_dump() if hasattr(t, 'model_dump') else t for t in tools_info],
                "status": "success"
            }
        )
    except McpNotFoundError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except MCPConnectionError as e:
        logger.error(f"Failed to get tools from MCP server: {e}")
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            detail="MCP connection failed"
        )
    except Exception as e:
        logger.error(f"get tools from MCP server failed, error: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to get tools from MCP server."
        )


# ---------------------------------------------------------------------------
# Add Endpoints
# ---------------------------------------------------------------------------

@router.post("/add")
async def add_mcp_service_endpoint(
    payload: AddMcpServiceRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """
    Add an MCP service.
    Supports both remote MCP (URL-based) and local MCP (record-based).
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        await add_mcp_service(
            tenant_id=tenant_id,
            user_id=user_id,
            name=payload.name,
            description=payload.description,
            source=payload.source.value if hasattr(payload.source, 'value') else payload.source,
            server_url=payload.server_url,
            tags=payload.tags,
            authorization_token=payload.authorization_token,
            custom_headers=payload.custom_headers,
            container_config=payload.container_config,
            registry_json=payload.registry_json,
            enabled=payload.enabled if payload.enabled is not None else False,
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "Successfully added MCP service", "status": "success"}
        )

    except MCPNameIllegal as e:
        logger.error(f"Failed to add MCP service: {e}")
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail="MCP name already exists")
    except MCPConnectionError as e:
        logger.error(f"Failed to add MCP service: {e}")
        raise HTTPException(status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail="MCP connection failed")
    except McpValidationError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to add MCP service: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to add MCP service"
        )


@router.post("/add-from-config")
async def add_container_mcp_service_endpoint(
    payload: AddContainerMcpServiceRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """
    Add a container-based MCP service with full configuration.
    Endpoint path is kept as /add-from-config for backward compatibility.
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        container_info = await add_container_mcp_service(
            tenant_id=tenant_id,
            user_id=user_id,
            name=payload.name,
            description=payload.description,
            source=payload.source.value if hasattr(payload.source, 'value') else payload.source,
            tags=payload.tags,
            authorization_token=payload.authorization_token,
            registry_json=payload.registry_json,
            port=payload.port,
            mcp_config=payload.mcp_config,
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "status": "success",
                "data": {
                    "service_name": container_info.get("service_name"),
                    "mcp_url": container_info.get("mcp_url"),
                    "container_id": container_info.get("container_id"),
                    "container_name": container_info.get("container_name"),
                    "host_port": container_info.get("host_port"),
                },
            },
        )

    except McpNameConflictError as e:
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=str(e))
    except McpPortConflictError as e:
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=str(e))
    except McpValidationError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except MCPContainerError as e:
        logger.error(f"Failed to start MCP container service: {e}")
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            detail="Docker service unavailable"
        )
    except MCPConnectionError as e:
        logger.error(f"MCP connection failed when adding container service: {e}")
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            detail="MCP connection failed"
        )
    except Exception as e:
        logger.error(f"Failed to add container MCP service: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to add container MCP service"
        )


# ---------------------------------------------------------------------------
# Update Endpoint
# ---------------------------------------------------------------------------

@router.put("/update")
async def update_mcp_service_endpoint(
    payload: UpdateMcpServiceRequest,
    tenant_id: Optional[str] = Query(
        None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Update an existing MCP service by ID."""
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(authorization, http_request)
        effective_tenant_id = tenant_id or auth_tenant_id

        update_mcp_service(
            tenant_id=effective_tenant_id,
            user_id=user_id,
            mcp_id=payload.mcp_id,
            new_name=payload.name,
            description=payload.description,
            server_url=payload.server_url,
            authorization_token=payload.authorization_token,
            custom_headers=payload.custom_headers,
            tags=payload.tags,
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "Successfully updated MCP service", "status": "success"}
        )

    except McpNotFoundError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except McpValidationError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update MCP service: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update MCP service"
        )


# ---------------------------------------------------------------------------
# Delete Endpoints
# ---------------------------------------------------------------------------

@router.delete("/{mcp_id}")
async def delete_mcp_by_id(
    mcp_id: int,
    tenant_id: Optional[str] = Query(
        None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Delete MCP service by ID."""
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(authorization, http_request)
        effective_tenant_id = tenant_id or auth_tenant_id

        await delete_mcp_service(
            tenant_id=effective_tenant_id,
            user_id=user_id,
            mcp_id=mcp_id
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "Successfully deleted MCP service", "status": "success"}
        )
    except McpNotFoundError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete MCP service: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to delete MCP service"
        )


@router.delete("/container/{container_id}")
async def stop_mcp_container(
    container_id: str,
    tenant_id: Optional[str] = Query(
        None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Stop and remove MCP container."""
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(authorization, http_request)
        effective_tenant_id = tenant_id or auth_tenant_id

        try:
            container_manager = MCPContainerManager()
        except MCPContainerError as e:
            logger.error(f"Failed to initialize container manager: {e}")
            raise HTTPException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                detail="Docker service unavailable"
            )

        success = await container_manager.stop_mcp_container(container_id)

        if success:
            await delete_mcp_by_container_id(
                tenant_id=effective_tenant_id,
                user_id=user_id,
                container_id=container_id,
            )
            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={
                    "message": "Container and MCP service stopped successfully",
                    "status": "success",
                },
            )
        else:
            return JSONResponse(
                status_code=HTTPStatus.NOT_FOUND,
                content={"message": "Container not found", "status": "error"},
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to stop container: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop container: {str(e)}"
        )


# ---------------------------------------------------------------------------
# List Endpoints
# ---------------------------------------------------------------------------

@router.get("/list")
async def get_mcp_list(
    tenant_id: Optional[str] = Query(
        None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """
    Get list of MCP services.
    Returns remote MCP list with full details including container_id, description,
    enabled, source, update_time, tags, container_port, registry_json, config_json,
    container_status, and authorization_token.
    """
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(authorization, http_request)
        effective_tenant_id = tenant_id or auth_tenant_id

        remote_mcp_list = await get_remote_mcp_server_list(
            tenant_id=effective_tenant_id,
            user_id=user_id,
            is_need_auth=True
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "remote_mcp_server_list": remote_mcp_list,
                "enable_upload_image": ENABLE_UPLOAD_IMAGE,
                "status": "success"
            }
        )
    except Exception as e:
        logger.error(f"Failed to get MCP list: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to get MCP list"
        )


@router.get("/record/{mcp_id}")
async def get_mcp_record(
    mcp_id: int,
    tenant_id: Optional[str] = Query(
        None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Get single MCP record by ID."""
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(authorization, http_request)
        effective_tenant_id = tenant_id or auth_tenant_id

        mcp_record = await get_mcp_record_by_id(
            mcp_id=mcp_id,
            tenant_id=effective_tenant_id
        )

        if not mcp_record:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail="MCP record not found"
            )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "mcp_name": mcp_record.get("mcp_name"),
                "mcp_server": mcp_record.get("mcp_server"),
                "authorization_token": mcp_record.get("authorization_token"),
                "custom_headers": mcp_record.get("custom_headers"),
                "status": "success"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get MCP record: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to get MCP record"
        )


@router.get("/containers")
async def list_mcp_containers(
    tenant_id: Optional[str] = Query(
        None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """List all MCP containers for the current tenant."""
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(
            authorization, http_request)
        effective_tenant_id = tenant_id or auth_tenant_id

        try:
            container_manager = MCPContainerManager()
        except MCPContainerError as e:
            logger.error(f"Failed to initialize container manager: {e}")
            raise HTTPException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                detail="Docker service unavailable"
            )

        containers = container_manager.list_mcp_containers(
            tenant_id=effective_tenant_id)
        containers = attach_mcp_container_permissions(
            containers=containers,
            tenant_id=effective_tenant_id,
            user_id=user_id,
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "containers": containers,
                "status": "success"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list containers: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to list containers: {str(e)}"
        )


@router.get("/container/{container_id}/logs")
async def get_container_logs(
    container_id: str,
    tail: int = 100,
    follow: bool = Query(
        True, description="Whether to follow logs in real-time"),
    tenant_id: Optional[str] = Query(
        None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Get logs from MCP container via SSE stream."""
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(
            authorization, http_request)
        effective_tenant_id = tenant_id or auth_tenant_id

        try:
            container_manager = MCPContainerManager()
        except MCPContainerError as e:
            logger.error(f"Failed to initialize container manager: {e}")
            raise HTTPException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                detail="Docker service unavailable"
            )

        async def generate_log_stream():
            """Generate SSE stream of container logs."""
            try:
                async for log_line in container_manager.stream_container_logs(
                    container_id, tail=tail, follow=follow
                ):
                    payload = json.dumps(
                        {"logs": log_line, "status": "success"},
                        ensure_ascii=False
                    )
                    yield f"data: {payload}\n\n"
            except Exception as stream_error:
                logger.error(f"Error in log stream: {stream_error}")
                error_payload = json.dumps(
                    {
                        "logs": f"An error occurred while streaming container logs.",
                        "status": "error"
                    },
                    ensure_ascii=False
                )
                yield f"data: {error_payload}\n\n"

        return StreamingResponse(
            generate_log_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get container logs: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to get container logs."
        )


@router.get("/healthcheck")
async def check_mcp_health(
    mcp_id: int = Query(..., description="MCP service ID"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Check MCP service health by ID."""
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        health_status = await check_mcp_service_health(
            tenant_id=tenant_id,
            user_id=user_id,
            mcp_id=mcp_id,
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": {"health_status": health_status}}
        )
    except McpNotFoundError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except McpValidationError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except MCPConnectionError as e:
        logger.error(f"MCP connection failed: {e}")
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            detail=str(e) or "MCP connection failed"
        )
    except Exception as e:
        logger.error(f"Failed to check MCP health: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to check MCP health"
        )


# ---------------------------------------------------------------------------
# Port Management Endpoints
# ---------------------------------------------------------------------------

@router.get("/port/check")
async def check_mcp_port(
    port: int = Query(..., ge=1, le=65535),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Check if a port is available for MCP container."""
    try:
        get_current_user_info(authorization, http_request)
        available = check_container_port_conflict(port=port)
        no_cache_headers = {
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": {"available": available}},
            headers=no_cache_headers
        )
    except McpValidationError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to check MCP port: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to check MCP port"
        )


@router.get("/port/suggest")
async def suggest_mcp_port(
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Suggest an available port for MCP container."""
    try:
        get_current_user_info(authorization, http_request)
        port = suggest_container_port()
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": {"port": port}}
        )
    except McpPortConflictError as e:
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to suggest MCP port: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to suggest MCP port"
        )


# ---------------------------------------------------------------------------
# Enable/Disable Endpoints
# ---------------------------------------------------------------------------

@router.post("/enable")
async def enable_mcp_service(
    payload: EnableMcpServiceRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Enable an MCP service by ID."""
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        await update_mcp_service_enabled(
            tenant_id=tenant_id,
            user_id=user_id,
            mcp_id=payload.mcp_id,
            enabled=True,
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success"}
        )
    except McpNotFoundError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except McpNameConflictError as e:
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=str(e))
    except McpPortConflictError as e:
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=str(e))
    except McpValidationError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except MCPConnectionError as e:
        logger.error(f"MCP connection failed while enabling service: {e}")
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            detail="MCP connection failed"
        )
    except Exception as e:
        logger.error(f"Failed to enable MCP service: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update MCP service status"
        )


@router.post("/disable")
async def disable_mcp_service(
    payload: DisableMcpServiceRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Disable an MCP service by ID."""
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        await update_mcp_service_enabled(
            tenant_id=tenant_id,
            user_id=user_id,
            mcp_id=payload.mcp_id,
            enabled=False,
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success"}
        )
    except McpNotFoundError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except McpValidationError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to disable MCP service: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update MCP service status"
        )


# ---------------------------------------------------------------------------
# Image Upload Endpoint
# ---------------------------------------------------------------------------

if ENABLE_UPLOAD_IMAGE:
    @router.post("/upload-image")
    async def upload_mcp_image(
        file: UploadFile = File(..., description="Docker image tar file"),
        port: int = Form(..., ge=1, le=65535,
                         description="Host port to expose the MCP server on (1-65535)"),
        service_name: Optional[str] = Form(
            None, description="Name for the MCP service (auto-generated if not provided)"),
        env_vars: Optional[str] = Form(
            None, description="Environment variables as JSON string"),
        tenant_id: Optional[str] = Form(
            None, description="Tenant ID for filtering (uses auth if not provided)"),
        authorization: Optional[str] = Header(None),
        http_request: Request = None
    ):
        """
        Upload Docker image tar file and start MCP container.

        Container naming: {filename-without-extension}-{tenant-id[:8]}-{user-id[:8]}
        """
        try:
            user_id, auth_tenant_id, _ = get_current_user_info(
                authorization, http_request)
            effective_tenant_id = tenant_id or auth_tenant_id

            content = await file.read()

            result = await upload_and_start_mcp_image(
                tenant_id=effective_tenant_id,
                user_id=user_id,
                file_content=content,
                filename=file.filename,
                port=port,
                service_name=service_name,
                env_vars=env_vars,
            )

            return JSONResponse(status_code=HTTPStatus.OK, content=result)

        except ValueError as e:
            logger.error(f"Validation error: {e}")
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
        except MCPNameIllegal as e:
            logger.error(f"MCP name conflict: {e}")
            raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=str(e))
        except MCPContainerError as e:
            logger.error(f"Container error: {e}")
            raise HTTPException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail=str(e))
        except Exception as e:
            logger.error(f"Failed to upload and start MCP container: {e}")
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to upload and start MCP container: {str(e)}"
            )
else:
    logger.info(
        "MCP image upload feature is disabled (ENABLE_UPLOAD_IMAGE=false)")
