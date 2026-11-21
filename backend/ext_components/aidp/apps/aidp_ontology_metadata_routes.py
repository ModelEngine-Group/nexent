# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Ontology Metadata definition routes."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse
from nexent.core.concurrency import run_blocking

from ext_components.aidp.apps.aidp_mgmt_common import _auth, _credentials
from ext_components.aidp.apps.aidp_ontology_common import (
    _find_metadata_field,
    _load_metadata_fields,
)
from ext_components.aidp.apps.aidp_ontology_models import (
    ChunkMetadataExportRequest,
    ChunkMetadataImportRequest,
    OntologyMetadataBatchUnbindSyncRequest,
    OntologyMetadataFieldRenameRequest,
    OntologyMetadataFieldRequest,
    OntologyMetadataUnbindRequest,
    OntologyTagSyncRequest,
)
from ext_components.aidp.apps.aidp_ontology_validation import (
    _bad_request,
    _domain_id_path,
    _require_ontology_manager,
)
from ext_components.aidp.services.aidp_ontology_common import METADATA_FIELD_LIMIT
from ext_components.aidp.services.aidp_ontology_metadata_service import (
    batch_unbind_metadata_impl,
    batch_unbind_metadata_sync_impl,
    create_ontology_metadata_field_impl,
    delete_ontology_metadata_field_impl,
    export_chunk_metadata_impl,
    import_chunk_metadata_impl,
    list_ontology_metadata_fields_impl,
    rename_ontology_metadata_field_impl,
    sync_ontology_tags_impl,
)
from ext_components.aidp.services.aidp_ontology_transform import (
    async_task_summary,
    is_async_task_payload,
)


logger = logging.getLogger("aidp_ontology_metadata_routes")
aidp_ontology_metadata_router = APIRouter()


@aidp_ontology_metadata_router.get("/domains/{domain_id}/metadata-fields")
async def list_metadata_fields(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 100,
    search: Annotated[str | None, Query(max_length=128)] = None,
) -> JSONResponse:
    """List metadata fields with Nexent-side search and pagination.

    AIDP has no keyword parameter on this endpoint, so fetch the bounded field
    set once and apply the filter/page here; the field limit keeps this small.
    """
    await _auth(request)
    server_url, api_key = _credentials()
    envelope = await run_blocking(
        "aidp-ontology-metadata-fields",
        list_ontology_metadata_fields_impl,
        server_url,
        api_key,
        domain_id,
        page=1,
        page_size=100,
        lane="control-io",
        owner="config",
    )
    fields = envelope["value"]
    all_count = len(fields)
    needle = (search or "").strip().lower()
    if needle:
        fields = [
            field
            for field in fields
            if needle in str(field.get("field_name") or "").lower()
        ]
    total = len(fields)
    start = (page - 1) * page_size
    envelope["value"] = fields[start : start + page_size]
    envelope["total_count"] = total
    envelope["has_more"] = page * page_size < total
    envelope["total_reliable"] = True
    envelope["all_count"] = all_count
    envelope["limit"] = METADATA_FIELD_LIMIT
    return JSONResponse(status_code=HTTPStatus.OK, content=envelope)


@aidp_ontology_metadata_router.post("/domains/{domain_id}/metadata-fields")
async def create_metadata_field(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    body: OntologyMetadataFieldRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    fields = await _load_metadata_fields(domain_id)
    if len(fields) >= METADATA_FIELD_LIMIT:
        raise _bad_request(
            f"每个本体库最多定义 {METADATA_FIELD_LIMIT} 个 Metadata 字段"
        )
    if any(item.get("field_name") == body.field_name for item in fields):
        raise _bad_request("字段名在该本体库中已存在")
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-metadata-create",
        create_ontology_metadata_field_impl,
        server_url,
        api_key,
        domain_id,
        field_name=body.field_name,
        field_type=body.field_type,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={
            "id": result.get("id") or result.get("metadata_id"),
            "field_name": result.get("fieldName")
            or result.get("field_name")
            or body.field_name,
            "field_type": result.get("fieldType")
            or result.get("field_type")
            or body.field_type,
            "column_index": result.get("columnIndex") or result.get("column_index"),
        },
    )


@aidp_ontology_metadata_router.patch("/domains/{domain_id}/metadata-fields/{field_ref}")
async def rename_metadata_field(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    field_ref: Annotated[str, Path(..., min_length=1, max_length=63)],
    body: OntologyMetadataFieldRenameRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    fields = await _load_metadata_fields(domain_id)
    current = _find_metadata_field(fields, field_ref)
    if current is None:
        raise _bad_request("要重命名的字段不存在")
    if body.new_field_name == current.get("field_name"):
        raise _bad_request("新字段名与当前字段名相同")
    if any(item.get("field_name") == body.new_field_name for item in fields):
        raise _bad_request("字段名在该本体库中已存在")
    metadata_id = current.get("id")
    if metadata_id is None:
        raise _bad_request("AIDP 没有返回该字段的 MetadataId，无法按真实契约改名")
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-metadata-rename",
        rename_ontology_metadata_field_impl,
        server_url,
        api_key,
        domain_id,
        metadata_id=metadata_id,
        new_field_name=body.new_field_name,
        lane="control-io",
        owner="config",
    )
    if is_async_task_payload(result):
        acknowledged = async_task_summary(result)
        acknowledged["field_name"] = body.new_field_name
        acknowledged["id"] = metadata_id
        return JSONResponse(status_code=HTTPStatus.OK, content=acknowledged)
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={
            "id": metadata_id,
            "field_name": result.get("fieldName")
            or result.get("field_name")
            or body.new_field_name,
            "field_type": result.get("fieldType") or current.get("field_type"),
        },
    )


@aidp_ontology_metadata_router.post("/domains/{domain_id}/metadata-fields/batch-unbind")
async def batch_unbind_metadata_fields(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    body: OntologyMetadataUnbindRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    fields = await _load_metadata_fields(domain_id)
    resolved: list[int] = []
    for field_ref in body.metadata_ids:
        current = _find_metadata_field(fields, field_ref)
        if current is None or current.get("id") is None:
            raise _bad_request("部分字段缺少 MetadataId，无法解绑")
        resolved.append(int(current["id"]))
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-metadata-unbind",
        batch_unbind_metadata_impl,
        server_url,
        api_key,
        domain_id,
        metadata_ids=resolved,
        creator=user_id,
        lane="control-io",
        owner="config",
    )
    if is_async_task_payload(result):
        return JSONResponse(
            status_code=HTTPStatus.OK, content=async_task_summary(result)
        )
    return JSONResponse(status_code=HTTPStatus.OK, content={"success": True})


@aidp_ontology_metadata_router.delete(
    "/domains/{domain_id}/metadata-fields/{field_ref}"
)
async def delete_metadata_field(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    field_ref: Annotated[str, Path(..., min_length=1, max_length=63)],
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    fields = await _load_metadata_fields(domain_id)
    current = _find_metadata_field(fields, field_ref)
    if current is None:
        raise _bad_request("要删除的字段不存在")
    metadata_id = current.get("id")
    if metadata_id is None:
        raise _bad_request("AIDP 没有返回该字段的 MetadataId，无法按真实契约删除")
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-metadata-delete",
        delete_ontology_metadata_field_impl,
        server_url,
        api_key,
        domain_id,
        metadata_id,
        lane="control-io",
        owner="config",
    )
    if is_async_task_payload(result):
        acknowledged = async_task_summary(result)
        acknowledged["id"] = metadata_id
        acknowledged["field_name"] = current.get("field_name")
        return JSONResponse(status_code=HTTPStatus.OK, content=acknowledged)
    failed_kbs = result.get("failed_kbs") or []
    dropped_kbs = result.get("dropped_kbs") or []
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={
            "success": result.get("deleted") is not False,
            "deleted": result.get("deleted"),
            "failed_kbs": failed_kbs,
            "dropped_kbs": dropped_kbs,
            "partial_failure": bool(failed_kbs),
        },
    )


@aidp_ontology_metadata_router.post("/domains/{domain_id}/chunks/metadata/export")
async def export_chunk_metadata(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    body: ChunkMetadataExportRequest,
) -> JSONResponse:
    """Export one chunk's user metadata; empty ``metadata_json`` means none."""
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-export-chunk-metadata",
        export_chunk_metadata_impl,
        server_url,
        api_key,
        domain_id,
        kds_id=body.kds_id,
        chunk_id=body.chunk_id,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_ontology_metadata_router.post("/domains/{domain_id}/chunks/metadata/import")
async def import_chunk_metadata(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    body: ChunkMetadataImportRequest,
) -> JSONResponse:
    """Write user metadata onto chunks; AIDP reports per-chunk results."""
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-import-chunk-metadata",
        import_chunk_metadata_impl,
        server_url,
        api_key,
        domain_id,
        kds_id=body.kds_id,
        metadata_json=body.metadata_json,
        chunk_id_list=body.chunk_id_list,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_ontology_metadata_router.post(
    "/domains/{domain_id}/metadata/batch-unbind-sync"
)
async def batch_unbind_metadata_fields_sync(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    body: OntologyMetadataBatchUnbindSyncRequest,
) -> JSONResponse:
    """Run the synchronous metadata unbind; AIDP answers aggregate counts."""
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-ontology-metadata-unbind-sync",
        batch_unbind_metadata_sync_impl,
        server_url,
        api_key,
        domain_id,
        metadata_ids=body.metadata_id_list,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)


@aidp_ontology_metadata_router.post("/tags/sync")
async def sync_ontology_tags(
    request: Request,
    body: OntologyTagSyncRequest,
) -> JSONResponse:
    """Queue the domain-scoped auto-tagging task for the given knowledge bases."""
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-sync-ontology-tags",
        sync_ontology_tags_impl,
        server_url,
        api_key,
        kb_ids=body.kb_ids,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)
