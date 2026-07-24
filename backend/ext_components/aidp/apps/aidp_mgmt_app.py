"""AIDP Management App Layer (v7.1).

FastAPI endpoints for AIDP knowledge base CRUD with permission enforcement.

* Every handler calls :func:`_auth` to resolve ``(user_id, tenant_id)`` from
  the ``Authorization`` header. Missing or invalid auth raises 401.
* Resource-level operations call :func:`require_permission` to enforce
  the v7.1 permission matrix and raise 403/404 when violated.
* Creation is idempotent: the AIDP call uses ``kds_id`` returned from AIDP
  as the dedup key; collisions surface as 409 without compensating deletes.
* KB metadata is fetched lazily for the visible page only; failures mark
  ``resource_status = UNAVAILABLE`` so the frontend can render the row
  gracefully instead of treating it as a hard error.
"""
from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Annotated, List, Optional

from fastapi import APIRouter, File, Path, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from consts.const import AIDP_API_KEY, AIDP_SERVER_URL
from consts.error_code import ErrorCode
from consts.exceptions import AppException, UnauthorizedError
from ext_components.aidp.consts.aidp_exceptions import (
    AidpKbConflictError,
    AidpKbNotFoundError,
    AidpKbPermissionDeniedError,
    AidpKbSyncError,
    AidpGroupValidationError,
)
from ext_components.aidp.database import aidp_permission_db
from ext_components.aidp.services import aidp_permission_service as perms
from ext_components.aidp.services.aidp_service import (
    count_aidp_docs_impl,
    create_aidp_kb_impl,
    delete_aidp_kb_impl,
    get_aidp_kb_impl,
    list_aidp_docs_impl,
    list_aidp_models_impl,
    update_aidp_kb_impl,
    upload_aidp_docs_impl,
)
from ext_components.aidp.services.aidp_permission_service import (
    EDIT,
    READ_ONLY,
    _validate_group_ids_strict,
)
from utils import auth_utils as auth_utils_module

aidp_mgmt_router = APIRouter(prefix="/aidp-mgmt")
logger = logging.getLogger("aidp_mgmt_app")


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------


class CreateKbRequest(BaseModel):
    """Request body for creating a knowledge base."""

    name: str = Field(..., description="Knowledge base name (required)")
    description: Optional[str] = Field(None, description="Knowledge base description")
    embedding_model: Optional[str] = Field(None, description="Embedding model identifier")
    is_multimodal: Optional[bool] = Field(None, description="Whether KB supports multimodal content")
    vision_model: Optional[str] = Field(None, description="Vision model identifier for multimodal KBs")
    chunk_token_num: Optional[int] = Field(None, description="Chunk size in tokens (> 0)")
    chunk_overlap_num: Optional[int] = Field(None, description="Chunk overlap in tokens (>= 0)")
    vlm_model: Optional[str] = Field(None, description="VLM model identifier for caption generation")
    is_personal: Optional[int] = Field(None, ge=0, le=1, description="Personal KB flag, int 0 or 1")
    topk: Optional[int] = Field(None, description="Top-K retrieval count")
    similarity: Optional[float] = Field(None, description="Similarity score threshold")
    smartsplit: Optional[int] = Field(None, ge=0, le=1, description="Smart chunking mode, int 0 or 1")
    caption_enable: Optional[int] = Field(None, ge=0, le=1, description="Caption generation toggle, int 0 or 1")
    # Nexent-side permission payload. Never forwarded to AIDP.
    ingroup_permission: Optional[str] = Field(
        "READ_ONLY",
        description="Permission level for authorised groups: EDIT / READ_ONLY / PRIVATE",
    )
    group_ids: Optional[List[int]] = Field(
        None,
        description="Group IDs granted the in-group permission. Empty/ignored when PRIVATE.",
    )


class UpdateKbRequest(BaseModel):
    """Request body for updating a knowledge base."""

    name: Optional[str] = Field(None, description="Knowledge base name")
    description: Optional[str] = Field(None, description="Knowledge base description")


class SetPermissionRequest(BaseModel):
    """Request body for setting a KB's group-level permission.

    The AIDP platform is not invoked; the change is purely a local table
    write that controls who can see the KB in subsequent list/search calls.
    """

    ingroup_permission: str = Field(..., description="EDIT / READ_ONLY / PRIVATE")
    group_ids: Optional[List[int]] = Field(
        None,
        description="Group IDs granted the in-group permission. Ignored when PRIVATE.",
    )


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


async def _auth(request: Request) -> tuple[str, str]:
    """Resolve ``(user_id, tenant_id)`` from the Authorization header.

    Raises 401 for missing/invalid tokens or empty tenant contexts so the
    caller never has to defend against partially-authenticated state.
    """
    auth = request.headers.get("Authorization")
    if not auth:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="Missing Authorization header")
    try:
        user_id, tenant_id = auth_utils_module.get_current_user_id(auth)
    except UnauthorizedError as exc:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    if not tenant_id:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="No tenant context")
    return user_id, tenant_id


def _raise_aidp_conflict(exc: IntegrityError) -> None:
    """Translate a unique-index violation into an HTTP 409 conflict."""
    logger.warning("AIDP permission unique constraint violated: %s", exc)
    raise HTTPException(
        status_code=HTTPStatus.CONFLICT,
        detail="Knowledge base already exists for this tenant",
    )


# HTTPException is imported lazily to keep FastAPI's exception handler in
# control of the response body.
from fastapi import HTTPException  # noqa: E402  (placed here to avoid editing mid-file)


def _credentials() -> tuple[str, str]:
    return AIDP_SERVER_URL, AIDP_API_KEY


# ---------------------------------------------------------------------------
# Permission-aware helpers
# ---------------------------------------------------------------------------


def _serialize_permission(decision) -> dict:
    return {
        "permission": decision.permission,
        "matched_group_ids": list(decision.matched_group_ids),
        "is_management_role": decision.is_management_role,
    }


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@aidp_mgmt_router.get("/knowledge-bases")
async def list_knowledge_bases(
    request: Request,
    page: Annotated[int, Query(ge=1, description="Page number starting from 1")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Page size from 1 to 100")] = 10,
) -> JSONResponse:
    """List KBs the caller can access.

    Resolution order:
    1. Read active rows from the local DB for the tenant (tenant + active
       filter ensures we never leak across tenants).
    2. For each row, compute the effective permission using the role +
       ownership + group intersection matrix.
    3. Fetch AIDP-side metadata lazily for the visible page only; failures
       mark ``resource_status = UNAVAILABLE`` rather than failing the list.
    """
    user_id, tenant_id = await _auth(request)

    total_count = perms.count_accessible_kbs(user_id=user_id, tenant_id=tenant_id)
    if total_count == 0:
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"value": [], "total_count": 0, "has_more": False, "total_reliable": True},
        )

    rows = perms.get_accessible_kbs(
        user_id=user_id, tenant_id=tenant_id, page=page, page_size=page_size
    )

    server_url, api_key = _credentials()
    items: list[dict] = []
    for row in rows:
        kb_id = row["kb_id"]
        try:
            detail = get_aidp_kb_impl(server_url, api_key, kb_id) or {}
            resource_status = "ACTIVE"
        except AppException as exc:
            logger.warning("AIDP detail fetch failed for %s: %s", kb_id, exc)
            perms.update_resource_status(
                kb_id=kb_id, tenant_id=tenant_id, status="UNAVAILABLE",
                updated_by=user_id,
            )
            detail = {}
            resource_status = "UNAVAILABLE"

        items.append({
            "kds_id": kb_id,
            "kds_name": detail.get("kds_name") or detail.get("name") or "",
            "description": detail.get("description", ""),
            "document_count": detail.get("document_count", 0),
            "chunk_count": detail.get("chunk_count", 0),
            "embedding_model": detail.get("embedding_model", ""),
            "is_multimodal": detail.get("is_multimodal", False),
            "created_at": detail.get("created_at"),
            "permission": row.get("permission"),
            "ingroup_permission": row.get("ingroup_permission"),
            "group_ids": row.get("group_ids"),
            "created_by": row.get("owner_user_id"),
            "resource_status": resource_status,
        })

    has_more = page * page_size < total_count
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={
            "value": items,
            "total_count": total_count,
            "has_more": has_more,
            "total_reliable": True,
        },
    )


@aidp_mgmt_router.get("/knowledge-bases/count")
async def count_knowledge_bases(request: Request) -> JSONResponse:
    """Return the accessible KB count for the calling user/tenant."""
    user_id, tenant_id = await _auth(request)
    total = perms.count_accessible_kbs(user_id=user_id, tenant_id=tenant_id)
    return JSONResponse(status_code=HTTPStatus.OK, content={"total_count": total})


@aidp_mgmt_router.post("/knowledge-bases")
async def create_knowledge_base(
    request: Request,
    body: CreateKbRequest,
) -> JSONResponse:
    """Create a KB. Idempotent via ``kds_id`` unique-index backstop."""
    user_id, tenant_id = await _auth(request)

    ingroup = body.ingroup_permission or READ_ONLY
    if ingroup not in {EDIT, READ_ONLY, "PRIVATE"}:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f"Unsupported ingroup_permission: {ingroup!r}",
        )

    if ingroup != "PRIVATE":
        if not body.group_ids:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="group_ids is required when ingroup_permission is READ_ONLY or EDIT",
            )
        try:
            valid_group_ids = perms._validate_group_ids_strict(body.group_ids, tenant_id)
        except AidpGroupValidationError as exc:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail=str(exc),
            )
    else:
        valid_group_ids = []

    server_url, api_key = _credentials()
    aidp_payload = body.model_dump(
        exclude={"ingroup_permission", "group_ids"},
        exclude_none=True,
    )
    try:
        aidp_result = create_aidp_kb_impl(server_url, api_key, aidp_payload)
    except AppException:
        raise
    except Exception as exc:
        logger.exception("AIDP create failed: %s", exc)
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"Failed to create AIDP knowledge base: {exc}",
        )

    kds_id = aidp_result.get("kds_id") or aidp_result.get("id")
    if not kds_id:
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            "AIDP did not return a kds_id for the created knowledge base",
        )

    if aidp_permission_db.get_permission_by_kb_id(kds_id, tenant_id):
        raise AidpKbConflictError(kds_id, tenant_id).__class__(
            kds_id=kds_id, tenant_id=tenant_id
        ) if False else HTTPException(  # construct HTTPException directly to keep mapping simple
            status_code=HTTPStatus.CONFLICT,
            detail=f"Knowledge base {kds_id} already exists in this tenant",
        )

    try:
        perms.create_permission(
            kb_id=kds_id,
            owner_user_id=user_id,
            tenant_id=tenant_id,
            ingroup_permission=ingroup,
            group_ids=valid_group_ids,
            resource_status="CREATING",
            created_by=user_id,
        )
    except IntegrityError as exc:
        _raise_aidp_conflict(exc)
    except Exception as db_err:
        logger.error("Failed to save KB permission, rolling back AIDP: %s", db_err)
        try:
            delete_aidp_kb_impl(server_url, api_key, kds_id)
        except Exception as rollback_err:
            logger.critical(
                "AIDP rollback failed for kds_id=%s (orphan remains): %s",
                kds_id, rollback_err,
            )
            perms.update_resource_status(
                kb_id=kds_id, tenant_id=tenant_id, status="ORPHANED",
                updated_by=user_id,
            )
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to save knowledge base permission record",
        )

    perms.update_resource_status(
        kb_id=kds_id, tenant_id=tenant_id, status="ACTIVE", updated_by=user_id,
    )

    aidp_result = dict(aidp_result or {})
    aidp_result["permission"] = EDIT
    return JSONResponse(status_code=HTTPStatus.OK, content=aidp_result)


@aidp_mgmt_router.get("/knowledge-bases/{kds_id}")
async def get_knowledge_base(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    decision = perms.require_permission(kds_id, user_id, tenant_id, required="READ")

    server_url, api_key = _credentials()
    try:
        detail = get_aidp_kb_impl(server_url, api_key, kds_id) or {}
        resource_status = "ACTIVE"
    except AppException as exc:
        logger.warning("AIDP detail fetch failed for %s: %s", kds_id, exc)
        perms.update_resource_status(
            kb_id=kds_id, tenant_id=tenant_id, status="UNAVAILABLE",
            updated_by=user_id,
        )
        detail = {}
        resource_status = "UNAVAILABLE"

    detail = dict(detail)
    detail["kds_id"] = kds_id
    detail["permission"] = decision.permission
    detail["resource_status"] = resource_status
    return JSONResponse(status_code=HTTPStatus.OK, content=detail)


@aidp_mgmt_router.put("/knowledge-bases/{kds_id}")
async def update_knowledge_base(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    body: UpdateKbRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")

    payload = body.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="At least one field (name or description) must be provided for update",
        )
    server_url, api_key = _credentials()
    result = update_aidp_kb_impl(server_url, api_key, kds_id, payload)
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_mgmt_router.delete("/knowledge-bases/{kds_id}")
async def delete_knowledge_base(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")

    server_url, api_key = _credentials()
    success = delete_aidp_kb_impl(server_url, api_key, kds_id)
    if success:
        perms.soft_delete_permission(
            kb_id=kds_id, tenant_id=tenant_id, updated_by=user_id,
        )
    return JSONResponse(status_code=HTTPStatus.OK, content={"success": success})


@aidp_mgmt_router.post("/knowledge-bases/{kds_id}/documents")
async def upload_documents(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    files: List[UploadFile] = File(..., description="Files to upload"),
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")

    server_url, api_key = _credentials()
    result = upload_aidp_docs_impl(server_url, api_key, kds_id, files)
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_mgmt_router.get("/knowledge-bases/{kds_id}/documents")
async def list_documents(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    page: Annotated[int, Query(ge=1, description="Page number starting from 1")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Page size from 1 to 100")] = 10,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="READ")

    server_url, api_key = _credentials()
    result = list_aidp_docs_impl(server_url, api_key, kds_id, page=page, page_size=page_size)
    page_items = result.get("value", []) if isinstance(result, dict) else []
    page_count = len(page_items) if isinstance(page_items, list) else 0

    try:
        total_count = count_aidp_docs_impl(server_url, api_key, kds_id)
        count_reliable = True
    except Exception as count_err:
        logger.warning(
            "AIDP doc Count API failed for KB %s: %s", kds_id, count_err,
        )
        total_count = page_count
        count_reliable = False

    has_more = (
        total_count > page * page_size
        if count_reliable
        else bool(result.get("next_link")) or page_count >= page_size
    )

    result["total_count"] = int(total_count)
    result["has_more"] = has_more
    if not count_reliable:
        result["total_reliable"] = False
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_mgmt_router.patch("/aidp-permissions/{kds_id}")
async def set_permission(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    body: SetPermissionRequest,
) -> JSONResponse:
    """Update the in-group permission for a KB (does not call AIDP)."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")

    if body.ingroup_permission not in {EDIT, READ_ONLY, "PRIVATE"}:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f"Unsupported ingroup_permission: {body.ingroup_permission!r}",
        )

    if body.ingroup_permission == "PRIVATE":
        final_group_ids: list[int] = []
    else:
        if not body.group_ids:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="group_ids is required when ingroup_permission is READ_ONLY or EDIT",
            )
        try:
            final_group_ids = perms._validate_group_ids_strict(body.group_ids, tenant_id)
        except AidpGroupValidationError as exc:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail=str(exc),
            )

    perms.update_permission(
        kb_id=kds_id,
        tenant_id=tenant_id,
        ingroup_permission=body.ingroup_permission,
        group_ids=final_group_ids,
        updated_by=user_id,
    )
    return JSONResponse(status_code=HTTPStatus.OK, content={"success": True})


@aidp_mgmt_router.get("/models")
async def list_models(
    request: Request,
    service: Annotated[str, Query(description="Model service category (default: llm)")] = "llm",
    app: Annotated[str, Query(description="Application filter (default: KnowledgeBase)")] = "KnowledgeBase",
) -> JSONResponse:
    """List available models from AIDP ModelService. Auth required; no per-KB permission."""
    await _auth(request)
    server_url, api_key = _credentials()
    result = list_aidp_models_impl(server_url, api_key, service=service, app=app)
    return JSONResponse(status_code=HTTPStatus.OK, content=result)
