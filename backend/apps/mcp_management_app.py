import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from http import HTTPStatus
from pydantic import BaseModel, Field

from consts.const import NEXENT_MCP_DOCKER_IMAGE
from consts.exceptions import MCPConnectionError, MCPContainerError
from consts.model import MCPConfigRequest
from database.remote_mcp_db import check_mcp_name_exists
from services.mcp_container_service import MCPContainerManager
from services.mcp_management_service import (
    add_mcp_service,
    check_mcp_service_health,
    check_mcp_service_health_legacy,
    delete_mcp_service,
    delete_mcp_service_legacy,
    list_registry_mcp_services,
    list_mcp_service_tools_by_id,
    list_mcp_services,
    update_mcp_service,
    update_mcp_service_legacy,
    update_mcp_service_enabled,
    update_mcp_service_enabled_legacy,
)
from utils.auth_utils import get_current_user_info

router = APIRouter(prefix="/mcp-tools")
logger = logging.getLogger("mcp_management_app")


class AddMcpServiceRequest(BaseModel):
    name: str = Field(min_length=1)
    server_url: str = Field(min_length=1)
    description: Optional[str] = None
    source: Literal["local", "mcp_registry", "market"] = "local"
    transport_type: Literal["http", "sse", "stdio", "container"] = "http"
    tags: Optional[list[str]] = None
    authorization_token: Optional[str] = None
    container_config: Optional[dict[str, Any]] = None
    version: Optional[str] = None
    registry_json: Optional[dict[str, Any]] = None


class AddContainerMcpServiceRequest(BaseModel):
    name: str = Field(min_length=1)
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    authorization_token: Optional[str] = None
    port: int = Field(..., ge=1, le=65535)
    mcp_config: MCPConfigRequest


class UpdateMcpServiceRequest(BaseModel):
    current_name: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: Optional[str] = None
    server_url: str = Field(min_length=1)
    tags: Optional[list[str]] = None
    authorization_token: Optional[str] = None


class UpdateMcpServiceByIdRequest(BaseModel):
    mcp_id: int
    name: str = Field(min_length=1)
    description: Optional[str] = None
    server_url: str = Field(min_length=1)
    tags: Optional[list[str]] = None
    authorization_token: Optional[str] = None


class EnableMcpServiceRequest(BaseModel):
    name: str = Field(min_length=1)
    enabled: bool


class EnableMcpServiceByIdRequest(BaseModel):
    mcp_id: int


class DisableMcpServiceByIdRequest(BaseModel):
    mcp_id: int


class HealthcheckMcpServiceRequest(BaseModel):
    name: str = Field(min_length=1)
    server_url: str = Field(min_length=1)


class HealthcheckMcpServiceByIdRequest(BaseModel):
    mcp_id: int


class ListMcpToolsByIdRequest(BaseModel):
    mcp_id: int


@router.post("/add")
async def add_mcp_service_api(
    payload: AddMcpServiceRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        name = payload.name.strip()
        server_url = payload.server_url.strip()
        description = payload.description
        source = payload.source
        transport_type = payload.transport_type
        tags = payload.tags
        authorization_token = (payload.authorization_token or "").strip()
        container_config = payload.container_config
        version = (payload.version or "").strip()
        registry_json = payload.registry_json

        await add_mcp_service(
            tenant_id=tenant_id,
            user_id=user_id,
            name=name,
            description=description,
            source=source,
            transport_type=transport_type,
            server_url=server_url,
            tags=tags,
            authorization_token=authorization_token,
            container_config=container_config,
            version=version,
            registry_json=registry_json,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success"},
        )
    except MCPConnectionError as exc:
        logger.error(f"MCP connection failed when adding service: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            detail="MCP connection failed",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to add MCP service: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to add MCP service",
        )


@router.post("/container/add")
async def add_container_mcp_service_api(
    payload: AddContainerMcpServiceRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        service_name = payload.name.strip()
        if check_mcp_name_exists(mcp_name=service_name, tenant_id=tenant_id):
            raise HTTPException(
                status_code=HTTPStatus.CONFLICT,
                detail="MCP name already exists",
            )

        servers = payload.mcp_config.mcpServers
        if len(servers) != 1:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="Exactly one mcpServers entry is required",
            )

        _, config = next(iter(servers.items()))
        command = (config.command or "").strip()
        if not command:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="command is required",
            )

        port = payload.port

        env_vars = dict(config.env or {})
        auth_token = (payload.authorization_token or "").strip()
        if auth_token:
            env_vars["authorization_token"] = auth_token

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
            *(config.args or []),
        ]

        container_manager = MCPContainerManager()
        container_info = await container_manager.start_mcp_container(
            service_name=service_name,
            tenant_id=tenant_id,
            user_id=user_id,
            env_vars=env_vars,
            host_port=port,
            image=config.image or NEXENT_MCP_DOCKER_IMAGE,
            full_command=full_command,
        )
        started_container_id: Optional[str] = None
        started_container_id = container_info.get("container_id")

        container_config = payload.mcp_config.model_dump()

        try:
            await add_mcp_service(
                tenant_id=tenant_id,
                user_id=user_id,
                name=service_name,
                description=payload.description,
                source="local",
                transport_type="stdio",
                server_url=container_info["mcp_url"],
                tags=payload.tags,
                authorization_token=auth_token,
                container_config=container_config,
                version=None,
                registry_json=None,
                enabled=True,
                container_id=container_info.get("container_id"),
            )
        except MCPConnectionError:
            if started_container_id:
                try:
                    cleanup_manager = MCPContainerManager()
                    await cleanup_manager.stop_mcp_container(started_container_id)
                except Exception as cleanup_exc:
                    logger.warning(f"Failed to cleanup container {started_container_id}: {cleanup_exc}")
            raise

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "status": "success",
                "data": {
                    "service_name": service_name,
                    "mcp_url": container_info.get("mcp_url"),
                    "container_id": container_info.get("container_id"),
                    "container_name": container_info.get("container_name"),
                    "host_port": container_info.get("host_port"),
                },
            },
        )
    except HTTPException:
        raise
    except MCPContainerError as exc:
        logger.error(f"Failed to start MCP container service: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            detail="Docker service unavailable",
        )
    except MCPConnectionError as exc:
        logger.error(f"MCP connection failed when adding container service: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            detail="MCP connection failed",
        )
    except Exception as exc:
        logger.error(f"Failed to add container MCP service: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to add container MCP service",
        )


@router.get("/list")
async def list_mcp_services_api(
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        _, tenant_id, _ = get_current_user_info(authorization, http_request)
        services = list_mcp_services(tenant_id=tenant_id)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": services},
        )
    except Exception as exc:
        logger.error(f"Failed to list MCP services: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to list MCP services",
        )


@router.get("/registry/list")
async def list_registry_mcp_services_api(
    search: Optional[str] = None,
    include_deleted: bool = False,
    updated_since: Optional[str] = None,
    version: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = 30,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        # Keep auth behavior consistent with other mcp-tools APIs.
        get_current_user_info(authorization, http_request)

        data = await list_registry_mcp_services(
            search=(search or "").strip() or None,
            include_deleted=bool(include_deleted),
            updated_since=(updated_since or "").strip() or None,
            version=(version or "").strip() or None,
            cursor=(cursor or "").strip() or None,
            # Registry currently validates limit <= 100.
            limit=max(1, min(limit, 100)),
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": data},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to list MCP registry MCP services: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to list MCP registry MCP services",
        )


@router.post("/tools")
async def list_mcp_tools_api(
    payload: ListMcpToolsByIdRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        _, tenant_id, _ = get_current_user_info(authorization, http_request)
        tools = await list_mcp_service_tools_by_id(
            tenant_id=tenant_id,
            mcp_id=payload.mcp_id,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "tools": tools},
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc),
        )
    except MCPConnectionError as exc:
        logger.error(f"Failed to get tools from MCP service: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            detail="MCP connection failed",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to list MCP tools by id: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to get tools from MCP service",
        )


@router.put("/update")
async def update_mcp_service_api(
    payload: UpdateMcpServiceRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        current_name = payload.current_name
        new_name = payload.name
        description = payload.description
        server_url = payload.server_url
        tags = payload.tags
        authorization_token = (payload.authorization_token or "").strip()

        update_mcp_service_legacy(
            tenant_id=tenant_id,
            user_id=user_id,
            current_name=current_name,
            new_name=new_name,
            description=description,
            server_url=server_url,
            authorization_token=authorization_token,
            tags=tags,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to update MCP service: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update MCP service",
        )


@router.put("/v2/update")
async def update_mcp_service_by_id_api(
    payload: UpdateMcpServiceByIdRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        update_mcp_service(
            tenant_id=tenant_id,
            user_id=user_id,
            mcp_id=payload.mcp_id,
            new_name=payload.name,
            description=payload.description,
            server_url=payload.server_url,
            authorization_token=(payload.authorization_token or "").strip(),
            tags=payload.tags,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to update MCP service by id: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update MCP service",
        )


@router.post("/manage/enable")
async def update_mcp_service_enable_api(
    payload: EnableMcpServiceRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        name = payload.name
        enabled = payload.enabled

        update_mcp_service_enabled_legacy(
            tenant_id=tenant_id,
            user_id=user_id,
            name=name,
            enabled=enabled,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to update MCP service status: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update MCP service status",
        )


@router.post("/v2/manage/enable")
async def update_mcp_service_enable_by_id_api(
    payload: EnableMcpServiceByIdRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    # Backward-compatible route. Prefer /enable or /disable.
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
            content={"status": "success"},
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc),
        )
    except MCPConnectionError as exc:
        logger.error(f"MCP connection failed while enabling service by id: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            detail="MCP connection failed",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to enable MCP service by id: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update MCP service status",
        )


@router.post("/enable")
async def enable_mcp_service_by_id_api(
    payload: EnableMcpServiceByIdRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
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
            content={"status": "success"},
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc),
        )
    except MCPConnectionError as exc:
        logger.error(f"MCP connection failed while enabling service by id: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            detail="MCP connection failed",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to enable MCP service by id: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update MCP service status",
        )


@router.post("/disable")
async def disable_mcp_service_by_id_api(
    payload: DisableMcpServiceByIdRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
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
            content={"status": "success"},
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to disable MCP service by id: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update MCP service status",
        )


@router.post("/healthcheck")
async def check_mcp_health_api(
    payload: HealthcheckMcpServiceRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        health_status = await check_mcp_service_health_legacy(
            tenant_id=tenant_id,
            user_id=user_id,
            name=payload.name,
            server_url=payload.server_url,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": {"health_status": health_status}},
        )
    except MCPConnectionError as exc:
        logger.error(f"MCP connection failed: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            detail="MCP connection failed",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to check MCP health: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to check MCP health",
        )


@router.post("/v2/healthcheck")
async def check_mcp_health_by_id_api(
    payload: HealthcheckMcpServiceByIdRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        health_status = await check_mcp_service_health(
            tenant_id=tenant_id,
            user_id=user_id,
            mcp_id=payload.mcp_id,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": {"health_status": health_status}},
        )
    except MCPConnectionError as exc:
        logger.error(f"MCP connection failed: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            detail="MCP connection failed",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to check MCP health by id: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to check MCP health",
        )


@router.delete("/delete")
async def delete_mcp_service_api(
    name: str = Query(min_length=1),
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        delete_mcp_service_legacy(
            tenant_id=tenant_id,
            user_id=user_id,
            name=name,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to delete MCP service: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to delete MCP service",
        )


@router.delete("/v2/delete")
async def delete_mcp_service_by_id_api(
    mcp_id: int = Query(gt=0),
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        await delete_mcp_service(
            tenant_id=tenant_id,
            user_id=user_id,
            mcp_id=mcp_id,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to delete MCP service by id: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to delete MCP service",
        )
