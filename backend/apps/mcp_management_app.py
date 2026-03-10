import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from http import HTTPStatus

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


@router.post("/add")
async def add_mcp_service_api(
    payload: dict,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        name = (payload.get("name") or "").strip()
        server_url = (payload.get("server_url") or "").strip()
        description = payload.get("description")
        source = payload.get("source") or "本地"
        server_type = payload.get("server_type") or "HTTP"
        tags = payload.get("tags")
        authorization_token = (payload.get("authorization_token") or "").strip() or None
        container_config = payload.get("container_config")

        if not name or not server_url:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="Missing required fields",
            )

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
    payload: dict,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        current_name = payload.get("current_name")
        new_name = payload.get("name")
        description = payload.get("description")
        server_url = payload.get("server_url")
        tags = payload.get("tags")
        authorization_token = (payload.get("authorization_token") or "").strip() or None

        if not current_name or not new_name or not server_url:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="Missing required fields",
            )

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
    payload: dict,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        name = payload.get("name")
        enabled = payload.get("enabled")
        if name is None or enabled is None:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="Missing required fields",
            )

        update_mcp_service_enabled(
            tenant_id=tenant_id,
            user_id=user_id,
            name=name,
            enabled=bool(enabled),
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
    payload: dict,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        name = payload.get("name")
        server_url = payload.get("server_url")
        if not name or not server_url:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="Missing required fields",
            )

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
    name: str,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        if not name:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="Missing required fields",
            )

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
