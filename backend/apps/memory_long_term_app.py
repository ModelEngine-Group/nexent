"""HTTP API for versioned tenant and user Markdown long-term memory."""

from http import HTTPStatus
from typing import Literal, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Response
from pydantic import BaseModel

from database.user_tenant_db import get_user_tenant_by_user_id
from services.memory_long_term_service import (
    LongTermMemoryConflict, LongTermMemoryError, get_memory_long_term_service,
)
from utils.auth_utils import get_current_user_id

router = APIRouter(prefix="/memory/long-term", tags=["long-term-memory"])
Scope = Literal["tenant", "user"]


class CreateVersionRequest(BaseModel):
    content: str
    expected_active_version_id: Optional[int] = None


class ActivateVersionRequest(BaseModel):
    expected_active_version_id: Optional[int] = None


def _authorize_mutation(scope: Scope, user_id: str) -> None:
    if scope == "tenant":
        row = get_user_tenant_by_user_id(user_id) or {}
        if str(row.get("user_role") or "").upper() != "ADMIN":
            raise HTTPException(HTTPStatus.FORBIDDEN, "Tenant memory mutation requires the ADMIN role")


@router.get("/{scope}")
def get_active(scope: Scope, response: Response, authorization: Optional[str] = Header(None)):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    user_id, tenant_id = get_current_user_id(authorization)
    value = get_memory_long_term_service().get_active(tenant_id, user_id, scope)
    return {"empty": value is None, "version": value}


@router.get("/{scope}/versions")
def list_versions(scope: Scope, response: Response, authorization: Optional[str] = Header(None),
                  limit: int = Query(100, ge=1, le=500)):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    user_id, tenant_id = get_current_user_id(authorization)
    items = get_memory_long_term_service().list_versions(tenant_id, user_id, scope, limit)
    return {"items": items, "count": len(items)}


@router.get("/{scope}/versions/{version_id}")
def get_version(scope: Scope, version_id: int, response: Response, authorization: Optional[str] = Header(None)):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    user_id, tenant_id = get_current_user_id(authorization)
    value = get_memory_long_term_service().get_version(tenant_id, user_id, scope, version_id)
    if value is None: raise HTTPException(HTTPStatus.NOT_FOUND, "Version not found")
    return value


@router.post("/{scope}/versions", status_code=HTTPStatus.CREATED)
def create_version(scope: Scope, payload: CreateVersionRequest,
                   authorization: Optional[str] = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization); _authorize_mutation(scope, user_id)
    try:
        return get_memory_long_term_service().create_manual(
            tenant_id, user_id, scope, payload.content, payload.expected_active_version_id)
    except LongTermMemoryConflict as exc:
        raise HTTPException(HTTPStatus.CONFLICT, str(exc)) from exc
    except LongTermMemoryError as exc:
        raise HTTPException(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.post("/{scope}/versions/{version_id}/activate")
def activate_version(scope: Scope, version_id: int, payload: ActivateVersionRequest,
                     authorization: Optional[str] = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization); _authorize_mutation(scope, user_id)
    try:
        value = get_memory_long_term_service().activate(
            tenant_id, user_id, scope, version_id, payload.expected_active_version_id)
    except LongTermMemoryConflict as exc:
        raise HTTPException(HTTPStatus.CONFLICT, str(exc)) from exc
    if value is None: raise HTTPException(HTTPStatus.NOT_FOUND, "Version not found")
    return value
