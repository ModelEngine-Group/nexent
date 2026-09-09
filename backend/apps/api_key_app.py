"""Authenticated tenant administration endpoints for API keys."""

import logging
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from consts.exceptions import (
    ForbiddenError,
    NotFoundException,
    UnauthorizedError,
    ValidationError,
)
from consts.model import ApiKeyTargetRequest
from services.api_key_service import (
    list_tenant_api_keys,
    refresh_user_api_key,
    revoke_user_api_keys,
)
from utils.auth_utils import get_current_user_context

logger = logging.getLogger("api_key_app")
router = APIRouter(prefix="/api-keys", tags=["api-keys"])


def _map_error(exc: Exception) -> None:
    if isinstance(exc, UnauthorizedError):
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    if isinstance(exc, ForbiddenError):
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc))
    if isinstance(exc, NotFoundException):
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc))
    if isinstance(exc, (ValidationError, ValueError)):
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
    raise exc


@router.get("")
async def list_api_keys_endpoint(
    tenant_id: str = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    authorization: Optional[str] = Header(None),
) -> JSONResponse:
    try:
        _, requester_tenant_id, requester_role = get_current_user_context(authorization)
        result = list_tenant_api_keys(
            actor_tenant_id=requester_tenant_id,
            actor_role=requester_role,
            tenant_id=tenant_id,
            page=page,
            page_size=page_size,
            sort_order=sort_order,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK, content={"message": "success", "data": result}
        )
    except Exception as exc:
        logger.warning("Failed to list tenant API keys: %s", exc)
        _map_error(exc)


@router.post("/refresh")
async def refresh_api_key_endpoint(
    payload: ApiKeyTargetRequest,
    authorization: Optional[str] = Header(None),
) -> JSONResponse:
    try:
        actor_user_id, tenant_id, role = get_current_user_context(authorization)
        result = refresh_user_api_key(
            actor_user_id=actor_user_id,
            actor_tenant_id=tenant_id,
            actor_role=role,
            user_id=payload.user_id,
            email=str(payload.email) if payload.email else None,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK, content={"message": "success", "data": result}
        )
    except Exception as exc:
        logger.warning("Failed to refresh API key: %s", exc)
        _map_error(exc)


@router.delete("")
async def revoke_api_key_endpoint(
    user_id: Optional[str] = Query(None),
    email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
) -> JSONResponse:
    try:
        target = ApiKeyTargetRequest(user_id=user_id, email=email)
        actor_user_id, tenant_id, role = get_current_user_context(authorization)
        result = revoke_user_api_keys(
            actor_user_id=actor_user_id,
            actor_tenant_id=tenant_id,
            actor_role=role,
            user_id=target.user_id,
            email=str(target.email) if target.email else None,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK, content={"message": "success", "data": result}
        )
    except Exception as exc:
        logger.warning("Failed to revoke API key: %s", exc)
        _map_error(exc)
