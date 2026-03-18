import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from http import HTTPStatus
from pydantic import BaseModel, Field

from consts.exceptions import MCPConnectionError, MCPNameIllegal
from services.mcp_management_service import (
    add_mcp_service,
    check_mcp_service_health,
    delete_mcp_service,
    list_market_mcp_services,
    list_mcp_services,
    update_mcp_service,
    update_mcp_service_enabled,
)
from utils.auth_utils import get_current_user_info

router = APIRouter(prefix="/mcp-tools")
logger = logging.getLogger("mcp_management_app")


class AddMcpServiceRequest(BaseModel):
    name: str = Field(min_length=1)
    server_url: str = Field(min_length=1)
    description: Optional[str] = None
    source: Literal["local", "market"] = "local"
    server_type: Literal["http", "sse", "container"] = "http"
    tags: Optional[list[str]] = None
    authorization_token: Optional[str] = None
    container_config: Optional[dict[str, Any]] = None


class UpdateMcpServiceRequest(BaseModel):
    current_name: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: Optional[str] = None
    server_url: str = Field(min_length=1)
    tags: Optional[list[str]] = None
    authorization_token: Optional[str] = None


class EnableMcpServiceRequest(BaseModel):
    name: str = Field(min_length=1)
    enabled: bool


class HealthcheckMcpServiceRequest(BaseModel):
    name: str = Field(min_length=1)
    server_url: str = Field(min_length=1)


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
        server_type = payload.server_type
        tags = payload.tags
        authorization_token = (payload.authorization_token or "").strip() or None
        container_config = payload.container_config

        await add_mcp_service(
            tenant_id=tenant_id,
            user_id=user_id,
            name=name,
            description=description,
            source=source,
            server_type=server_type,
            server_url=server_url,
            tags=tags,
            authorization_token=authorization_token,
            container_config=container_config,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success"},
        )
    except MCPNameIllegal as exc:
        logger.error(f"MCP name conflict: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail=str(exc),
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


@router.get("/market/list")
async def list_market_mcp_services_api(
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

        market_data = await list_market_mcp_services(
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
            content={"status": "success", "data": market_data},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to list market MCP services: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to list market MCP services",
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
        authorization_token = (payload.authorization_token or "").strip() or None

        update_mcp_service(
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

        update_mcp_service_enabled(
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


@router.post("/healthcheck")
async def check_mcp_health_api(
    payload: HealthcheckMcpServiceRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        name = payload.name
        server_url = payload.server_url

        health_status = await check_mcp_service_health(
            tenant_id=tenant_id,
            user_id=user_id,
            name=name,
            server_url=server_url,
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


@router.delete("/delete")
async def delete_mcp_service_api(
    name: str = Query(min_length=1),
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        delete_mcp_service(
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
