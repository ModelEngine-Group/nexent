# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Chunk metadata annotation and inspection routes."""
from __future__ import annotations

import asyncio
import logging
from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse
from nexent.core.concurrency import run_blocking

from contracts.errors.exceptions import AppException
from ext_components.aidp.apps.aidp_mgmt_common import _auth, _credentials
from ext_components.aidp.apps.aidp_ontology_common import (
    _load_metadata_fields,
)
from ext_components.aidp.apps.aidp_ontology_models import (
    ChunkMetadataUpdateRequest,
)
from ext_components.aidp.apps.aidp_ontology_validation import (
    _bad_request,
)
from ext_components.aidp.services import aidp_permission_service as perms
from ext_components.aidp.services.aidp_ontology_binding_service import (
    list_ontology_bindings_impl,
)
from ext_components.aidp.services.aidp_ontology_common import (
    METADATA_FIELD_LIMIT,
    METADATA_KEY_MAX_BYTES,
)
from ext_components.aidp.services.aidp_ontology_metadata_service import (
    batch_set_chunk_metadata_impl,
    get_aidp_chunk_impl,
    list_aidp_chunks_impl,
    metadata_value_error,
)


logger = logging.getLogger("aidp_ontology_chunk_routes")
aidp_ontology_chunk_router = APIRouter()


@aidp_ontology_chunk_router.patch("/knowledge-bases/{kds_id}/chunks/metadata")
async def batch_update_chunk_metadata(
    request: Request,
    kds_id: Annotated[str, Path(..., min_length=1, max_length=128)],
    body: ChunkMetadataUpdateRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="EDIT")

    server_url, api_key = _credentials()
    bindings = await run_blocking(
        "aidp-chunk-metadata-binding",
        list_ontology_bindings_impl,
        server_url,
        api_key,
        kds_id=kds_id,
        lane="control-io",
        owner="config",
    )
    if not any(binding["od_id"] == body.domain_id for binding in bindings):
        raise _bad_request("该知识库未绑定当前本体库，不能标注 Metadata")

    fields = await _load_metadata_fields(body.domain_id)
    field_types = {
        item.get("field_name"): item.get("field_type")
        for item in fields
        if item.get("field_name")
    }
    metadata = body.metadata
    if len(metadata) > METADATA_FIELD_LIMIT:
        raise _bad_request(
            f"单次最多标注 {METADATA_FIELD_LIMIT} 个字段"
        )
    errors: list[dict[str, Any]] = []
    for key, value in metadata.items():
        if len(key.encode("utf-8")) > METADATA_KEY_MAX_BYTES:
            errors.append(
                {
                    "field": key,
                    "message": f"字段键不能超过 {METADATA_KEY_MAX_BYTES} 字节",
                }
            )
            continue
        field_type = field_types.get(key)
        if field_type is None:
            errors.append({"field": key, "message": "字段未在当前本体库中定义"})
            continue
        value_error = metadata_value_error(key, field_type, value)
        if value_error:
            errors.append({"field": key, "message": value_error})
    if errors:
        raise _bad_request("Metadata 校验失败", errors)

    async def _check_chunk(chunk_id: int | str) -> dict[str, Any] | None:
        try:
            await run_blocking(
                "aidp-chunk-ownership",
                get_aidp_chunk_impl,
                server_url,
                api_key,
                kds_id,
                str(chunk_id),
                lane="control-io",
                owner="config",
            )
            return None
        except AppException as error:
            upstream_status = (error.details or {}).get("upstream_status")
            if upstream_status == HTTPStatus.NOT_FOUND:
                return {"chunk_id": chunk_id, "message": "Chunk 不属于该知识库"}
            raise

    ownership_errors = [
        error for error in await asyncio.gather(*[_check_chunk(item) for item in body.chunk_ids])
        if error is not None
    ]
    if ownership_errors:
        raise _bad_request("部分 Chunk 不属于该知识库", ownership_errors)

    result = await run_blocking(
        "aidp-chunk-metadata-batch",
        batch_set_chunk_metadata_impl,
        server_url,
        api_key,
        kds_id,
        domain_id=body.domain_id,
        metadata=metadata,
        chunk_ids=body.chunk_ids,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_ontology_chunk_router.get("/knowledge-bases/{kds_id}/chunks")
async def list_chunks(
    request: Request,
    kds_id: Annotated[str, Path(..., min_length=1, max_length=128)],
    file_uuid: Annotated[str, Query(min_length=1, max_length=128)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="READ")
    server_url, api_key = _credentials()
    envelope = await run_blocking(
        "aidp-chunk-list",
        list_aidp_chunks_impl,
        server_url,
        api_key,
        kds_id,
        file_uuid=file_uuid,
        page=page,
        page_size=page_size,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=envelope)


@aidp_ontology_chunk_router.get("/knowledge-bases/{kds_id}/chunks/{chunk_id}")
async def get_chunk(
    request: Request,
    kds_id: Annotated[str, Path(..., min_length=1, max_length=128)],
    chunk_id: Annotated[str, Path(..., min_length=1, max_length=64)],
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="READ")
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-chunk-get",
        get_aidp_chunk_impl,
        server_url,
        api_key,
        kds_id,
        chunk_id,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)

