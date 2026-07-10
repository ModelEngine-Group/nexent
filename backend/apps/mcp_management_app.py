import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from http import HTTPStatus

from consts.exceptions import (
    MCPConnectionError,
    McpNameConflictError,
    McpNotFoundError,
    McpValidationError,
    UnauthorizedError,
)
from consts.model import (
    RegistryListQuery,
    CommunityListRequest,
    CommunityPublishRequest,
    CommunityReviewActionRequest,
    CommunityReviewListRequest,
    CommunityUpdateRequest,
)
from services.mcp_management_service import (
    list_community_mcp_services,
    list_community_mcp_tag_stats,
    approve_community_mcp_service,
    list_community_mcp_review_services,
    list_my_community_mcp_services,
    list_registry_mcp_services,
    publish_community_mcp_service,
    reject_community_mcp_service,
    update_community_mcp_service,
    delete_community_mcp_service,
)
from database.market_mcp_db import increment_mcp_market_download_count
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
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        data = await list_community_mcp_services(
            tenant_id=tenant_id,
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
        _, tenant_id, _ = get_current_user_info(authorization, http_request)
        stats = list_community_mcp_tag_stats(tenant_id=tenant_id)
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


@router.get("/community/review/list")
async def list_community_mcp_review_services_api(
    query: CommunityReviewListRequest = Depends(),
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    """
    List MCP community submissions for administrator review.
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        data = await list_community_mcp_review_services(
            tenant_id=tenant_id,
            user_id=user_id,
            status=query.status,
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
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to list MCP community review services: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to list MCP community review services"
        )


@router.post("/community/review/approve")
async def approve_community_mcp_service_api(
    payload: CommunityReviewActionRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    """
    Approve an MCP community submission.
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        await approve_community_mcp_service(
            tenant_id=tenant_id,
            user_id=user_id,
            review_id=payload.review_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content={"status": "success"})
    except McpNotFoundError as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc))
    except UnauthorizedError as exc:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to approve MCP community service: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to approve MCP community service"
        )


@router.post("/community/review/reject")
async def reject_community_mcp_service_api(
    payload: CommunityReviewActionRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    """
    Reject an MCP community submission.
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        await reject_community_mcp_service(
            tenant_id=tenant_id,
            user_id=user_id,
            review_id=payload.review_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content={"status": "success"})
    except McpNotFoundError as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc))
    except UnauthorizedError as exc:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to reject MCP community service: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to reject MCP community service"
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
        review_id = await publish_community_mcp_service(
            tenant_id=tenant_id,
            user_id=user_id,
            mcp_id=payload.mcp_id,
            name=payload.name,
            description=payload.description,
            tags=payload.tags,
            mcp_server=payload.mcp_server,
            config_json=payload.config_json,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": {"review_id": review_id}},
        )
    except McpNotFoundError as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc))
    except McpValidationError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
    except McpNameConflictError as exc:
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
            market_id=payload.market_id,
            name=payload.name,
            description=payload.description,
            tags=payload.tags,
            registry_json=payload.registry_json,
            mcp_server=payload.mcp_server,
            config_json=payload.config_json,
            transport_type=payload.transport_type,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success"},
        )
    except McpNotFoundError as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc))
    except McpValidationError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
    except McpNameConflictError as exc:
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
    market_id: int = Query(gt=0),
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    """
    Delete a market MCP service.
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        await delete_community_mcp_service(
            tenant_id=tenant_id,
            user_id=user_id,
            market_id=market_id,
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
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)
        data = await list_my_community_mcp_services(
            tenant_id=tenant_id,
            user_id=user_id,
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
        logger.error(f"Failed to list my MCP community services: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to list my MCP community services"
        )


@router.post("/community/{market_id}/download")
async def increment_community_mcp_download_count_api(
    market_id: int,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
):
    """Increment the download counter when a user installs a community MCP."""
    try:
        get_current_user_info(authorization, http_request)
        increment_mcp_market_download_count(market_id)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": None},
        )
    except UnauthorizedError as exc:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except Exception as exc:
        logger.error(f"Failed to increment download count: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to increment download count",
        )
