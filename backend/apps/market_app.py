"""Unified market FastAPI router.

Exposes endpoints under prefix ``/market`` for the unified market page
and template detail page.

All endpoints use ``authorization: str = Header(None)`` and call
``get_current_user_id(authorization)`` to resolve ``(user_id, tenant_id)``.
"""

import logging
from http import HTTPStatus
from typing import Annotated, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from starlette.requests import Request
from starlette.responses import JSONResponse

from consts.exceptions import UnauthorizedError
from consts.market import InstantiateRequest
from services.market_service import (
    get_agent_mcp_servers_impl,
    get_market_agent_detail_impl,
    list_categories_impl,
    list_market_agents_impl,
    list_tags_impl,
)
from services.recipe_service import instantiate_from_template_impl, launch_solution_impl
from utils.auth_utils import get_current_user_id, get_user_language

logger = logging.getLogger(__name__)
market_router = APIRouter(prefix="/market")


@market_router.get("/agents")
async def list_market_agents_api(
    page: Annotated[int, Query(ge=1, description="Page number starting from 1")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Page size from 1 to 100")] = 20,
    category: Optional[str] = Query(None, description="Filter by category ID or name"),
    tag: Optional[str] = Query(None, description="Filter by tag name"),
    search: Optional[str] = Query(None, description="Search keyword"),
    sort: Optional[str] = Query("latest", description="Sort order: latest / popular / name"),
    source: Optional[str] = Query(None, description="Filter by source: official / community"),
    lang: Optional[str] = Query(None, description="Language preference: zh / en"),
    authorization: str = Header(None, alias="Authorization"),
    request: Request = None,
):
    """List all shared/official market agent listings."""
    try:
        _user_id, _tenant_id = get_current_user_id(authorization)
        language = lang or get_user_language(request)
        result = list_market_agents_impl(
            page=page,
            page_size=page_size,
            category=category,
            tag=tag,
            search=search,
            sort=sort or "latest",
            source=source,
            lang=language,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except UnauthorizedError as e:
        logger.warning("Unauthorized market agents access: %s", str(e))
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except ValueError as e:
        logger.warning("Invalid market agents request: %s", str(e))
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))


@market_router.get("/agents/{agent_repository_id}")
async def get_market_agent_detail_api(
    agent_repository_id: int,
    lang: Optional[str] = Query(None, description="Language preference: zh / en"),
    authorization: str = Header(None, alias="Authorization"),
    request: Request = None,
):
    """Get detailed information for a single market agent listing."""
    try:
        _user_id, tenant_id = get_current_user_id(authorization)
        language = lang or get_user_language(request)
        result = get_market_agent_detail_impl(
            agent_repository_id=agent_repository_id,
            tenant_id=tenant_id,
            lang=language,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except UnauthorizedError as e:
        logger.warning("Unauthorized market agent detail access: %s", str(e))
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))


@market_router.post("/agents/{agent_repository_id}/instantiate")
async def instantiate_market_agent_api(
    agent_repository_id: int,
    body: InstantiateRequest,
    authorization: str = Header(None, alias="Authorization"),
):
    """Instantiate a new agent from a market template.

    Applies Recipe variable substitution and IndustryRule injection to the
    frozen template snapshot, then imports the agent tree into the current
    tenant. Returns ``{agent_id, precheck}``.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
    except UnauthorizedError as e:
        logger.warning("Unauthorized instantiate attempt: %s", str(e))
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))

    try:
        result = await instantiate_from_template_impl(
            template_id=agent_repository_id,
            variable_values=body.variable_values or {},
            user_id=user_id,
            tenant_id=tenant_id,
            authorization=authorization,
            force_import=body.force_import,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        logger.warning(
            "Instantiate failed (template=%s): %s", agent_repository_id, str(e)
        )
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception(
            "Instantiate error (template=%s): %s", agent_repository_id, str(e)
        )
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to instantiate agent: {str(e)}",
        )


@market_router.post("/agents/{agent_repository_id}/launch")
async def launch_market_agent_api(
    agent_repository_id: int,
    authorization: str = Header(None, alias="Authorization"),
):
    """Launch a solution straight into a conversation (WorkBuddy-style).

    Get-or-creates a runnable Agent from the solution template (reusing an
    existing same-named agent if present, otherwise instantiating with each
    Recipe variable's default value). Returns ``{agent_id, reused}`` so the
    frontend can drop the user directly into /newchat.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
    except UnauthorizedError as e:
        logger.warning("Unauthorized launch attempt: %s", str(e))
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))

    try:
        result = await launch_solution_impl(
            template_id=agent_repository_id,
            user_id=user_id,
            tenant_id=tenant_id,
            authorization=authorization,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        logger.warning("Launch failed (template=%s): %s", agent_repository_id, str(e))
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception("Launch error (template=%s): %s", agent_repository_id, str(e))
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to launch solution: {str(e)}",
        )


@market_router.get("/categories")
async def list_categories_api(
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    lang: Optional[str] = Query(None, description="Language preference: zh / en"),
    authorization: str = Header(None, alias="Authorization"),
    request: Request = None,
):
    """List all active market categories."""
    try:
        _user_id, _tenant_id = get_current_user_id(authorization)
        language = lang or get_user_language(request)
        result = list_categories_impl(lang=language, entity_type=entity_type)
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except UnauthorizedError as e:
        logger.warning("Unauthorized market categories access: %s", str(e))
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))


@market_router.get("/tags")
async def list_tags_api(
    authorization: str = Header(None, alias="Authorization"),
):
    """List all market tags with usage counts."""
    try:
        _user_id, _tenant_id = get_current_user_id(authorization)
        result = list_tags_impl()
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except UnauthorizedError as e:
        logger.warning("Unauthorized market tags access: %s", str(e))
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))


@market_router.get("/agents/{agent_repository_id}/mcp_servers")
async def get_agent_mcp_servers_api(
    agent_repository_id: int,
    authorization: str = Header(None, alias="Authorization"),
):
    """Get the MCP servers configured for a market agent listing."""
    try:
        _user_id, _tenant_id = get_current_user_id(authorization)
        result = get_agent_mcp_servers_impl(agent_repository_id)
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except UnauthorizedError as e:
        logger.warning("Unauthorized market agent mcp_servers access: %s", str(e))
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
