import logging
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from starlette.responses import JSONResponse

from consts.exceptions import SkillDuplicateError, UnauthorizedError
from consts.model import AgentRepositoryListingCreateRequest
from services.agent_repository_service import (
    create_agent_repository_listing_impl,
    get_agent_repository_listing_detail_impl,
    import_agent_from_repository_impl,
    list_agent_repository_listings_impl,
    list_my_editable_agents_impl,
    update_agent_repository_status_impl,
)
from utils.auth_utils import get_current_user_id

agent_repository_router = APIRouter(prefix="/repository/agent")
logger = logging.getLogger("agent_repository_app")


@agent_repository_router.get("")
async def list_agent_repository_listings_api(
    status: Optional[str] = Query(None, description="Filter by listing status"),
    agent_id: Optional[int] = Query(None, description="Filter by source agent ID"),
    deduplicate_by_agent_id: Optional[bool] = Query(
        None,
        description="Whether to return one listing per agent",
    ),
    category_id: Optional[int] = Query(
        None,
        description="Filter by marketplace category ID",
    ),
    authorization: str = Header(None),
):
    """List all marketplace repository listings with optional status filter."""
    try:
        get_current_user_id(authorization)
        should_deduplicate = (
            agent_id is None
            if deduplicate_by_agent_id is None
            else deduplicate_by_agent_id
        )
        result = list_agent_repository_listings_impl(
            status=status,
            agent_id=agent_id,
            deduplicate_by_agent_id=should_deduplicate,
            category_id=category_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except UnauthorizedError as e:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"List agent repository listings error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="List agent repository listings error.",
        )


@agent_repository_router.get("/mine")
async def list_my_editable_agents_api(
    ownership: Optional[str] = Query(
        "all",
        description="Filter by ownership: all / created / others",
    ),
    authorization: str = Header(None),
):
    """List editable draft agents for the current user with repository listing info."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = list_my_editable_agents_impl(
            tenant_id=tenant_id,
            user_id=user_id,
            ownership=ownership or "all",
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except UnauthorizedError as e:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"List my editable agents error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="List my editable agents error.",
        )


@agent_repository_router.get("/{agent_repository_id}")
async def get_agent_repository_listing_detail_api(
    agent_repository_id: int,
    authorization: str = Header(None),
):
    """Get detailed marketplace repository listing by primary key."""
    try:
        get_current_user_id(authorization)
        result = get_agent_repository_listing_detail_impl(agent_repository_id)
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except UnauthorizedError as e:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Get agent repository listing detail error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Get agent repository listing detail error.",
        )


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
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Update agent repository status error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Update agent repository status error.",
        )


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
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Create agent repository listing error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Create agent repository listing error.",
        )


@agent_repository_router.post("/{agent_repository_id}/import")
async def import_agent_from_repository_api(
    agent_repository_id: int,
    authorization: Optional[str] = Header(None),
):
    """Import an agent tree from a marketplace repository listing into the current tenant."""
    try:
        await import_agent_from_repository_impl(
            agent_repository_id=agent_repository_id,
            authorization=authorization,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content={})
    except UnauthorizedError as e:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except SkillDuplicateError as exc:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail={
                "type": "skill_duplicate",
                "duplicate_skills": exc.duplicate_names,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Import agent from repository error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Import agent from repository error.",
        )
