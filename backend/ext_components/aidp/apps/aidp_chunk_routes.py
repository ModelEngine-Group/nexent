# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Per-knowledge-base AIDP document chunk routes.

The chunk surface (list, read, create, update, batch remove, file-scoped
search, chunk images) is split out of the legacy management router so the
feature has one focused route module, mirroring the folder and sensitive-word
routes. The public Nexent paths are unchanged.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Annotated, List

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from nexent.core.concurrency import run_blocking
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from ext_components.aidp.apps.aidp_mgmt_common import (
    AIDP_FILE_UUID_PATTERN,
    AidpFileUuid,
    _auth,
    _credentials,
)
from ext_components.aidp.apps.aidp_ontology_validation import MetadataJson
from ext_components.aidp.services import aidp_permission_service as perms
from ext_components.aidp.services.aidp_chunk_service import (
    AIDP_CHUNK_REMOVE_MAX_IDS,
    AIDP_CHUNK_TEXT_MAX_LENGTH,
    create_aidp_chunk_impl,
    get_aidp_chunk_impl,
    get_aidp_image_impl,
    list_aidp_chunks_impl,
    remove_aidp_chunks_impl,
    search_aidp_chunks_impl,
    update_aidp_chunk_impl,
    update_chunk_metadata_impl,
)


aidp_chunk_router = APIRouter()

def _normalize_chunk_text(value: str) -> str:
    """Trim chunk text and enforce the AIDP 1-10240 character contract.

    The AIDP contract counts characters, not bytes, and rejects an empty text.
    Both rules are enforced here so an invalid write never reaches AIDP; the
    returned value is the trimmed text that actually gets stored.
    """
    text = value.strip()
    if not text:
        raise ValueError("chunk_text must not be blank")
    if len(text) > AIDP_CHUNK_TEXT_MAX_LENGTH:
        raise ValueError(
            f"chunk_text must not exceed {AIDP_CHUNK_TEXT_MAX_LENGTH} characters"
        )
    return text


class CreateAidpChunkRequest(BaseModel):
    """Body for adding one chunk to a file."""

    model_config = ConfigDict(extra="forbid")

    file_uuid: AidpFileUuid = Field(..., description="AIDP file UUID the chunk belongs to")
    chunk_text: str = Field(..., description="Chunk text (1-10240 characters)")

    @field_validator("chunk_text")
    @classmethod
    def validate_chunk_text(cls, value: str) -> str:
        return _normalize_chunk_text(value)


class UpdateAidpChunkRequest(BaseModel):
    """Body for updating one chunk's text; no other field is writable."""

    model_config = ConfigDict(extra="forbid")

    chunk_text: str = Field(..., description="Chunk text (1-10240 characters)")

    @field_validator("chunk_text")
    @classmethod
    def validate_chunk_text(cls, value: str) -> str:
        return _normalize_chunk_text(value)


class RemoveAidpChunksRequest(BaseModel):
    """Body for removing chunks; AIDP accepts one batch of 1-2000 ids."""

    model_config = ConfigDict(extra="forbid")

    chunk_ids: List[Annotated[int, Field(strict=True, ge=0)]] = Field(
        ...,
        min_length=1,
        max_length=AIDP_CHUNK_REMOVE_MAX_IDS,
        description=f"Chunk ids (1-{AIDP_CHUNK_REMOVE_MAX_IDS} items)",
    )


AIDP_BATCH_METADATA_SYNC_MAX_IDS = 300
AIDP_BATCH_METADATA_FILE_MAX_IDS = 100


class BatchChunkMetadataRequest(BaseModel):
    """Body for a batch chunk-metadata edit; one id list is required.

    AIDP accepts either user metadata or entity tags in one request:
    ``metadata_json`` may carry ``null`` values to delete a field, while
    ``tag`` replaces the complete tag set (an empty list clears every tag).
    Field limits: at most 20 fields, keys <= 64 bytes, values <= 256 bytes.
    """

    model_config = ConfigDict(extra="forbid")

    od_id: int = Field(..., ge=0, description="Ontology domain that owns the fields")
    metadata_json: MetadataJson | None = Field(
        default=None,
        description="Field/value pairs; a null value deletes the field",
    )
    tag: List[str] | None = Field(
        default=None,
        description="Complete replacement tag set; [] clears every tag",
    )
    chunk_id_list: List[Annotated[int, Field(strict=True, ge=0)]] | None = Field(
        default=None, description="Chunk ids addressed directly"
    )
    file_uuid_list: List[AidpFileUuid] | None = Field(
        default=None,
        max_length=AIDP_BATCH_METADATA_FILE_MAX_IDS,
        description="Files whose chunks all receive the metadata",
    )

    @model_validator(mode="after")
    def validate_scope(self):
        if self.tag is not None:
            cleaned: list[str] = []
            for item in self.tag:
                if not isinstance(item, str) or not item.strip():
                    raise ValueError("tag entries must be non-empty strings")
                if item.strip() not in cleaned:
                    cleaned.append(item.strip())
            self.tag = cleaned
        if self.metadata_json is None and self.tag is None:
            raise ValueError("one of metadata_json or tag is required")
        if (self.chunk_id_list is None) == (self.file_uuid_list is None):
            raise ValueError(
                "exactly one of chunk_id_list or file_uuid_list is required"
            )
        if self.chunk_id_list is not None and not self.chunk_id_list:
            raise ValueError("chunk_id_list must not be empty")
        if self.file_uuid_list is not None and not self.file_uuid_list:
            raise ValueError("file_uuid_list must not be empty")
        return self


@aidp_chunk_router.get("/knowledge-bases/{kds_id}/chunks")
async def list_chunks(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    file_uuid: Annotated[str, Query(pattern=AIDP_FILE_UUID_PATTERN, description="AIDP file UUID")],
    page: Annotated[int, Query(ge=1, description="Page number starting from 1")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Page size from 1 to 100")] = 20,
) -> JSONResponse:
    """List the chunks AIDP generated for one file.

    AIDP addresses the list by ``file_uuid`` only: the contract has no keyword
    filter, so the page cannot offer a content search. Its ``next_link`` is
    returned on every page, including the last, and ``total_count`` is the
    current page's row count rather than a global total (both verified against
    the real 2026-11-18 deployment), so ``has_more`` is derived from the page
    being full instead of either field.
    """
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="READ")

    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-list-chunks",
        list_aidp_chunks_impl,
        server_url,
        api_key,
        kds_id,
        str(file_uuid),
        page,
        page_size,
        lane="control-io",
        owner="config",
    )
    payload = dict(result or {})
    rows = payload.get("value")
    if not isinstance(rows, list):
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            "Unexpected AIDP chunk list response format",
        )
    # A full page means another page may exist; a short page (or an empty
    # out-of-range page) is the last one. This deliberately over-reports one
    # page when the row count is an exact multiple of page_size; the following
    # fetch then returns an empty page and stops.
    total = (page - 1) * page_size + len(rows)
    payload.update({
        "total_count": total,
        "has_more": len(rows) >= page_size,
        "total_reliable": False,
    })
    return JSONResponse(status_code=HTTPStatus.OK, content=payload)


@aidp_chunk_router.get("/knowledge-bases/{kds_id}/chunks/search")
async def search_chunks(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    file_uuid: Annotated[str, Query(pattern=AIDP_FILE_UUID_PATTERN, description="AIDP file UUID")],
    file_name: Annotated[
        str,
        Query(
            min_length=1,
            max_length=255,
            description="Current file name used by the AIDP file-name filter",
        ),
    ],
    query: Annotated[
        str,
        Query(min_length=1, max_length=2048, description="Chunk content query"),
    ],
    topk: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JSONResponse:
    """Search chunk content in one file through AIDP FusionSearch.

    AIDP's list endpoint has no keyword parameter, so this dedicated route
    builds a FusionSearch request constrained by the documented
    ``metadata_condition.original_file_name`` filter. ``file_uuid`` keeps the
    route tied to the current file; ``file_name`` is the filter value.
    """
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="READ")

    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-search-chunks",
        search_aidp_chunks_impl,
        server_url,
        api_key,
        kds_id,
        file_name,
        query,
        topk,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_chunk_router.get("/knowledge-bases/{kds_id}/images/{file_id}")
async def view_chunk_image(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    file_id: Annotated[
        str,
        Path(
            pattern=r"^[A-Za-z0-9_-]+\.png$",
            description="AIDP image file id: {file_ino_no}_{image_uuid}.png",
        ),
    ],
) -> Response:
    """Return an image chunk's picture as PNG bytes through AIDP ViewImage.

    The ``file_id`` is derived on the page from the chunk's ``file_url``
    (``{kds_id}/{file_ino_no}/{image_uuid}.png`` → ``{file_ino_no}_
    {image_uuid}.png``). The upstream answer is binary, so the proxy returns
    the bytes as PNG instead of a JSON body.
    """
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="READ")

    server_url, api_key = _credentials()
    content = await run_blocking(
        "aidp-view-image",
        get_aidp_image_impl,
        server_url,
        api_key,
        kds_id,
        file_id,
        lane="control-io",
        owner="config",
    )
    return Response(
        content=content,
        media_type="image/png",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@aidp_chunk_router.post("/knowledge-bases/{kds_id}/chunks")
async def create_chunk(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    body: CreateAidpChunkRequest,
) -> JSONResponse:
    """Add one text chunk to a file; only ``file_uuid`` and text are forwarded."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")

    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-create-chunk",
        create_aidp_chunk_impl,
        server_url,
        api_key,
        kds_id,
        str(body.file_uuid),
        body.chunk_text,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_chunk_router.delete("/knowledge-bases/{kds_id}/chunks")
async def remove_chunks(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    body: RemoveAidpChunksRequest,
) -> Response:
    """Remove up to 2000 chunks; AIDP receives a JSON body on POST /Chunks/Remove.

    AIDP answers ``204 No Content``, so this proxy mirrors the empty success
    response instead of inventing a result payload.
    """
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")

    server_url, api_key = _credentials()
    await run_blocking(
        "aidp-remove-chunks",
        remove_aidp_chunks_impl,
        server_url,
        api_key,
        kds_id,
        body.chunk_ids,
        lane="control-io",
        owner="config",
    )
    return Response(status_code=HTTPStatus.NO_CONTENT)


@aidp_chunk_router.patch("/knowledge-bases/{kds_id}/chunks/batch-metadata")
async def update_chunks_metadata(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    body: BatchChunkMetadataRequest,
) -> JSONResponse:
    """Apply user metadata to many chunks; AIDP answers per-chunk counts.

    The sync upstream route accepts at most 300 chunk ids; larger sets must
    use the async variant. Values are forwarded as sent: AIDP owns field
    validation against the ontology domain definition.
    """
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")
    if body.chunk_id_list is not None and (
        len(body.chunk_id_list) > AIDP_BATCH_METADATA_SYNC_MAX_IDS
    ):
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=(
                "chunk_id_list must not exceed "
                f"{AIDP_BATCH_METADATA_SYNC_MAX_IDS} ids on the sync route; "
                "use /chunks/batch-metadata-async for larger batches"
            ),
        )

    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-batch-chunk-metadata",
        update_chunk_metadata_impl,
        server_url,
        api_key,
        kds_id,
        od_id=body.od_id,
        metadata_json=body.metadata_json,
        tag=body.tag,
        chunk_id_list=body.chunk_id_list,
        file_uuid_list=body.file_uuid_list,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_chunk_router.patch("/knowledge-bases/{kds_id}/chunks/batch-metadata-async")
async def update_chunks_metadata_async(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    body: BatchChunkMetadataRequest,
) -> JSONResponse:
    """Queue a batch metadata edit; AIDP answers a task acceptance snapshot."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")

    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-batch-chunk-metadata-async",
        update_chunk_metadata_impl,
        server_url,
        api_key,
        kds_id,
        od_id=body.od_id,
        metadata_json=body.metadata_json,
        tag=body.tag,
        chunk_id_list=body.chunk_id_list,
        file_uuid_list=body.file_uuid_list,
        async_mode=True,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_chunk_router.get("/knowledge-bases/{kds_id}/chunks/{chunk_id}")
async def get_chunk(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    chunk_id: Annotated[int, Path(ge=0, description="AIDP chunk ID")],
) -> JSONResponse:
    """Read one chunk's full text and read-only metadata."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="READ")

    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-get-chunk",
        get_aidp_chunk_impl,
        server_url,
        api_key,
        kds_id,
        chunk_id,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_chunk_router.patch("/knowledge-bases/{kds_id}/chunks/{chunk_id}")
async def update_chunk(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    chunk_id: Annotated[int, Path(ge=0, description="AIDP chunk ID")],
    body: UpdateAidpChunkRequest,
) -> JSONResponse:
    """Update one chunk's text; AIDP declares no other writable field."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")

    server_url, api_key = _credentials()
    # TEXT and TABLE chunks are editable: real AIDP accepts a table chunk's
    # HTML text on PATCH (verified 2026-11-18). IMAGE chunks stay read-only —
    # their chunk_text is a VLM-generated description, and editing it is not
    # validated upstream. The check uses the type AIDP reports, never the
    # source file's extension or upload size class.
    current = await run_blocking(
        "aidp-get-chunk-for-update",
        get_aidp_chunk_impl,
        server_url,
        api_key,
        kds_id,
        chunk_id,
        lane="control-io",
        owner="config",
    )
    chunk_type = str((current or {}).get("chunk_type") or "").strip().upper()
    if chunk_type not in ("TEXT", "TABLE"):
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Only TEXT and TABLE chunks can be edited",
        )

    result = await run_blocking(
        "aidp-update-chunk",
        update_aidp_chunk_impl,
        server_url,
        api_key,
        kds_id,
        chunk_id,
        body.chunk_text,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)
