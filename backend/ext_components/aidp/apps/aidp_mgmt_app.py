"""AIDP Management App Layer (v7.1).

FastAPI endpoints for AIDP knowledge base CRUD with permission enforcement.

* Every handler calls :func:`_auth` to resolve ``(user_id, tenant_id)`` from
  the ``Authorization`` header. Missing or invalid auth raises 401.
* Resource-level operations call :func:`require_permission` to enforce
  the v7.1 permission matrix and raise 403/404 when violated.
* Creation is idempotent: the AIDP call uses ``kds_id`` returned from AIDP
  as the dedup key; collisions surface as 409 without compensating deletes.
* The current AIDP catalog is intersected with Nexent permissions before
  pagination. KB metadata is fetched lazily for the visible page only.
"""
from __future__ import annotations

import asyncio
import logging
import time
from http import HTTPStatus
from typing import Annotated, List, Optional
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Path, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from nexent.core.concurrency import run_blocking
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from starlette.background import BackgroundTask

from consts.const import AIDP_API_KEY, AIDP_SERVER_URL
from consts.error_code import ErrorCode
from consts.exceptions import AppException, UnauthorizedError
from database.user_tenant_db import get_user_role_by_tenant
from ext_components.aidp.consts.aidp_exceptions import (
    AidpGroupValidationError,
    AidpKbConflictError,
)
from ext_components.aidp.database import aidp_permission_db
from ext_components.aidp.services import aidp_permission_service as perms
from ext_components.aidp.services.aidp_access_service import (
    get_cached_aidp_channels,
    get_cached_aidp_doc_count,
    get_cached_aidp_kb_detail,
    invalidate_aidp_catalog_cache,
    invalidate_aidp_doc_count_cache,
    invalidate_aidp_kb_detail_cache,
    resolve_current_aidp_access,
)
from ext_components.aidp.services.aidp_kb_update_service import save_kb_settings
from ext_components.aidp.services.aidp_permission_service import (
    EDIT,
    PRIVATE,
    READ_ONLY,
    _validate_group_ids_strict,  # noqa: F401 - retained as a module-level compatibility symbol
)
from ext_components.aidp.services.aidp_service import (
    _timestamp_to_iso,
    count_aidp_docs_impl,
    create_aidp_kb_impl,
    delete_aidp_kb_impl,
    get_aidp_kb_impl,
    list_aidp_channels_impl,
    list_aidp_doc_history_impl,
    list_aidp_docs_impl,
    list_aidp_models_impl,
    remove_aidp_docs_impl,
    stream_aidp_doc_impl,
    select_aidp_channel,
    update_aidp_kb_impl,
    upload_aidp_docs_impl,
)
from utils import auth_utils as auth_utils_module


aidp_mgmt_router = APIRouter(prefix="/aidp-mgmt")
logger = logging.getLogger("aidp_mgmt_app")

AIDP_MAX_UPLOAD_FILE_COUNT = 50
AIDP_SMALL_FILE_MAX_SIZE_BYTES = 20 * 1024 * 1024
AIDP_OTHER_FILE_MAX_SIZE_BYTES = 1024 * 1024 * 1024
AIDP_SMALL_FILE_EXTENSIONS = {"txt", "xls", "xlsx", "csv"}

# AIDP document statuses (mirrors the file-history vocabulary): UPLOADING,
# PROCESSING and EXTRACTING are the stages a file walks through, COMPLETED and
# FAILED are the two terminal outcomes. Only the terminal ones end the wait, so
# every other reported status is counted as work in progress: `processing_count`
# is what keeps the frontend polling, and a build that reports a stage we do not
# know yet must not stop it early either.
_TERMINAL_DOC_STATUSES = ("COMPLETED", "FAILED")


def _upload_failure(file_name: str, reason_zh: str, reason_en: str) -> dict:
    return {
        "file_name": file_name,
        "reason_zh": reason_zh,
        "reason_en": reason_en,
    }


def _validate_upload_files(files: List[UploadFile]) -> tuple[List[UploadFile], list[dict]]:
    """Validate AIDP upload count and per-file size without loading files into memory."""
    if len(files) > AIDP_MAX_UPLOAD_FILE_COUNT:
        reason_zh = f"单次最多上传 {AIDP_MAX_UPLOAD_FILE_COUNT} 个文件"
        reason_en = f"You can upload up to {AIDP_MAX_UPLOAD_FILE_COUNT} files at a time"
        return [], [
            _upload_failure(file.filename or "unknown", reason_zh, reason_en)
            for file in files
        ]

    valid_files: List[UploadFile] = []
    failed_files: list[dict] = []
    for file in files:
        file_name = file.filename or "unknown"
        extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        max_size_bytes = (
            AIDP_SMALL_FILE_MAX_SIZE_BYTES
            if extension in AIDP_SMALL_FILE_EXTENSIONS
            else AIDP_OTHER_FILE_MAX_SIZE_BYTES
        )
        max_size_mb = max_size_bytes // (1024 * 1024)

        original_position = file.file.tell()
        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(original_position)

        if file_size > max_size_bytes:
            failed_files.append(_upload_failure(
                file_name,
                f"文件大小不能超过 {max_size_mb} MB",
                f"File size must not exceed {max_size_mb} MB",
            ))
        else:
            valid_files.append(file)

    return valid_files, failed_files


def _cleanup_document_assignments_for_deleted_knowledge_base(
    tenant_id: str,
    knowledge_base_id: str,
    user_id: str,
) -> None:
    """Keep document assignment usage in sync after AIDP confirms knowledge-base deletion."""

    from services.tag_management_service import TagManagementService

    TagManagementService.cleanup_document_assignments_for_knowledge_base(
        tenant_id, "aidp", knowledge_base_id, user_id
    )


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
    """Save permissions and optionally synchronize explicitly changed metadata."""

    name: Optional[str] = Field(None, min_length=1, description="Changed KB name; omit when unchanged")
    description: Optional[str] = Field(None, description="Changed description; omit when unchanged")
    ingroup_permission: str = Field(..., description="EDIT / READ_ONLY / PRIVATE")
    group_ids: Optional[List[int]] = Field(
        None,
        description="Group IDs granted the in-group permission. Ignored when PRIVATE.",
    )


class RemoveAidpDocumentsRequest(BaseModel):

    file_uuids: List[UUID] = Field(..., min_length=1, description="AIDP file UUIDs")


class DownloadAidpDocumentRequest(BaseModel):
    """AIDP file selected for download."""

    file_uuid: UUID = Field(..., description="AIDP file UUID")


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


def _infer_is_multimodal(detail: dict) -> bool:
    """Reverse-derive ``is_multimodal`` from AIDP detail response.

    AIDP does not return an ``is_multimodal`` field — it is a Nexent-side
    concept. On create the SDK mapper translates it one-to-one into
    ``caption_enable`` (``sdk/nexent/core/knowledge_base/mapper.py``):

        caption_enable = 1 if is_multimodal else DEFAULT_CAPTION_ENABLE

    So the reverse mapping only needs to inspect ``caption_enable``. The
    ``vlm_model`` field is a separate, optional identifier that the user
    may or may not supply — we deliberately do NOT gate on it being
    non-empty, because (a) the user can choose any VLM model from the
    AIDP catalog (not a fixed name) and (b) AIDP may not even return
    the field for a given KB.

    Returns ``True`` iff ``caption_enable ∈ {1, "1", True}``.
    """
    if not isinstance(detail, dict):
        return False
    caption = detail.get("caption_enable")
    return caption in (1, "1", True)


def _raise_aidp_conflict(exc: IntegrityError) -> None:
    """Translate a unique-index violation into an HTTP 409 conflict."""
    logger.warning("AIDP permission unique constraint violated: %s", exc)
    raise HTTPException(
        status_code=HTTPStatus.CONFLICT,
        detail="Knowledge base already exists for this tenant",
    )


def _credentials() -> tuple[str, str]:
    return AIDP_SERVER_URL, AIDP_API_KEY


def _is_user_role(user_id: str, tenant_id: str) -> bool:
    """Return whether the caller is a regular USER in the current tenant.

    Missing tenant-role data is treated as USER so an authenticated caller
    cannot bypass the personal-KB boundary while its tenant context is being
    provisioned.
    """
    role = get_user_role_by_tenant(user_id, tenant_id)
    return (role or "USER").upper() == "USER"


def _current_accessible_rows(
    user_id: str,
    tenant_id: str,
    keyword: str | None = None,
) -> list[dict]:
    """Return the current AIDP catalog intersected with local user access.

    ``keyword`` is forwarded to AIDP so the remote catalog is already narrowed
    before the permission intersection runs.
    """
    server_url, api_key = _credentials()
    snapshot = resolve_current_aidp_access(
        server_url=server_url,
        api_key=api_key,
        user_id=user_id,
        tenant_id=tenant_id,
        aidp_tenant_id="aidp",
        keyword=keyword,
    )
    return snapshot.accessible_rows


# ---------------------------------------------------------------------------
# Permission-aware helpers
# ---------------------------------------------------------------------------


def _serialize_permission(decision) -> dict:
    return {
        "permission": decision.permission,
        "matched_group_ids": list(decision.matched_group_ids),
        "is_management_role": decision.is_management_role,
    }


def _has_kb_card_metadata(row: dict) -> bool:
    """Return whether the catalog row already contains every card field."""
    has_name = bool(row.get("kds_name") or row.get("name"))
    has_description = "description" in row
    has_created_at = "created_at" in row or "create_time" in row
    has_multimodal = "is_multimodal" in row or "caption_enable" in row
    return has_name and has_description and has_created_at and has_multimodal


def _load_cached_kb_detail(server_url: str, api_key: str, kb_id: str) -> dict:
    return get_cached_aidp_kb_detail(
        server_url=server_url,
        api_key=api_key,
        kds_id=kb_id,
        loader=lambda: get_aidp_kb_impl(server_url, api_key, kb_id) or {},
    )


def _load_cached_doc_count(server_url: str, api_key: str, kb_id: str) -> int:
    return get_cached_aidp_doc_count(
        server_url=server_url,
        api_key=api_key,
        kds_id=kb_id,
        loader=lambda: count_aidp_docs_impl(server_url, api_key, kb_id),
    )


# Knowledge bases whose all-status history has already been reported as
# unavailable. Documents are polled every few seconds while they process, so the
# fallback is reported once per KB instead of once per poll.
_HISTORY_FALLBACK_REPORTED: set[str] = set()


def _log_history_fallback(kds_id: str, reason: str) -> None:
    """Report (once per KB) that the document list fell back to ingested files.

    The status column can only be filled from the history payload, so a silent
    fallback shows up as a column of dashes. Logging the concrete reason keeps
    the cause traceable: an AIDP build without the endpoint, a channel list whose
    fields we cannot read, and a failing history request all land here.
    """
    if kds_id in _HISTORY_FALLBACK_REPORTED:
        logger.debug(
            "AIDP file history still unavailable for KB %s (%s)",
            kds_id,
            reason,
        )
        return
    _HISTORY_FALLBACK_REPORTED.add(kds_id)
    logger.warning(
        "AIDP all-status file history unavailable for KB %s (%s); the document list falls "
        "back to ingested files only, so files under processing stay invisible and the "
        "status column stays empty",
        kds_id,
        reason,
    )


def _resolve_doc_history_channel(
    server_url: str,
    api_key: str,
    kds_id: str,
) -> dict | None:
    """Resolve the ingestion channel whose directory feeds ``kds_id``.

    Returns ``None`` when AIDP exposes no channel carrying both ``fs_id`` and a
    source directory, in which case the caller keeps using the completed-files
    listing. The channel payload shape is reported when resolution fails, so an
    unreadable field name is visible instead of silently degrading.
    """
    channels = get_cached_aidp_channels(
        server_url=server_url,
        api_key=api_key,
        kds_id=kds_id,
        loader=lambda: list_aidp_channels_impl(server_url, api_key, kds_id),
    )
    channel = select_aidp_channel(channels, kds_id)
    if channel is None:
        _log_history_fallback(
            kds_id,
            "no channel exposes fs_id + a source dir (channels=%d, sample keys=%s)"
            % (len(channels), sorted(channels[0].keys()) if channels else []),
        )
    return channel


async def _load_doc_history(
    server_url: str,
    api_key: str,
    kds_id: str,
) -> dict | None:
    """Fetch the all-status document history for ``kds_id`` when available.

    Any failure degrades to the legacy completed-files listing rather than
    failing the request: the channel/history endpoints are newer than the
    document list and may be missing on older AIDP builds, and a knowledge base
    with no matching channel must still render its ingested files. Every
    degraded case is logged with the offending KB so the cause stays traceable.
    """
    try:
        channel = await run_blocking(
            "aidp-doc-history-channel",
            _resolve_doc_history_channel,
            server_url,
            api_key,
            kds_id,
            lane="control-io",
            owner="config",
        )
        if not channel:
            # The reason is reported by ``_resolve_doc_history_channel``.
            return None
        history = await run_blocking(
            "aidp-doc-history",
            list_aidp_doc_history_impl,
            server_url,
            api_key,
            channel["fs_id"],
            channel["src_dir"],
            kds_id,
            lane="control-io",
            owner="config",
        )
        items = history.get("value") if isinstance(history, dict) else None
        if isinstance(items, list) and not items:
            # A resolved channel directory holding no file would blank the table
            # and hide the KB's ingested files — the directory may simply not be
            # where this KB's uploads live. The KB-scoped listing is always safe
            # to show, so an empty history is treated as unusable rather than
            # authoritative (an empty KB still renders an empty list either way).
            _log_history_fallback(
                kds_id,
                "history returned no files for the resolved directory "
                f"(fs_id={channel['fs_id']}, dir_path={channel['src_dir']})",
            )
            return None
        return history
    except AppException as exc:
        _log_history_fallback(kds_id, f"history request failed: {exc}")
        return None
    except Exception as exc:  # noqa: BLE001 - history is an optional enhancement
        _log_history_fallback(kds_id, f"unexpected history error: {exc!r}")
        return None


def _history_sort_key(item: dict) -> tuple:
    """Sort key placing the most recently uploaded file first.

    Numeric upload timestamps sort above entries that only expose an ISO
    ``created_at`` string, and entries with neither sink to the bottom — the
    ordering is only ever used to bring fresh uploads to the top of page 1.
    """
    raw = item.get("first_upload_time")
    if raw is None:
        raw = item.get("create_time")
    try:
        return (1, float(raw))
    except (TypeError, ValueError):
        created_at = item.get("created_at")
        return (0, created_at) if isinstance(created_at, str) else (0, "")


def _paginate_history_documents(result: dict, page: int, page_size: int) -> dict:
    """Slice an all-status history payload into one page.

    The history API returns the whole channel directory in one response, so the
    total is exact and the document Count endpoint is not needed. Newest files
    come first so an upload shows up at the top of page 1 as soon as it is
    accepted, instead of only after ingestion completes.

    ``processing_count`` covers the WHOLE directory, not just the returned page:
    the frontend keeps polling while it is non-zero, so a file still being
    processed on another page also keeps the status column live.
    """
    raw_items = result.get("value")
    items = (
        [item for item in raw_items if isinstance(item, dict)]
        if isinstance(raw_items, list)
        else []
    )
    ordered = sorted(items, key=_history_sort_key, reverse=True)
    start = (page - 1) * page_size
    end = start + page_size
    # Count every non-terminal status, so a file that is uploading or extracting
    # keeps the frontend polling exactly like one that is being chunked.
    processing_count = sum(
        1
        for item in ordered
        if isinstance(item.get("status"), str)
        and item["status"].strip().upper() not in _TERMINAL_DOC_STATUSES
    )
    return {
        "value": ordered[start:end],
        "total_count": len(ordered),
        "has_more": end < len(ordered),
        "total_reliable": True,
        "processing_count": processing_count,
    }


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@aidp_mgmt_router.get("/knowledge-bases")
async def list_knowledge_bases(
    request: Request,
    page: Annotated[int, Query(ge=1, description="Page number starting from 1")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Page size from 1 to 100")] = 10,
    keyword: Annotated[
        str | None,
        Query(max_length=200, description="Optional name filter forwarded to AIDP"),
    ] = None,
) -> JSONResponse:
    """List KBs the caller can access, optionally filtered by name.

    Resolution order:
    1. Fetch the AIDP catalog visible to the configured credentials, narrowed
       server-side by ``keyword`` when one is supplied.
    2. Intersect that catalog with the caller's effective Nexent permissions.
    3. Paginate the intersection, then fetch details for the visible page.

    A non-blank ``keyword`` therefore narrows both the fetched set and the
    reported ``total_count``: both describe the filtered, permission-scoped set.
    """
    user_id, tenant_id = await _auth(request)

    server_url, api_key = _credentials()
    normalized_keyword = (keyword or "").strip() or None
    started_at = time.perf_counter()
    # ``run_blocking`` (not a bare to_thread) keeps AIDP catalog reads on the
    # managed control-io lane, and the keyword is still forwarded so the remote
    # catalog is narrowed server-side before the permission intersection.
    rows = await run_blocking(
        "aidp-accessible-rows",
        _current_accessible_rows,
        user_id,
        tenant_id,
        normalized_keyword,
        lane="control-io",
        owner="config",
    )
    access_resolve_ms = (time.perf_counter() - started_at) * 1000
    total_count = len(rows)
    if total_count == 0:
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"value": [], "total_count": 0, "has_more": False, "total_reliable": True},
        )

    start = (page - 1) * page_size
    page_rows = rows[start:start + page_size]

    detail_semaphore = asyncio.Semaphore(5)

    async def resolve_detail(row: dict) -> tuple[dict, str]:
        if _has_kb_card_metadata(row):
            return {}, "ACTIVE"
        kb_id = row["kb_id"]
        async with detail_semaphore:
            try:
                detail = await run_blocking(
                    "aidp-kb-detail",
                    _load_cached_kb_detail,
                    server_url,
                    api_key,
                    kb_id,
                    lane="control-io",
                    owner="config",
                )
                return detail, "ACTIVE"
            except AppException as exc:
                logger.warning("AIDP detail fetch failed for %s: %s", kb_id, exc)
                return {}, "UNAVAILABLE"

    detail_started_at = time.perf_counter()
    detail_results = await asyncio.gather(*(resolve_detail(row) for row in page_rows))
    detail_fetch_ms = (time.perf_counter() - detail_started_at) * 1000

    items: list[dict] = []
    for row, (detail, resource_status) in zip(page_rows, detail_results):
        kb_id = row["kb_id"]
        items.append({
            "kds_id": kb_id,
            "kds_name": (
                detail.get("kds_name")
                or detail.get("name")
                or row.get("kds_name")
                or row.get("name")
                or ""
            ),
            "description": detail.get("description") or row.get("description") or "",
            "document_count": detail.get("document_count", row.get("document_count", 0)),
            "chunk_count": detail.get("chunk_count", row.get("chunk_count", 0)),
            "embedding_model": detail.get("embedding_model") or row.get("embedding_model") or "",
            # ``is_multimodal`` is a Nexent-side concept (frontend sends it
            # when creating a KB; the SDK mapper converts it to
            # ``caption_enable`` + ``vlm_model``). AIDP does NOT return this
            # field, so we reverse-derive it from ``caption_enable == 1``
            # and a non-empty ``vlm_model``. Matches the forward mapping
            # in ``sdk/nexent/core/knowledge_base/mapper.py``.
            "is_multimodal": _infer_is_multimodal(detail or row),
            "vlm_model": detail.get("vlm_model") or row.get("vlm_model") or "",
            "caption_enable": detail.get("caption_enable", row.get("caption_enable", 0)),
            "created_at": (
                detail.get("created_at")
                or row.get("created_at")
                or _timestamp_to_iso(row.get("create_time"))
            ),
            "permission": row.get("permission"),
            "ingroup_permission": row.get("ingroup_permission"),
            "group_ids": row.get("group_ids"),
            "created_by": row.get("owner_user_id"),
            "resource_status": resource_status,
        })

    total_ms = (time.perf_counter() - started_at) * 1000
    logger.info(
        "AIDP KB list timing: total_ms=%.1f access_resolve_ms=%.1f detail_ms=%.1f "
        "accessible_count=%d page_item_count=%d detail_candidates=%d",
        total_ms,
        access_resolve_ms,
        detail_fetch_ms,
        total_count,
        len(page_rows),
        sum(1 for row in page_rows if not _has_kb_card_metadata(row)),
    )

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
    rows = await run_blocking(
        "aidp-accessible-rows", _current_accessible_rows, user_id, tenant_id,
        lane="control-io", owner="config",
    )
    total = len(rows)
    return JSONResponse(status_code=HTTPStatus.OK, content={"total_count": total})


@aidp_mgmt_router.post("/knowledge-bases")
async def create_knowledge_base(
    request: Request,
    body: CreateKbRequest,
) -> JSONResponse:
    """Create a KB. Idempotent via ``kds_id`` unique-index backstop."""
    user_id, tenant_id = await _auth(request)

    ingroup = body.ingroup_permission or READ_ONLY
    is_user = _is_user_role(user_id, tenant_id)
    if is_user:
        # Personal KB is the only KB type a USER may create. Normalize rather
        # than trusting the client, so direct API callers cannot create a
        # shared AIDP KB by sending EDIT/READ_ONLY and group_ids.
        ingroup = PRIVATE
        valid_group_ids: list[int] = []
    elif ingroup not in {EDIT, READ_ONLY, PRIVATE}:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f"Unsupported ingroup_permission: {ingroup!r}",
        )

    elif ingroup != PRIVATE:
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
    # Normalize to string. AIDP may return kds_id as int or str; the DB
    # schema declares ``kb_id VARCHAR(64)``, so PostgreSQL rejects a
    # mixed-type comparison (``varchar = integer``) with an
    # ``UndefinedFunction`` error. Cast once here so every downstream
    # use (DB lookup, permission record insert, log messages) is a str.
    kds_id = str(kds_id)

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
            kds_name=body.name or aidp_result.get("kds_name") or aidp_result.get("name") or "",
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
    invalidate_aidp_catalog_cache(server_url, api_key)

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
        detail = await run_blocking(
            "aidp-kb-detail",
            _load_cached_kb_detail,
            server_url,
            api_key,
            kds_id,
            lane="control-io",
            owner="config",
        )
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

    # Sync kds_name to permission table so the LLM name-to-id map stays current.
    new_kds_name = (
        (result.get("kds_name") if isinstance(result, dict) else None)
        or body.name
    )
    if new_kds_name:
        perms.update_permission(
            kb_id=kds_id,
            tenant_id=tenant_id,
            kds_name=new_kds_name,
            updated_by=user_id,
        )

    invalidate_aidp_catalog_cache(server_url, api_key)
    invalidate_aidp_kb_detail_cache(server_url, api_key, kds_id)

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
        invalidate_aidp_catalog_cache(server_url, api_key)
        invalidate_aidp_kb_detail_cache(server_url, api_key, kds_id)
        invalidate_aidp_doc_count_cache(server_url, api_key, kds_id)
        _cleanup_document_assignments_for_deleted_knowledge_base(tenant_id, kds_id, user_id)
    return JSONResponse(status_code=HTTPStatus.OK, content={"success": success})


@aidp_mgmt_router.post("/knowledge-bases/{kds_id}/documents")
async def upload_documents(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    files: List[UploadFile] = File(..., description="Files to upload"),
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")

    valid_files, validation_failures = _validate_upload_files(files)
    server_url, api_key = _credentials()
    if valid_files:
        result = await run_blocking(
            "aidp-upload-documents",
            upload_aidp_docs_impl,
            server_url,
            api_key,
            kds_id,
            valid_files,
            lane="control-io",
            owner="config",
        )
        invalidate_aidp_kb_detail_cache(server_url, api_key, kds_id)
        invalidate_aidp_doc_count_cache(server_url, api_key, kds_id)
    else:
        result = {
            "summary": {"total": 0, "success": 0, "failed": 0},
            "success_list": [],
            "failed_list": [],
        }

    success_list = result.get("success_list", []) if isinstance(result, dict) else []
    aidp_failed_list = result.get("failed_list", []) if isinstance(result, dict) else []
    failed_list = [*aidp_failed_list, *validation_failures]
    result = {
        "summary": {
            "total": len(files),
            "success": len(success_list),
            "failed": len(failed_list),
        },
        "success_list": success_list,
        "failed_list": failed_list,
    }
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
    started_at = time.perf_counter()

    # Preferred source: the all-status history, so files appear in the list
    # while they are still being chunked/embedded (and when they failed). The
    # payload covers the whole channel directory, so this branch paginates
    # in-process and reports an exact total.
    history_result = await _load_doc_history(server_url, api_key, kds_id)
    if history_result is not None:
        result = _paginate_history_documents(history_result, page, page_size)
        logger.info(
            "AIDP document list timing: total_ms=%.1f kb_id=%s page=%d page_size=%d "
            "page_count=%d total_count=%d total_reliable=True source=history",
            (time.perf_counter() - started_at) * 1000,
            kds_id,
            page,
            page_size,
            len(result["value"]),
            result["total_count"],
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)

    # Fallback: the completed-files listing (historical behaviour), used when
    # AIDP has no channel/history support for this knowledge base.
    list_result, count_result = await asyncio.gather(
        run_blocking(
            "aidp-list-documents",
            list_aidp_docs_impl,
            server_url,
            api_key,
            kds_id,
            page,
            page_size,
            lane="control-io",
            owner="config",
        ),
        run_blocking(
            "aidp-document-count",
            _load_cached_doc_count,
            server_url,
            api_key,
            kds_id,
            lane="control-io",
            owner="config",
        ),
        return_exceptions=True,
    )

    if isinstance(list_result, BaseException):
        raise list_result

    result = list_result
    page_items = result.get("value", []) if isinstance(result, dict) else []
    page_count = len(page_items) if isinstance(page_items, list) else 0

    if not isinstance(count_result, BaseException):
        total_count = count_result
        count_reliable = True
    else:
        logger.warning(
            "AIDP doc Count API failed for KB %s: %s", kds_id, count_result,
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
    # The completed-files listing carries no processing statuses, so nothing
    # keeps the frontend polling for this knowledge base.
    result["processing_count"] = 0
    if not count_reliable:
        result["total_reliable"] = False
    logger.info(
        "AIDP document list timing: total_ms=%.1f kb_id=%s page=%d page_size=%d "
        "page_count=%d total_count=%d total_reliable=%s source=completed",
        (time.perf_counter() - started_at) * 1000,
        kds_id,
        page,
        page_size,
        page_count,
        int(total_count),
        count_reliable,
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_mgmt_router.post("/knowledge-bases/{kds_id}/documents/remove")
async def remove_documents(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    body: RemoveAidpDocumentsRequest,
) -> JSONResponse:
    """Remove AIDP documents."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")

    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-remove-documents",
        remove_aidp_docs_impl,
        server_url,
        api_key,
        kds_id,
        [str(file_uuid) for file_uuid in body.file_uuids],
        lane="control-io",
        owner="config",
    )

    success_list = result["success_list"]
    if success_list:
        invalidate_aidp_kb_detail_cache(server_url, api_key, kds_id)
        invalidate_aidp_doc_count_cache(server_url, api_key, kds_id)
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_mgmt_router.post("/knowledge-bases/{kds_id}/documents/download")
async def download_document(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    body: DownloadAidpDocumentRequest,
) -> StreamingResponse:
    """Proxy an AIDP document as a binary attachment."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="READ")

    server_url, api_key = _credentials()
    aidp_response = await stream_aidp_doc_impl(
        server_url,
        api_key,
        kds_id,
        str(body.file_uuid),
    )
    response_headers = {
        "Content-Disposition": aidp_response.headers["Content-Disposition"],
        "X-File-Size": aidp_response.headers["X-File-Size"],
    }

    return StreamingResponse(
        aidp_response.aiter_bytes(),
        media_type=aidp_response.headers["Content-Type"],
        headers=response_headers,
        background=BackgroundTask(aidp_response.aclose),
    )


@aidp_mgmt_router.patch("/aidp-permissions/{kds_id}")
async def set_permission(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    body: SetPermissionRequest,
) -> JSONResponse:
    """Save local permissions first, then synchronize supplied metadata changes."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")

    if _is_user_role(user_id, tenant_id) and body.ingroup_permission != PRIVATE:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="USER role can only manage PRIVATE personal knowledge bases",
        )

    if body.ingroup_permission not in {EDIT, READ_ONLY, PRIVATE}:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f"Unsupported ingroup_permission: {body.ingroup_permission!r}",
        )

    if body.ingroup_permission == PRIVATE:
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

    metadata = body.model_dump(include={"name", "description"}, exclude_none=True)
    if "name" in metadata:
        metadata["name"] = metadata["name"].strip()
        if not metadata["name"]:
            raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Name must not be blank")
    result = await asyncio.to_thread(
        save_kb_settings,
        kb_id=kds_id,
        tenant_id=tenant_id,
        user_id=user_id,
        ingroup_permission=body.ingroup_permission,
        group_ids=final_group_ids,
        metadata=metadata,
        server_url=AIDP_SERVER_URL,
        api_key=AIDP_API_KEY,
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


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
