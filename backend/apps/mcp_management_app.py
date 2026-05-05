import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from http import HTTPStatus

from consts.exceptions import (
    MCPConnectionError,
    McpNotFoundError,
    McpValidationError,
    UnauthorizedError,
)
from consts.model import (
    RegistryListQuery,
    CommunityListRequest,
    CommunityPublishRequest,
    CommunityUpdateRequest,
)
from services.mcp_management_service import (
    list_community_mcp_services,
    list_community_mcp_tag_stats,
    list_my_community_mcp_services,
    list_registry_mcp_services,
    publish_community_mcp_service,
    update_community_mcp_service,
    delete_community_mcp_service,
)
from utils.auth_utils import get_current_user_info

router = APIRouter(prefix="/mcp-tools")
logger = logging.getLogger("mcp_management_app")


# ---------------------------------------------------------------------------
# Registry Endpoints (MCP Registry - external service)
# ---------------------------------------------------------------------------

@router.get("/registry/list")
async def list_registry_mcp_services_api(
    query: RegistryListQuery = Depends(),
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    """
    List MCP services from the official MCP Registry.
    """
    try:
        get_current_user_info(authorization, http_request)

        data = await list_registry_mcp_services(
            search=query.search,
            include_deleted=query.include_deleted,
            updated_since=query.updated_since,
            version=query.version,
            cursor=query.cursor,
            limit=query.limit,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content=data,
        )
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to list MCP registry services: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to list MCP registry services"
        )


# ---------------------------------------------------------------------------
# Community Endpoints
# ---------------------------------------------------------------------------

@router.get("/community/list")
async def list_community_mcp_services_api(
    query: CommunityListRequest = Depends(),
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    """
    List public community MCP services.
    """
    try:
        get_current_user_info(authorization, http_request)
        data = await list_community_mcp_services(
            search=query.search,
            tag=query.tag,
            transport_type=query.transport_type,
            cursor=query.cursor,
            limit=query.limit,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": data},
        )
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to list MCP community services: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to list MCP community services"
        )


@router.get("/community/tags/stats")
async def list_community_mcp_tag_stats_api(
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    """
    Get community MCP tag statistics.
    """
    try:
        get_current_user_info(authorization, http_request)
        stats = list_community_mcp_tag_stats()
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": stats},
        )
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to list community MCP tag stats: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to list community MCP tag stats"
        )


@router.post("/community/publish")
async def publish_community_mcp_service_api(
    payload: CommunityPublishRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    """
    Publish a local MCP service to the community.
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        community_id = await publish_community_mcp_service(
            tenant_id=tenant_id,
            user_id=user_id,
            mcp_id=payload.mcp_id,
            name=payload.name,
            description=payload.description,
            version=payload.version,
            tags=payload.tags,
            mcp_server=payload.mcp_server,
            config_json=payload.config_json,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": {"community_id": community_id}},
        )
    except McpNotFoundError as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc))
    except McpValidationError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to publish MCP community service: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to publish MCP community service"
        )


@router.put("/community/update")
async def update_community_mcp_service_api(
    payload: CommunityUpdateRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    """
    Update a community MCP service.
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        await update_community_mcp_service(
            tenant_id=tenant_id,
            user_id=user_id,
            community_id=payload.community_id,
            name=payload.name,
            description=payload.description,
            tags=payload.tags,
            version=payload.version,
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
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to update MCP community service: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update MCP community service"
        )


@router.delete("/community/delete")
async def delete_community_mcp_service_api(
    community_id: int = Query(gt=0),
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    """
    Delete a community MCP service.
    """
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
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to delete MCP community service: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to delete MCP community service"
        )


@router.get("/community/mine")
async def list_my_community_mcp_services_api(
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    """
    List MCP services published by the current user to the community.
    """
    try:
        _, tenant_id, _ = get_current_user_info(authorization, http_request)
        data = await list_my_community_mcp_services(tenant_id=tenant_id)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": data},
        )
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to list my MCP community services: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to list my MCP community services"
        )
