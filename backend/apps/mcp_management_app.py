import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from http import HTTPStatus
from pydantic import BaseModel, Field

from consts.exceptions import (
    MCPConnectionError,
    MCPContainerError,
    McpNameConflictError,
    McpNotFoundError,
    McpValidationError,
)
from consts.model import MCPConfigRequest
from services.mcp_management_service import (
    add_mcp_service,
    add_container_mcp_service,
    check_mcp_service_health,
    delete_mcp_service,
    delete_community_mcp_service,
    list_community_mcp_services,
    list_community_mcp_tag_stats,
    list_my_community_mcp_services,
    list_registry_mcp_services,
    list_mcp_service_tools_by_id,
    list_mcp_services,
    list_mcp_tag_stats,
    publish_community_mcp_service,
    update_mcp_service,
    update_community_mcp_service,
    update_mcp_service_enabled,
)
from utils.auth_utils import get_current_user_info

router = APIRouter(prefix="/mcp-tools")
logger = logging.getLogger("mcp_management_app")


class AddMcpServiceRequest(BaseModel):
    name: str = Field(min_length=1)
    server_url: str = Field(min_length=1)
    description: Optional[str] = None
    source: Literal["local", "mcp_registry", "community", "market"] = "local"
    transport_type: Literal["http", "sse", "stdio", "container"] = "http"
    tags: Optional[list[str]] = None
    authorization_token: Optional[str] = None
    container_config: Optional[dict[str, Any]] = None
    version: Optional[str] = None
    registry_json: Optional[dict[str, Any]] = None


class AddContainerMcpServiceRequest(BaseModel):
    name: str = Field(min_length=1)
    description: Optional[str] = None
    source: Literal["local", "community", "market"] = "local"
    tags: Optional[list[str]] = None
    authorization_token: Optional[str] = None
    registry_json: Optional[dict[str, Any]] = None
    port: int = Field(..., ge=1, le=65535)
    mcp_config: MCPConfigRequest


class UpdateMcpServiceByIdRequest(BaseModel):
    mcp_id: int
    name: str = Field(min_length=1)
    description: Optional[str] = None
    server_url: str = Field(min_length=1)
    tags: Optional[list[str]] = None
    authorization_token: Optional[str] = None


class EnableMcpServiceByIdRequest(BaseModel):
    mcp_id: int


class DisableMcpServiceByIdRequest(BaseModel):
    mcp_id: int


class HealthcheckMcpServiceByIdRequest(BaseModel):
    mcp_id: int


class ListMcpToolsByIdRequest(BaseModel):
    mcp_id: int


class CommunityListRequest(BaseModel):
    search: Optional[str] = None
    tag: Optional[str] = None
    transport_type: Optional[Literal["http", "sse", "stdio"]] = None
    cursor: Optional[str] = None
    limit: int = Field(default=30, ge=1, le=100)


class CommunityPublishRequest(BaseModel):
    mcp_id: int = Field(gt=0)


class CommunityUpdateRequest(BaseModel):
    community_id: int = Field(gt=0)
    name: Optional[str] = Field(default=None, min_length=1)
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    version: Optional[str] = None
    registry_json: Optional[dict[str, Any]] = None


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
    except McpValidationError as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc),
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
        container_info = await add_container_mcp_service(
            tenant_id=tenant_id,
            user_id=user_id,
            name=payload.name,
            description=payload.description,
            source=payload.source,
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
    except McpNameConflictError as exc:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail=str(exc),
        )
    except McpValidationError as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc),
        )
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
    tag: Optional[str] = None,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        _, tenant_id, _ = get_current_user_info(authorization, http_request)
        services = list_mcp_services(tenant_id=tenant_id, tag=(tag or "").strip() or None)
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


@router.get("/tags/stats")
async def list_mcp_tag_stats_api(
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        _, tenant_id, _ = get_current_user_info(authorization, http_request)
        stats = list_mcp_tag_stats(tenant_id=tenant_id)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": stats},
        )
    except Exception as exc:
        logger.error(f"Failed to list MCP tag stats: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to list MCP tag stats",
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
            content=data,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to list MCP registry MCP services: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to list MCP registry MCP services",
        )


@router.post("/community/list")
async def list_community_mcp_services_api(
    payload: CommunityListRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        get_current_user_info(authorization, http_request)
        data = await list_community_mcp_services(
            search=(payload.search or "").strip() or None,
            tag=(payload.tag or "").strip() or None,
            transport_type=(payload.transport_type or "").strip() or None,
            cursor=(payload.cursor or "").strip() or None,
            limit=payload.limit,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": data},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to list MCP community services: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to list MCP community services",
        )


@router.get("/community/tags/stats")
async def list_community_mcp_tag_stats_api(
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        _, tenant_id, _ = get_current_user_info(authorization, http_request)
        stats = list_community_mcp_tag_stats(tenant_id=tenant_id)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": stats},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to list community MCP tag stats: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to list community MCP tag stats",
        )


@router.post("/community/publish")
async def publish_community_mcp_service_api(
    payload: CommunityPublishRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        community_id = await publish_community_mcp_service(
            tenant_id=tenant_id,
            user_id=user_id,
            mcp_id=payload.mcp_id,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": {"community_id": community_id}},
        )
    except McpNotFoundError as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc))
    except McpValidationError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to publish MCP community service: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to publish MCP community service",
        )


@router.put("/community/update")
async def update_community_mcp_service_api(
    payload: CommunityUpdateRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        await update_community_mcp_service(
            tenant_id=tenant_id,
            user_id=user_id,
            community_id=payload.community_id,
            name=(payload.name or "").strip() or None,
            description=payload.description,
            tags=payload.tags,
            version=(payload.version or "").strip() or None,
            registry_json=payload.registry_json,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success"},
        )
    except McpNotFoundError as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc))
    except McpValidationError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to update MCP community service: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update MCP community service",
        )


@router.delete("/community/delete")
async def delete_community_mcp_service_api(
    community_id: int = Query(gt=0),
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        await delete_community_mcp_service(
            tenant_id=tenant_id,
            user_id=user_id,
            community_id=community_id,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success"},
        )
    except McpNotFoundError as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to delete MCP community service: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to delete MCP community service",
        )


@router.get("/community/mine")
async def list_my_community_mcp_services_api(
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        _, tenant_id, _ = get_current_user_info(authorization, http_request)
        data = await list_my_community_mcp_services(tenant_id=tenant_id)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": data},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to list my MCP community services: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to list my MCP community services",
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
    except McpNotFoundError as exc:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc),
        )
    except McpValidationError as exc:
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
    except McpNotFoundError as exc:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc),
        )
    except McpValidationError as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to update MCP service by id: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update MCP service",
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
    except McpNotFoundError as exc:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc),
        )
    except McpNameConflictError as exc:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail=str(exc),
        )
    except McpValidationError as exc:
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
    except McpNotFoundError as exc:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc),
        )
    except McpValidationError as exc:
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
    except McpNotFoundError as exc:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc),
        )
    except McpValidationError as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc),
        )
    except MCPConnectionError as exc:
        logger.error(f"MCP connection failed: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            detail=str(exc) or "MCP connection failed",
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
    except McpNotFoundError as exc:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to delete MCP service by id: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to delete MCP service",
        )
