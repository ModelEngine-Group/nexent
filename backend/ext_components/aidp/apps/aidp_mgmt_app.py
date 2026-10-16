# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

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
import json
import logging
import time
from http import HTTPStatus
from typing import Annotated, List, Literal, Optional
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import APIRouter, File, HTTPException, Path, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from nexent.core.concurrency import run_blocking
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from starlette.background import BackgroundTask

from consts.const import AIDP_API_KEY, AIDP_SERVER_URL
from consts.error_code import ErrorCode
from consts.exceptions import AppException, UnauthorizedError
from database.user_tenant_db import get_user_role_by_tenant
from ext_components.aidp.consts.aidp_exceptions import (
    AidpGroupValidationError,
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
)
from ext_components.aidp.services.aidp_service import (
    _timestamp_to_iso,
    count_aidp_docs_impl,
    create_aidp_kb_impl,
    delete_aidp_kb_impl,
    get_aidp_graph_template_impl,
    get_aidp_kb_impl,
    list_aidp_channels_impl,
    list_aidp_doc_history_impl,
    list_aidp_docs_impl,
    list_aidp_models_impl,
    merge_graph_config_update,
    remove_aidp_docs_impl,
    retry_aidp_docs_impl,
    select_aidp_channel,
    stream_aidp_doc_impl,
    stream_aidp_preview_impl,
    update_aidp_kb_impl,
    upload_aidp_docs_impl,
)
from utils import auth_utils as auth_utils_module


aidp_mgmt_router = APIRouter(prefix="/aidp-mgmt")
logger = logging.getLogger("aidp_mgmt_app")

AIDP_MAX_UPLOAD_FILE_COUNT = 50
AIDP_SMALL_FILE_MAX_SIZE_BYTES = 20 * 1024 * 1024
AIDP_OTHER_FILE_MAX_SIZE_BYTES = 1024 * 1024 * 1024
AIDP_SMALL_FILE_EXTENSIONS = {"txt", "json", "md", "html", "xls", "xlsx", "csv"}


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

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Knowledge base name (required)")
    description: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Knowledge base description (required)",
    )
    embedding_model: str = Field(..., min_length=1, description="Embedding model identifier")
    chunk_token_num: int = Field(1024, ge=256, le=4096, strict=True, description="Chunk size in tokens")
    chunk_overlap_num: int = Field(128, ge=0, strict=True, description="Chunk overlap in tokens")
    vlm_model: str = Field("", description="VLM model identifier for caption generation")
    is_personal: int = Field(0, ge=0, le=1, description="Personal KB flag, int 0 or 1")
    topk: int = Field(10, ge=1, le=100, strict=True, description="Top-K retrieval count")
    similarity: float = Field(0.6, ge=0, le=1, description="Similarity score threshold")
    caption_enable: int = Field(0, ge=0, le=1, strict=True, description="Caption generation toggle, int 0 or 1")
    chunk_mode: int = Field(
        0, ge=0, le=1, strict=True, description="Chunking mode: 0 smart splitting, 1 legal clauses"
    )
    is_exist_graph: bool = Field(
        False, description="Whether knowledge graph extraction is enabled for this KB"
    )
    graph_config: Optional[dict] = Field(
        None,
        description=(
            "Structured graph configuration. The service validates it and serializes it into the "
            "AIDP graph_config string; it is omitted entirely when the graph is disabled."
        ),
    )
    # Nexent-side permission payload. Never forwarded to AIDP.
    ingroup_permission: Optional[str] = Field(
        "READ_ONLY",
        description="Permission level for authorised groups: EDIT / READ_ONLY / PRIVATE",
    )
    group_ids: Optional[List[int]] = Field(
        None,
        description="Group IDs granted the in-group permission. Empty/ignored when PRIVATE.",
    )


    @field_validator("description", mode="before")
    @classmethod
    def trim_description(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("embedding_model")
    @classmethod
    def require_embedding_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Embedding model is required")
        return value

    @model_validator(mode="after")
    def validate_creation_settings(self):
        if self.chunk_overlap_num > self.chunk_token_num / 2:
            raise ValueError("chunk_overlap_num must not exceed half of chunk_token_num")
        if self.caption_enable and not self.vlm_model.strip():
            raise ValueError("VLM model is required when caption generation is enabled")
        return self


class UpdateKbRequest(BaseModel):
    """Request body for updating a knowledge base."""

    name: Optional[str] = Field(None, description="Knowledge base name")
    description: Optional[str] = Field(None, description="Knowledge base description")
    chunk_mode: Optional[int] = Field(None, ge=0, le=1, description="Chunk mode: 0 smart, 1 legal")
    topk: Optional[int] = Field(None, ge=1, le=100, description="Vector retrieval Top K")
    caption_enable: Optional[int] = Field(
        None, ge=0, le=1, description="Caption (VLM) generation toggle, int 0 or 1"
    )
    vlm_model: Optional[str] = Field(None, description="VLM model identifier for caption generation")
    is_exist_graph: Optional[bool] = Field(
        None,
        description=(
            "Disable the knowledge graph. Permanent: once disabled the graph "
            "cannot be re-enabled and its configuration is locked."
        ),
    )
    graph_config: Optional[dict] = Field(
        None,
        description=(
            "Partial graph configuration update with native-typed values for any "
            "subset of the editable fields (llm_model_name str, "
            "retrieve_subgraph_hop int 1-3, no_think_mode / synonym_merge_enable "
            "/ disambiguation_enable bool). Merged into the stored AIDP "
            "graph_config string; requires the graph to be enabled."
        ),
    )


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


class RetryAidpDocumentsRequest(BaseModel):
    """AIDP accepts one or more failed file UUIDs in a single retry request."""

    file_uuids: List[UUID] = Field(..., min_length=1)


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


def _normalize_kb_config_fields(detail: dict) -> dict:
    """Extract configuration fields the frontend expects from the AIDP detail response.

    AIDP stores chunking and embedding configuration inside ``kms_config_str``
    (a JSON string) and uses ``top_k`` instead of ``topk``. The frontend reads
    ``chunk_mode``, ``embedding_model``, ``topk``, ``similarity``, ``vlm_model``,
    ``caption_enable``, ``chunk_token_num`` and ``chunk_overlap_num`` as
    top-level fields. Without this normalization every configuration field
    on the detail "Information" tab renders as unknown ("-").
    """
    if not isinstance(detail, dict):
        return detail

    # Parse kms_config_str and merge its keys as top-level fields, but never
    # overwrite a value already present at the top level (the top-level value
    # is more authoritative if AIDP ever starts returning it natively).
    raw_kms = detail.get("kms_config_str")
    if isinstance(raw_kms, str) and raw_kms.strip():
        try:
            kms = json.loads(raw_kms)
            if isinstance(kms, dict):
                for key, value in kms.items():
                    if key not in detail or detail[key] is None:
                        detail[key] = value
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse kms_config_str for KB %s", detail.get("kds_id"))

    # Map AIDP's top_k -> topk (the frontend / create payload field name).
    if "topk" not in detail or detail["topk"] is None:
        top_k = detail.get("top_k")
        if top_k is not None:
            detail["topk"] = top_k

    # Derive is_multimodal from caption_enable when not already present.
    if "is_multimodal" not in detail or detail["is_multimodal"] is None:
        detail["is_multimodal"] = _infer_is_multimodal(detail)

    # Normalize the graph configuration for the frontend. AIDP serializes the
    # three graph toggles as "是"/"否" and the hop count as a string, while the
    # detail view and its inline editors expect native booleans and numbers.
    graph = detail.get("graph_config")
    if isinstance(graph, str) and graph.strip():
        try:
            graph = json.loads(graph)
        except (json.JSONDecodeError, ValueError):
            graph = None
    if isinstance(graph, dict):
        for key in (
            "no_think_mode",
            "synonym_merge_enable",
            "disambiguation_enable",
        ):
            if graph.get(key) == "是":
                graph[key] = True
            elif graph.get(key) == "否":
                graph[key] = False
        hop = graph.get("retrieve_subgraph_hop")
        if isinstance(hop, str) and hop.strip().isdigit():
            graph["retrieve_subgraph_hop"] = int(hop.strip())
        detail["graph_config"] = graph
        # AIDP nests the graph LLM model inside graph_config; lift it to the
        # top-level field the detail view renders when the top level has none.
        top_model = detail.get("llm_model_name")
        if not (isinstance(top_model, str) and top_model.strip()):
            nested_model = graph.get("llm_model_name")
            if isinstance(nested_model, str) and nested_model.strip():
                detail["llm_model_name"] = nested_model

    return detail


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
        "AIDP all-status file history unavailable for KB %s (%s); the upload-task list "
        "stays empty until the channel resolves",
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


def _history_reports_more(payload: dict) -> bool | None:
    """Whether the payload explicitly says another history page exists.

    Only unambiguous signals are trusted: this endpoint family reports
    ``total_count`` as the size of the current page elsewhere, so it cannot be
    read as a grand total. ``None`` means the payload does not say, and the
    caller has to ask for the next page to find out.
    """
    has_more = payload.get("has_more")
    if isinstance(has_more, bool):
        return has_more
    if "next_link" in payload:
        return bool(payload.get("next_link"))
    return None


@aidp_mgmt_router.get("/knowledge-bases/graph-template")
async def get_graph_template(
    request: Request,
    language: Literal["chinese", "english"] = "chinese",
) -> JSONResponse:
    await _auth(request)
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-graph-template", get_aidp_graph_template_impl, server_url, api_key, language,
        lane="control-io", owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


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
            "created_at": _timestamp_to_iso(row.get("create_time")),
            "permission": row.get("permission"),
            "ingroup_permission": row.get("ingroup_permission"),
            "group_ids": row.get("group_ids"),
            "created_by": row.get("owner_user_id"),
            "creator_name": row.get("creator_name"),
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

    from services.user_identity_service import enrich_cas_usernames

    await run_blocking(
        "aidp-list-creator-names", enrich_cas_usernames,
        items, {"creator_cas_username": "created_by"}, lane="control-io", owner="config",
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
        aidp_result = await run_blocking(
            "aidp-create-kb", create_aidp_kb_impl, server_url, api_key, aidp_payload,
            lane="control-io", owner="config",
        )
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
        raise HTTPException(
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
    detail = _normalize_kb_config_fields(detail)
    # Skip the Count call when the KB is already marked UNAVAILABLE - the
    # detail fetch failed, so AIDP is likely down and Count would fail too.
    # Escalating a second failure into a 5xx would prevent the UI from
    # showing the degraded detail view with the UNAVAILABLE status.
    if resource_status == "ACTIVE":
        detail["document_count"] = await run_blocking(
            "aidp-detail-document-count", count_aidp_docs_impl, server_url, api_key, kds_id,
            lane="control-io", owner="config",
        )
    detail["kds_id"] = kds_id
    detail["permission"] = decision.permission
    detail["resource_status"] = resource_status
    permission_record = await run_blocking(
        "aidp-detail-permission", aidp_permission_db.get_permission_by_kb_id,
        kds_id, tenant_id, lane="control-io", owner="config",
    ) or {}
    detail["ingroup_permission"] = permission_record.get("ingroup_permission")
    detail["group_ids"] = permission_record.get("group_ids") or []
    detail["created_by"] = permission_record.get("owner_user_id")
    detail["creator_name"] = permission_record.get("creator_name")
    from services.user_identity_service import enrich_cas_usernames

    await run_blocking(
        "aidp-detail-creator-name", enrich_cas_usernames,
        [detail], {"creator_cas_username": "created_by"}, lane="control-io", owner="config",
    )
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
            detail="At least one supported knowledge base field must be provided for update",
        )
    server_url, api_key = _credentials()

    if "is_exist_graph" in payload or "graph_config" in payload:
        # The graph switch is one-way: disabling keeps the stored graph data
        # but the flag can never return to enabled, and the configuration is
        # locked once the graph is off. Validate against the current AIDP
        # state so direct API callers cannot bypass the UI rules.
        current = await run_blocking(
            "aidp-update-graph-detail", _load_cached_kb_detail,
            server_url, api_key, kds_id,
            lane="control-io", owner="config",
        )
        if payload.get("is_exist_graph") is True:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="Knowledge graph cannot be re-enabled once disabled",
            )
        if not current.get("is_exist_graph"):
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail=(
                    "Knowledge graph is disabled for this knowledge base; "
                    "graph settings are locked"
                ),
            )
        graph_updates = payload.pop("graph_config", None)
        if graph_updates is not None:
            payload["graph_config"] = merge_graph_config_update(
                {}, graph_updates
            )
            # AIDP require is_exist_graph=true alongside any graph_config
            # edit; without it the PATCH returns HTTP 500. The graph is
            # confirmed enabled above, so echoing the flag is
            # safe and is not a re-enable attempt.
            payload["is_exist_graph"] = True

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
    keyword: Annotated[str | None, Query(max_length=200)] = None,
) -> JSONResponse:
    """List ingested files; Count provides the unfiltered pagination total."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="READ")
    server_url, api_key = _credentials()
    started_at = time.perf_counter()
    normalized_keyword = (keyword or "").strip()

    if normalized_keyword:
        result = await run_blocking(
            "aidp-list-documents", list_aidp_docs_impl, server_url, api_key,
            kds_id, page, page_size, normalized_keyword,
            lane="control-io", owner="config",
        )
        total_count = None
    else:
        result, total_count = await asyncio.gather(
            run_blocking(
                "aidp-list-documents", list_aidp_docs_impl, server_url, api_key,
                kds_id, page, page_size,
                lane="control-io", owner="config",
            ),
            run_blocking(
                "aidp-document-count", count_aidp_docs_impl, server_url, api_key, kds_id,
                lane="control-io", owner="config",
            ),
        )

    if not isinstance(result, dict) or not isinstance(result.get("value"), list):
        raise AppException(ErrorCode.AIDP_RESPONSE_ERROR, "Unexpected AIDP document list response format")
    has_more = bool(result.get("next_link"))
    # Count is queried fresh, never from the 30-second cache. Search has no
    # filtered Count endpoint, so next_link drives its simple pagination.
    result.update({
        "total_count": total_count if total_count is not None else (page - 1) * page_size + len(result["value"]),
        "has_more": has_more,
        "total_reliable": total_count is not None,
    })
    logger.info(
        "AIDP document list timing: total_ms=%.1f kb_id=%s page=%d page_size=%d "
        "page_count=%d total_count=%s has_more=%s",
        (time.perf_counter() - started_at) * 1000, kds_id, page, page_size,
        len(result["value"]), total_count, has_more,
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


def _build_inline_disposition(file_name: str) -> str:
    """Build an ``inline`` disposition for a name AIDP reports.

    AIDP only tells us the served name through ``X-File-Name``; non-ASCII names
    need the RFC 5987 ``filename*`` form, so an ASCII fallback is emitted too.
    """
    ascii_name = "".join(
        char if 32 <= ord(char) < 127 and char not in {'"', "\\"} else "_"
        for char in file_name
    )
    return (
        f'inline; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(file_name)}'
    )


def _stream_aidp_preview(aidp_response: httpx.Response) -> StreamingResponse:
    """Forward an AIDP preview stream together with the served file name.

    AIDP serves the original bytes for docx/xlsx/pptx/pdf/txt and a PDF
    conversion for every other format, so the served name differs from the
    uploaded one whenever a conversion happened. ``X-File-Name`` is how that
    name reaches the browser, which picks its renderer from its extension; the
    disposition is rebuilt from it so saving the stream keeps the same name.

    Response header values are latin-1 on the wire, while AIDP reports names
    verbatim (Chinese names included), so the name is URI-encoded: forwarding it
    unchanged would raise ``UnicodeEncodeError`` on the way out and fail the
    whole preview. Encoding every name keeps the rule single - the extension
    stays readable and the frontend decodes unconditionally.
    """
    response_headers: dict[str, str] = {}
    served_file_name = aidp_response.headers.get("X-File-Name")
    if served_file_name:
        response_headers["X-File-Name"] = quote(served_file_name, safe="")
        response_headers["Content-Disposition"] = _build_inline_disposition(
            served_file_name
        )
    else:
        response_headers["Content-Disposition"] = "inline"

    return StreamingResponse(
        aidp_response.aiter_bytes(),
        media_type=aidp_response.headers.get(
            "Content-Type", "application/octet-stream"
        ),
        headers=response_headers,
        background=BackgroundTask(aidp_response.aclose),
    )


@aidp_mgmt_router.get("/knowledge-bases/{kds_id}/documents/{file_uuid}/preview")
async def preview_document(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    file_uuid: Annotated[UUID, Path(description="AIDP file UUID")],
) -> StreamingResponse:
    """Stream one AIDP document inline so the browser can render it.

    AIDP serves the original bytes for the formats it can render itself and a
    PDF conversion for the rest; the frontend therefore resolves the format
    from the ``X-File-Name`` header this response carries, not from the name
    the document was uploaded with.
    """
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="READ")

    server_url, api_key = _credentials()
    aidp_response = await stream_aidp_preview_impl(
        server_url,
        api_key,
        kds_id,
        str(file_uuid),
    )
    return _stream_aidp_preview(aidp_response)
@aidp_mgmt_router.get("/knowledge-bases/{kds_id}/files")
async def list_ingested_files(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
    keyword: Annotated[str | None, Query(max_length=200)] = None,
) -> JSONResponse:
    """List only files AIDP confirms as ingested; upload history stays separate."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="READ")
    server_url, api_key = _credentials()
    normalized_keyword = (keyword or "").strip()

    # AIDP's list response exposes next_link as the authoritative paging signal;
    # total_count can be page-local. The Count endpoint is unfiltered, so use it
    # only for the unfiltered list and keep keyword results in simple paging mode.
    if normalized_keyword:
        list_result = await run_blocking(
            "aidp-list-ingested-files",
            list_aidp_docs_impl,
            server_url,
            api_key,
            kds_id,
            page,
            page_size,
            normalized_keyword,
            lane="control-io",
            owner="config",
        )
        count_result = None
    else:
        list_result, count_result = await asyncio.gather(
            run_blocking(
                "aidp-list-ingested-files",
                list_aidp_docs_impl,
                server_url,
                api_key,
                kds_id,
                page,
                page_size,
                None,
                lane="control-io",
                owner="config",
            ),
            run_blocking(
                "aidp-ingested-file-count",
                _load_cached_doc_count,
                server_url,
                api_key,
                kds_id,
                lane="control-io",
                owner="config",
            ),
        )
    result = dict(list_result or {})
    rows = result.get("value") if isinstance(result.get("value"), list) else []
    total_reliable = isinstance(count_result, int) and not isinstance(count_result, bool)
    total = int(count_result) if total_reliable else (page - 1) * page_size + len(rows)
    reported_more = _history_reports_more(result)
    # An explicit next_link/has_more is authoritative even when the page is
    # short; the row count only infers the last page when AIDP provides no
    # paging signal at all, matching the /documents paging contract.
    has_more = (
        total > page * page_size
        if total_reliable
        else bool(reported_more) if reported_more is not None
        else len(rows) >= page_size
    )
    result.update({
        "total_count": total,
        "has_more": has_more,
        "total_reliable": total_reliable,
        "processing_count": 0,
    })
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_mgmt_router.get("/knowledge-bases/{kds_id}/upload-tasks")
async def list_upload_tasks(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
    keyword: Annotated[str | None, Query(max_length=200)] = None,
    status: Annotated[int, Query(ge=0, le=5)] = 0,
) -> JSONResponse:
    """Read the recent AIDP upload history, separate from the ingested file list."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="READ")
    server_url, api_key = _credentials()
    normalized_keyword = (keyword or "").strip()
    channel = await run_blocking(
        "aidp-upload-task-channel",
        _resolve_doc_history_channel,
        server_url,
        api_key,
        kds_id,
        lane="control-io",
        owner="config",
    )
    history = {}
    if channel:
        history = await run_blocking(
            "aidp-upload-tasks",
            list_aidp_doc_history_impl,
            server_url,
            api_key,
            channel["fs_id"],
            channel["src_dir"],
            kds_id,
            None,
            page,
            page_size,
            status,
            normalized_keyword or None,
            lane="control-io",
            owner="config",
        )
    raw_items = history.get("value") if isinstance(history, dict) else None
    rows = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
    # AIDP History returns ``total_count`` as the current-page count, while
    # ``total_record_count`` is a global statistic computed before the
    # keyword/status filters are applied. It can therefore drive pagination
    # only for the unfiltered list; filtered queries keep
    # ``total_reliable=false`` and follow the upstream paging signal, while
    # the global count stays available in the summary statistics.
    filtered = bool(normalized_keyword) or status != 0
    raw_global_total = history.get("total_record_count") if isinstance(history, dict) else None
    total_reliable = (
        not filtered
        and isinstance(raw_global_total, int)
        and not isinstance(raw_global_total, bool)
    )
    total = int(raw_global_total) if total_reliable else (page - 1) * page_size + len(rows)
    reported_more = _history_reports_more(history) if isinstance(history, dict) else None
    has_more = (
        bool(reported_more)
        if reported_more is not None
        else total > page * page_size
    )

    def _history_count(field: str, fallback: int = 0) -> int:
        value = history.get(field) if isinstance(history, dict) else None
        return value if isinstance(value, int) and not isinstance(value, bool) else fallback

    stats = {
        "total": _history_count("total_record_count", total),
        "extracting": _history_count("processing_record_count"),
        "failed": _history_count("failed_record_count"),
        "success": _history_count("success_record_count"),
        "queued": _history_count("waiting_record_count"),
    }
    return JSONResponse(status_code=HTTPStatus.OK, content={
        "value": rows,
        "total_count": total,
        "has_more": has_more,
        "total_reliable": total_reliable,
        "stats": stats,
        "retention_days": 30,
    })


@aidp_mgmt_router.post("/knowledge-bases/{kds_id}/upload-tasks/retry")
async def retry_upload_tasks(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    body: RetryAidpDocumentsRequest,
) -> JSONResponse:
    """Retry selected failed tasks; the upstream request always carries a UUID array."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")
    file_uuids = list(dict.fromkeys(str(file_uuid) for file_uuid in body.file_uuids))
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-retry-upload-tasks",
        retry_aidp_docs_impl,
        server_url,
        api_key,
        kds_id,
        file_uuids,
        lane="control-io",
        owner="config",
    )
    invalidate_aidp_kb_detail_cache(server_url, api_key, kds_id)
    invalidate_aidp_doc_count_cache(server_url, api_key, kds_id)
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


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
    result = await run_blocking(
        "aidp-models", list_aidp_models_impl, server_url, api_key, service, app,
        lane="control-io", owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)
