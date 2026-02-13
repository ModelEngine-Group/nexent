import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, UploadFile, File, Form, Query, Request
from fastapi.responses import JSONResponse
from http import HTTPStatus

from consts.const import NEXENT_MCP_DOCKER_IMAGE, ENABLE_UPLOAD_IMAGE
from consts.exceptions import MCPConnectionError, MCPNameIllegal, MCPContainerError
from consts.model import MCPConfigRequest, MCPUpdateRequest
from services.remote_mcp_service import (
    add_remote_mcp_server_list,
    delete_remote_mcp_server_list,
    get_remote_mcp_server_list,
    check_mcp_health_and_update_db,
    delete_mcp_by_container_id,
    upload_and_start_mcp_image,
    update_remote_mcp_server_list,
    attach_mcp_container_permissions,
)
from database.remote_mcp_db import check_mcp_name_exists
from services.tool_configuration_service import get_tool_from_remote_mcp_server
from services.mcp_container_service import MCPContainerManager
from utils.auth_utils import get_current_user_info

router = APIRouter(prefix="/mcp")
logger = logging.getLogger("remote_mcp_app")


@router.post("/tools")
async def get_tools_from_remote_mcp(
    service_name: str,
    mcp_url: str
):
    """ Used to list tool information from the remote MCP server """
    try:
        tools_info = await get_tool_from_remote_mcp_server(mcp_server_name=service_name, remote_mcp_server=mcp_url)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "tools": [tool.__dict__ for tool in tools_info], "status": "success"}
        )
    except MCPConnectionError as e:
        logger.error(f"Failed to get tools from remote MCP server: {e}")
        raise HTTPException(status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                            detail="MCP connection failed")
    except Exception as e:
        logger.error(f"get tools from remote MCP server failed, error: {e}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Failed to get tools from remote MCP server.")


@router.post("/add")
async def add_remote_proxies(
    mcp_url: str,
    service_name: str,
    tenant_id: Optional[str] = Query(
        None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """ Used to add a remote MCP server """
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(authorization, http_request)
        # Use explicit tenant_id if provided, otherwise fall back to auth tenant_id
        effective_tenant_id = tenant_id or auth_tenant_id
        await add_remote_mcp_server_list(tenant_id=effective_tenant_id,
                                         user_id=user_id,
                                         remote_mcp_server=mcp_url,
                                         remote_mcp_server_name=service_name,
                                         container_id=None)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "Successfully added remote MCP proxy",
                     "status": "success"}
        )

    except MCPNameIllegal as e:
        logger.error(f"Failed to add remote MCP proxy: {e}")
        raise HTTPException(status_code=HTTPStatus.CONFLICT,
                            detail="MCP name already exists")
    except MCPConnectionError as e:
        logger.error(f"Failed to add remote MCP proxy: {e}")
        raise HTTPException(status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                            detail="MCP connection failed")
    except Exception as e:
        logger.error(f"Failed to add remote MCP proxy: {e}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Failed to add remote MCP proxy")


@router.delete("")
async def delete_remote_proxies(
    service_name: str,
    mcp_url: str,
    tenant_id: Optional[str] = Query(
        None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """ Used to delete a remote MCP server """
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(authorization, http_request)
        # Use explicit tenant_id if provided, otherwise fall back to auth tenant_id
        effective_tenant_id = tenant_id or auth_tenant_id
        await delete_remote_mcp_server_list(tenant_id=effective_tenant_id,
                                            user_id=user_id,
                                            remote_mcp_server=mcp_url,
                                            remote_mcp_server_name=service_name)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "Successfully deleted remote MCP proxy",
                     "status": "success"}
        )
    except Exception as e:
        logger.error(f"Failed to delete remote MCP proxy: {e}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Failed to delete remote MCP proxy")


@router.put("/update")
async def update_remote_proxy(
    update_data: MCPUpdateRequest,
    tenant_id: Optional[str] = Query(
        None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """ Used to update an existing remote MCP server """
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(authorization, http_request)
        # Use explicit tenant_id if provided, otherwise fall back to auth tenant_id
        effective_tenant_id = tenant_id or auth_tenant_id
        await update_remote_mcp_server_list(
            update_data=update_data,
            tenant_id=effective_tenant_id,
            user_id=user_id
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "Successfully updated remote MCP proxy",
                     "status": "success"}
        )
    except MCPNameIllegal as e:
        logger.error(f"Failed to update remote MCP proxy: {e}")
        raise HTTPException(status_code=HTTPStatus.CONFLICT,
                            detail=str(e))
    except MCPConnectionError as e:
        logger.error(f"Failed to update remote MCP proxy: {e}")
        raise HTTPException(status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                            detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update remote MCP proxy: {e}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Failed to update remote MCP proxy")


@router.get("/list")
async def get_remote_proxies(
    tenant_id: Optional[str] = Query(
        None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """ Used to get the list of remote MCP servers """
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(authorization, http_request)
        # Use explicit tenant_id if provided, otherwise fall back to auth tenant_id
        effective_tenant_id = tenant_id or auth_tenant_id
        remote_mcp_server_list = await get_remote_mcp_server_list(
            tenant_id=effective_tenant_id,
            user_id=user_id,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"remote_mcp_server_list": remote_mcp_server_list,
                     "enable_upload_image": ENABLE_UPLOAD_IMAGE,
                     "status": "success"}
        )
    except Exception as e:
        logger.error(f"Failed to get remote MCP proxy: {e}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Failed to get remote MCP proxy")


@router.get("/healthcheck")
async def check_mcp_health(
    mcp_url: str,
    service_name: str,
    tenant_id: Optional[str] = Query(
        None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """ Used to check the health of the MCP server, the front end can call it,
    and automatically update the database status """
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(authorization, http_request)
        # Use explicit tenant_id if provided, otherwise fall back to auth tenant_id
        effective_tenant_id = tenant_id or auth_tenant_id
        await check_mcp_health_and_update_db(mcp_url, service_name, effective_tenant_id, user_id)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success"}
        )
    except MCPConnectionError as e:
        logger.error(f"MCP connection failed: {e}")
        raise HTTPException(status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                            detail="MCP connection failed")
    except Exception as e:
        logger.error(f"Failed to check the health of the MCP server: {e}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Failed to check the health of the MCP server")


@router.post("/add-from-config")
async def add_mcp_from_config(
    mcp_config: MCPConfigRequest,
    tenant_id: Optional[str] = Query(
        None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """
    Add MCP server by starting a container with command+args config.
    Similar to Cursor's MCP server configuration format.

    Example request:
    {
        "mcpServers": {
            "12306-mcp": {
                "command": "npx",
                "args": ["-y", "12306-mcp"],
                "env": {"NODE_ENV": "production"}
            }
        }
    }
    """
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(authorization, http_request)
        # Use explicit tenant_id if provided, otherwise fall back to auth tenant_id
        effective_tenant_id = tenant_id or auth_tenant_id

        # Initialize container manager
        try:
            container_manager = MCPContainerManager()
        except MCPContainerError as e:
            logger.error(f"Failed to initialize container manager: {e}")
            raise HTTPException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                detail="Docker service unavailable. Please ensure Docker socket is mounted."
            )

        results = []
        errors = []

        for service_name, config in mcp_config.mcpServers.items():
            try:
                command = config.command
                args = config.args or []
                env_vars = config.env or {}
                port = config.port

                if not command:
                    errors.append(f"{service_name}: command is required")
                    continue

                if port is None:
                    errors.append(f"{service_name}: port is required")
                    continue

                # Check if MCP service name already exists before starting container
                if check_mcp_name_exists(mcp_name=service_name, tenant_id=effective_tenant_id):
                    errors.append(f"{service_name}: MCP name already exists")
                    continue

                # Build full command to run inside nexent/nexent-mcp image
                full_command = [
                    "python",
                    "-m",
                    "mcp_proxy",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    str(port),
                    "--transport",
                    "streamablehttp",
                    "--",
                    command,
                    *args,
                ]

                # Start container
                container_info = await container_manager.start_mcp_container(
                    service_name=service_name,
                    tenant_id=effective_tenant_id,
                    user_id=user_id,
                    env_vars=env_vars,
                    host_port=port,
                    image=config.image or NEXENT_MCP_DOCKER_IMAGE,
                    full_command=full_command,
                )

                # Register to remote MCP server list
                await add_remote_mcp_server_list(
                    tenant_id=effective_tenant_id,
                    user_id=user_id,
                    remote_mcp_server=container_info["mcp_url"],
                    remote_mcp_server_name=service_name,
                    container_id=container_info["container_id"],
                )

                results.append({
                    "service_name": service_name,
                    "status": "success",
                    "mcp_url": container_info["mcp_url"],
                    "container_id": container_info["container_id"],
                    "container_name": container_info.get("container_name"),
                    "host_port": container_info.get("host_port")
                })

            except MCPContainerError as e:
                logger.error(
                    f"Failed to start MCP container {service_name}: {e}")
                errors.append(f"{service_name}: {str(e)}")
            except Exception as e:
                logger.error(
                    f"Unexpected error adding MCP {service_name}: {e}")
                errors.append(f"{service_name}: {str(e)}")

        if errors and not results:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail=f"All MCP servers failed: {errors}"
            )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "MCP servers processed",
                "results": results,
                "errors": errors if errors else None,
                "status": "success"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add MCP from config: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to add MCP servers: {str(e)}"
        )


@router.delete("/container/{container_id}")
async def stop_mcp_container(
    container_id: str,
    tenant_id: Optional[str] = Query(
        None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """ Stop and remove MCP container """
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(authorization, http_request)
        # Use explicit tenant_id if provided, otherwise fall back to auth tenant_id
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
            # Soft delete the corresponding MCP record (if any) by container ID
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


@router.get("/containers")
async def list_mcp_containers(
    tenant_id: Optional[str] = Query(
        None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """ List all MCP containers for the current tenant """
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(authorization, http_request)
        # Use explicit tenant_id if provided, otherwise fall back to auth tenant_id
        effective_tenant_id = tenant_id or auth_tenant_id

        try:
            container_manager = MCPContainerManager()
        except MCPContainerError as e:
            logger.error(f"Failed to initialize container manager: {e}")
            raise HTTPException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                detail="Docker service unavailable"
            )

        containers = container_manager.list_mcp_containers(tenant_id=effective_tenant_id)
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
    tenant_id: Optional[str] = Query(
        None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """ Get logs from MCP container """
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(authorization, http_request)
        # Use explicit tenant_id if provided, otherwise fall back to auth tenant_id
        effective_tenant_id = tenant_id or auth_tenant_id

        try:
            container_manager = MCPContainerManager()
        except MCPContainerError as e:
            logger.error(f"Failed to initialize container manager: {e}")
            raise HTTPException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                detail="Docker service unavailable"
            )

        logs = container_manager.get_container_logs(container_id, tail=tail)

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "logs": logs,
                "status": "success"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get container logs: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to get container logs: {str(e)}"
        )


# Conditionally add upload-image route based on ENABLE_UPLOAD_IMAGE setting
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
            user_id, auth_tenant_id, _ = get_current_user_info(authorization, http_request)
            # Use explicit tenant_id if provided, otherwise fall back to auth tenant_id
            effective_tenant_id = tenant_id or auth_tenant_id

            # Read file content
            content = await file.read()

            # Call service layer to handle the business logic
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
