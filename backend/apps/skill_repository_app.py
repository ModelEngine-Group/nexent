import json
import logging
from http import HTTPStatus
from typing import Annotated, Optional

from consts.exceptions import ForbiddenError, SkillDuplicateError, UnauthorizedError
from consts.model import (
    SkillRepositoryInstallRequest,
    SkillRepositoryListingCreateRequest,
    TagAssignmentFilter,
)
from fastapi import APIRouter, Body, Header, HTTPException, Query
from services.skill_repository_service import (
    count_my_editable_skills_impl,
    create_skill_repository_listing_impl,
    ensure_skill_repository_access,
    get_skill_repository_listing_detail_impl,
    install_skill_from_repository_impl,
    list_my_editable_skills_impl,
    list_skill_repository_listings_impl,
    list_skill_repository_tag_stats_impl,
    update_skill_repository_status_impl,
)
from starlette.responses import JSONResponse
from utils.auth_utils import get_current_user_id

logger = logging.getLogger(__name__)
skill_repository_router = APIRouter(prefix="/repository/skill")


def _parse_tag_predicates(raw: str | None) -> list[TagAssignmentFilter]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("tag_predicates must be valid JSON") from error
    if not isinstance(payload, list):
        raise ValueError("tag_predicates must be a list")
    return [TagAssignmentFilter.model_validate(item) for item in payload]


@skill_repository_router.get("")
async def list_skill_repository_listings_api(
    status: Optional[str] = Query(
        None, description="Filter by listing status"),
    skill_id: Optional[int] = Query(
        None, description="Filter by source skill ID"),
    category_id: Optional[int] = Query(
        None,
        description="Filter by marketplace category ID",
    ),
    page: Annotated[int, Query(
        ge=1, description="Page number starting from 1")] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=100, description="Page size from 1 to 100")
    ] = 10,
    search: Optional[str] = Query(
        None, description="Filter by name, description, source, submitter, or tags"
    ),
    tag_predicates: Optional[str] = Query(
        None,
        description="Structured tag predicates encoded as JSON",
    ),
    tag: Optional[str] = Query(None, description="Filter by an exact tag"),
    sort_by_update_time: bool = Query(
        False, description="Sort by repository update time descending"
    ),
    authorization: str = Header(None),
):
    """List all skill marketplace repository listings with optional filters."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        ensure_skill_repository_access(user_id)
        filters = {
            "user_id": user_id,
            "status": status,
            "skill_id": skill_id,
            "category_id": category_id,
            "page": page,
            "page_size": page_size,
            "search": search,
            "sort_by_update_time": sort_by_update_time,
        }
        predicates = _parse_tag_predicates(tag_predicates)
        if predicates:
            filters["tag_predicates"] = predicates
        if tag:
            filters["tag"] = tag
        result = list_skill_repository_listings_impl(tenant_id, **filters)
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except UnauthorizedError as e:
        logger.warning(
            f"Unauthorized skill repository listings access attempt: {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except ForbiddenError as e:
        logger.warning(
            f"Forbidden skill repository listings access attempt: {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(e))
    except ValueError as e:
        logger.warning(
            f"Invalid skill repository listings request parameters: {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))


@skill_repository_router.get("/tags")
async def list_skill_repository_tag_stats_api(authorization: str = Header(None)):
    """List shared repository tag values with counts for the caller tenant."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        ensure_skill_repository_access(user_id)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"items": list_skill_repository_tag_stats_impl(tenant_id)},
        )
    except UnauthorizedError as e:
        logger.warning(f"Unauthorized skill repository tag-stat access: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except ForbiddenError as e:
        logger.warning(f"Forbidden skill repository tag-stat access: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(
            "Failed to list skill repository tag statistics: %s",
            e,
        )
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to list skill repository tag statistics",
        ) from e


@skill_repository_router.get("/mine")
async def list_my_editable_skills_api(
    ownership: Optional[str] = Query(
        "all",
        description="Filter by ownership: all / created / others",
    ),
    page: Annotated[int, Query(
        ge=1, description="Page number starting from 1")] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=100, description="Page size from 1 to 100")
    ] = 10,
    search: Optional[str] = Query(
        None, description="Filter by skill name, description, source, creator, or tags"
    ),
    new_skill_padding: bool = Query(
        False,
        description="Reserve first slot on page 1 for create-skill placeholder",
    ),
    tag_predicates: Optional[str] = Query(
        None,
        description="Structured tag predicates encoded as JSON",
    ),
    authorization: str = Header(None),
):
    """List editable skills for the current user with repository listing info."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        filters = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "ownership": ownership or "all",
            "page": page,
            "page_size": page_size,
            "search": search,
            "new_skill_padding": new_skill_padding,
        }
        predicates = _parse_tag_predicates(tag_predicates)
        if predicates:
            filters["tag_predicates"] = predicates
        result = list_my_editable_skills_impl(**filters)
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except UnauthorizedError as e:
        logger.warning(
            f"Unauthorized my editable skills access attempt: {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except ValueError as e:
        logger.warning(
            f"Invalid my editable skills request parameters (ownership={ownership}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))


@skill_repository_router.get("/mine/counts")
async def count_my_editable_skills_api(
    authorization: str = Header(None),
):
    """Count visible skills by ownership without loading full skill records."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = count_my_editable_skills_impl(
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except UnauthorizedError as e:
        logger.warning(
            f"Unauthorized my editable skill counts access attempt: {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))


@skill_repository_router.get("/{skill_repository_id}")
async def get_skill_repository_listing_detail_api(
    skill_repository_id: int,
    authorization: str = Header(None),
):
    """Get detailed skill marketplace repository listing by primary key."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        ensure_skill_repository_access(user_id)
        result = get_skill_repository_listing_detail_impl(
            skill_repository_id,
            tenant_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except UnauthorizedError as e:
        logger.warning(
            f"Unauthorized skill repository listing detail access attempt "
            f"(id={skill_repository_id}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except ForbiddenError as e:
        logger.warning(
            f"Forbidden skill repository listing detail access attempt "
            f"(id={skill_repository_id}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(e))
    except ValueError as e:
        logger.warning(
            f"Skill repository listing not found (id={skill_repository_id}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))


@skill_repository_router.patch("/{skill_repository_id}/status")
async def update_skill_repository_status_api(
    skill_repository_id: int,
    status: str = Body(
        ...,
        embed=True,
        description=(
            "New status: not_shared / pending_review / rejected / shared"
        ),
    ),
    content: Optional[str] = Body(
        None,
        embed=True,
        description="Review opinion or resubmit note",
    ),
    authorization: str = Header(None),
):
    """Update skill marketplace repository listing status."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        ensure_skill_repository_access(user_id)
        result = update_skill_repository_status_impl(
            skill_repository_id=skill_repository_id,
            status=status,
            user_id=user_id,
            tenant_id=tenant_id,
            content=content,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except UnauthorizedError as e:
        logger.warning(
            f"Unauthorized skill repository status update attempt "
            f"(id={skill_repository_id}, status={status}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except ForbiddenError as e:
        logger.warning(
            f"Forbidden skill repository status update attempt "
            f"(id={skill_repository_id}, status={status}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(e))
    except ValueError as e:
        logger.warning(
            f"Invalid skill repository status update "
            f"(id={skill_repository_id}, status={status}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))


@skill_repository_router.post("/{skill_id}")
async def create_skill_repository_listing_api(
    skill_id: int,
    payload: Optional[SkillRepositoryListingCreateRequest] = Body(None),
    authorization: str = Header(None),
):
    """Create or update a marketplace repository listing from a skill snapshot."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        card_fields = payload.model_dump(
            exclude_none=True) if payload else None
        result = create_skill_repository_listing_impl(
            skill_id=skill_id,
            tenant_id=tenant_id,
            user_id=user_id,
            card_fields=card_fields,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except UnauthorizedError as e:
        logger.warning(
            f"Unauthorized skill repository listing creation attempt "
            f"(skill_id={skill_id}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except ForbiddenError as e:
        logger.warning(
            f"Forbidden skill repository listing creation attempt "
            f"(skill_id={skill_id}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(e))
    except ValueError as e:
        logger.warning(
            f"Invalid skill repository listing creation parameters "
            f"(skill_id={skill_id}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))


@skill_repository_router.post("/{skill_repository_id}/install")
async def install_skill_from_repository_api(
    skill_repository_id: int,
    payload: Optional[SkillRepositoryInstallRequest] = Body(None),
    authorization: Optional[str] = Header(None),
):
    """Install a skill from a shared marketplace repository listing."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = install_skill_from_repository_impl(
            skill_repository_id=skill_repository_id,
            tenant_id=tenant_id,
            user_id=user_id,
            target_name=payload.target_name if payload else None,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except UnauthorizedError as e:
        logger.warning(
            f"Unauthorized skill repository install attempt "
            f"(id={skill_repository_id}): {str(e)}"
        )
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except ValueError as e:
        message = str(e)
        status_code = (
            HTTPStatus.NOT_FOUND
            if "not found" in message.lower()
            else HTTPStatus.BAD_REQUEST
        )
        logger.warning(
            f"Invalid skill repository install request "
            f"(id={skill_repository_id}): {message}"
        )
        raise HTTPException(status_code=status_code, detail=message)
    except SkillDuplicateError as e:
        logger.warning(
            f"Duplicate skill repository install attempt "
            f"(id={skill_repository_id}, duplicates={e.duplicate_names})"
        )
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail={
                "type": "skill_duplicate",
                "duplicate_skills": e.duplicate_names,
            },
        )
