# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Per-knowledge-base AIDP sensitive-word routes.

The sensitive-word management surface is split out of the legacy management
router so the feature has one focused route module, mirroring the folder
routes. The public Nexent paths are unchanged.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Annotated, Literal, NoReturn

from fastapi import APIRouter, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from nexent.core.concurrency import run_blocking
from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from ext_components.aidp.apps.aidp_mgmt_common import _auth, _credentials
from ext_components.aidp.consts.aidp_exceptions import AidpSensitiveWordError
from ext_components.aidp.services import aidp_permission_service as perms
from ext_components.aidp.services.aidp_sensitive_word_service import (
    create_sensitive_word_impl,
    delete_sensitive_word_impl,
    get_sensitive_word_impl,
    list_sensitive_words_impl,
    update_sensitive_word_impl,
)


aidp_sensitive_word_router = APIRouter()


class CreateSensitiveWordRequest(BaseModel):
    """Body for creating one custom sensitive word."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    word: str = Field(..., min_length=1, max_length=64, description="Word or phrase to match")
    mode: Literal["BLACK", "WHITE"] = Field(..., description="BLACK blocks, WHITE allows")
    description: str = Field(
        ..., min_length=1, max_length=512, description="Why the word is in the dictionary"
    )


class UpdateSensitiveWordRequest(BaseModel):
    """Partial update for one custom sensitive word."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    word: str | None = Field(None, min_length=1, max_length=64)
    mode: Literal["BLACK", "WHITE"] | None = None
    description: str | None = Field(None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def require_at_least_one_field(self):
        if self.word is None and self.mode is None and self.description is None:
            raise ValueError("At least one sensitive word field must be provided")
        return self


def _raise_sensitive_word_upstream_error(exc: AidpSensitiveWordError) -> NoReturn:
    """Propagate AIDP's message while keeping business codes as diagnostics.

    Business codes describe the upstream result; they are not Nexent HTTP
    semantics. The response therefore carries the upstream message and details
    under the generic AIDP service error instead of remapping codes to
    409/404/403.
    """
    raise AppException(
        ErrorCode.AIDP_SERVICE_ERROR,
        str(exc),
        details={
            "upstream_status": exc.upstream_status,
            "upstream_code": exc.upstream_code,
        },
    ) from exc


@aidp_sensitive_word_router.get("/knowledge-bases/{kds_id}/sensitive-words")
async def list_sensitive_words(
    request: Request,
    kds_id: Annotated[str, Path(min_length=1, description="Knowledge base ID")],
    page: Annotated[int, Query(ge=1, description="Page number starting from 1")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Page size from 1 to 100")] = 10,
    keyword: Annotated[
        str | None,
        Query(max_length=200, description="Optional word filter forwarded to AIDP"),
    ] = None,
    mode: Annotated[
        Literal["BLACK", "WHITE"] | None,
        Query(description="Optional dictionary mode filter"),
    ] = None,
) -> JSONResponse:
    """Return one page of the knowledge base's sensitive word dictionary."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="READ")
    server_url, api_key = _credentials()
    try:
        result = await run_blocking(
            "aidp-sensitive-words",
            list_sensitive_words_impl,
            server_url,
            api_key,
            kds_id,
            page,
            page_size,
            keyword,
            mode,
            lane="control-io",
            owner="config",
        )
    except AidpSensitiveWordError as exc:
        _raise_sensitive_word_upstream_error(exc)
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_sensitive_word_router.post("/knowledge-bases/{kds_id}/sensitive-words")
async def create_sensitive_word(
    request: Request,
    kds_id: Annotated[str, Path(min_length=1, description="Knowledge base ID")],
    body: CreateSensitiveWordRequest,
) -> JSONResponse:
    """Create one custom word in the knowledge base dictionary."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")
    server_url, api_key = _credentials()
    try:
        result = await run_blocking(
            "aidp-create-sensitive-word",
            create_sensitive_word_impl,
            server_url,
            api_key,
            kds_id,
            body.word,
            body.mode,
            body.description,
            lane="control-io",
            owner="config",
        )
    except AidpSensitiveWordError as exc:
        _raise_sensitive_word_upstream_error(exc)
    return JSONResponse(status_code=HTTPStatus.CREATED, content=result)


@aidp_sensitive_word_router.get("/knowledge-bases/{kds_id}/sensitive-words/{word_id}")
async def get_sensitive_word(
    request: Request,
    kds_id: Annotated[str, Path(min_length=1, description="Knowledge base ID")],
    word_id: Annotated[str, Path(min_length=1, description="AIDP sensitive word ID")],
) -> JSONResponse:
    """Read the latest value of one word before editing it."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="READ")
    server_url, api_key = _credentials()
    try:
        result = await run_blocking(
            "aidp-sensitive-word-detail",
            get_sensitive_word_impl,
            server_url,
            api_key,
            kds_id,
            word_id,
            lane="control-io",
            owner="config",
        )
    except AidpSensitiveWordError as exc:
        _raise_sensitive_word_upstream_error(exc)
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_sensitive_word_router.patch("/knowledge-bases/{kds_id}/sensitive-words/{word_id}")
async def update_sensitive_word(
    request: Request,
    kds_id: Annotated[str, Path(min_length=1, description="Knowledge base ID")],
    word_id: Annotated[str, Path(min_length=1, description="AIDP sensitive word ID")],
    body: UpdateSensitiveWordRequest,
) -> JSONResponse:
    """Update the supplied fields of one custom word."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")
    server_url, api_key = _credentials()
    try:
        result = await run_blocking(
            "aidp-update-sensitive-word",
            update_sensitive_word_impl,
            server_url,
            api_key,
            kds_id,
            word_id,
            body.model_dump(exclude_none=True),
            lane="control-io",
            owner="config",
        )
    except AidpSensitiveWordError as exc:
        _raise_sensitive_word_upstream_error(exc)
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_sensitive_word_router.delete("/knowledge-bases/{kds_id}/sensitive-words/{word_id}")
async def delete_sensitive_word(
    request: Request,
    kds_id: Annotated[str, Path(min_length=1, description="Knowledge base ID")],
    word_id: Annotated[str, Path(min_length=1, description="AIDP sensitive word ID")],
) -> Response:
    """Delete one custom word; AIDP confirms with an empty 204 response."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")
    server_url, api_key = _credentials()
    try:
        await run_blocking(
            "aidp-delete-sensitive-word",
            delete_sensitive_word_impl,
            server_url,
            api_key,
            kds_id,
            word_id,
            lane="control-io",
            owner="config",
        )
    except AidpSensitiveWordError as exc:
        _raise_sensitive_word_upstream_error(exc)
    return Response(status_code=HTTPStatus.NO_CONTENT)


__all__ = [
    "CreateSensitiveWordRequest",
    "UpdateSensitiveWordRequest",
    "aidp_sensitive_word_router",
]
