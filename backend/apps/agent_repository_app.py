import logging
from http import HTTPStatus
from typing import Annotated, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from starlette.responses import JSONResponse

from consts.exceptions import SkillDuplicateError, UnauthorizedError
from consts.model import AgentRepositoryListingCreateRequest
from services.agent_repository_service import (
    check_repository_import_precheck_impl,
    create_agent_repository_listing_impl,
    get_agent_repository_listing_detail_impl,
    import_agent_from_repository_impl,
    list_agent_repository_listings_impl,
    list_my_editable_agents_impl,
    update_agent_repository_status_impl,
)
from utils.auth_utils import get_current_user_id

logger = logging.getLogger(__name__)
agent_repository_router = APIRouter(prefix="/repository/agent")


@agent_repository_router.get("")
async def list_agent_repository_listings_api(
    status: Optional[str] = Query(None, description="Filter by listing status"),
    agent_id: Optional[int] = Query(None, description="Filter by source agent ID"),
    page: Annotated[int, Query(ge=1, description="Page number starting from 1")] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=100, description="Page size from 1 to 100")
    ] = 10,
    search: Optional[str] = Query(
        None, description="Filter by name, description, author, or tags"
    ),
    authorization: str = Header(None),
):
    """List all marketplace repository listings with optional status filter."""
    try:
        _, tenant_id = get_current_user_id(authorization)
        result = list_agent_repository_listings_impl(
            tenant_id,
            status=status,
            agent_id=agent_id,
            page=page,
            page_size=page_size,
            search=search,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except UnauthorizedError as e:
        logger.warning(
            f"Unauthorized agent repository listings access attempt: {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except ValueError as e:
        logger.warning(
            f"Invalid agent repository listings request parameters: {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))


@agent_repository_router.get("/mine")
async def list_my_editable_agents_api(
    ownership: Optional[str] = Query(
        "all",
        description="Filter by ownership: all / created / others",
    ),
    page: Annotated[int, Query(ge=1, description="Page number starting from 1")] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=100, description="Page size from 1 to 100")
    ] = 10,
    search: Optional[str] = Query(
        None, description="Filter by agent name or description"
    ),
    new_agent_padding: bool = Query(
        False,
        description="Reserve first slot on page 1 for create-agent placeholder",
    ),
    authorization: str = Header(None),
):
    """List editable draft agents for the current user with repository listing info."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = await list_my_editable_agents_impl(
            tenant_id=tenant_id,
            user_id=user_id,
            ownership=ownership or "all",
            page=page,
            page_size=page_size,
            search=search,
            new_agent_padding=new_agent_padding,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except UnauthorizedError as e:
        logger.warning(
            f"Unauthorized my editable agents access attempt: {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except ValueError as e:
        logger.warning(
            f"Invalid my editable agents request parameters (ownership={ownership}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))


@agent_repository_router.get("/{agent_repository_id}")
async def get_agent_repository_listing_detail_api(
    agent_repository_id: int,
    authorization: str = Header(None),
):
    """Get detailed marketplace repository listing by primary key."""
    try:
        _, tenant_id = get_current_user_id(authorization)
        result = get_agent_repository_listing_detail_impl(
            agent_repository_id,
            tenant_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except UnauthorizedError as e:
        logger.warning(
            f"Unauthorized agent repository listing detail access attempt "
            f"(id={agent_repository_id}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except ValueError as e:
        logger.warning(
            f"Agent repository listing not found (id={agent_repository_id}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))


@agent_repository_router.patch("/{agent_repository_id}/status")
async def update_agent_repository_status_api(
    agent_repository_id: int,
    status: str = Body(
        ...,
        embed=True,
        description=(
            "New status: not_shared (未共享) / pending_review (待审核) / "
            "rejected (审核驳回) / shared (已共享)"
        ),
    ),
    authorization: str = Header(None),
):
    """Update marketplace repository listing status (share, unshare, approve, reject)."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = update_agent_repository_status_impl(
            agent_repository_id=agent_repository_id,
            status=status,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except UnauthorizedError as e:
        logger.warning(
            f"Unauthorized agent repository status update attempt "
            f"(id={agent_repository_id}, status={status}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except ValueError as e:
        logger.warning(
            f"Invalid agent repository status update "
            f"(id={agent_repository_id}, status={status}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))


@agent_repository_router.post("/{agent_id}/versions/{version_no}")
async def create_agent_repository_listing_api(
    agent_id: int,
    version_no: int,
    payload: Optional[AgentRepositoryListingCreateRequest] = Body(None),
    authorization: str = Header(None),
):
    """Create or update a marketplace repository listing from an agent version snapshot."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        card_fields = payload.model_dump(exclude_none=True) if payload else None
        result = await create_agent_repository_listing_impl(
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            version_no=version_no,
            card_fields=card_fields,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except UnauthorizedError as e:
        logger.warning(
            f"Unauthorized agent repository listing creation attempt "
            f"(agent_id={agent_id}, version_no={version_no}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except ValueError as e:
        logger.warning(
            f"Invalid agent repository listing creation parameters "
            f"(agent_id={agent_id}, version_no={version_no}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))


@agent_repository_router.get("/{agent_repository_id}/import_precheck")
async def check_repository_import_precheck_api(
    agent_repository_id: int,
    authorization: str = Header(None),
):
    """Precheck import dependencies for a shared marketplace listing."""
    try:
        _, tenant_id = get_current_user_id(authorization)
        result = check_repository_import_precheck_impl(
            agent_repository_id=agent_repository_id,
            tenant_id=tenant_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except UnauthorizedError as e:
        logger.warning(
            f"Unauthorized agent repository import precheck attempt "
            f"(id={agent_repository_id}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except ValueError as e:
        logger.warning(
            f"Agent repository import precheck failed "
            f"(id={agent_repository_id}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))


@agent_repository_router.post("/{agent_repository_id}/import")
async def import_agent_from_repository_api(
    agent_repository_id: int,
    authorization: Optional[str] = Header(None),
):
    """Import an agent tree from a marketplace repository listing into the current tenant."""
    try:
        _, tenant_id = get_current_user_id(authorization)
        await import_agent_from_repository_impl(
            agent_repository_id=agent_repository_id,
            tenant_id=tenant_id,
            authorization=authorization,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content={})
    except UnauthorizedError as e:
        logger.warning(
            f"Unauthorized agent repository import attempt "
            f"(id={agent_repository_id}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except SkillDuplicateError as exc:
        logger.warning(
            f"Skill duplicate on repository import (id={agent_repository_id}): "
            f"{exc.duplicate_names}"
        )
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail={
                "type": "skill_duplicate",
                "duplicate_skills": exc.duplicate_names,
            },
        )
    except ValueError as e:
        logger.warning(
            f"Agent repository listing not found for import "
            f"(id={agent_repository_id}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
