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
    OntologyMetadataFieldRenameRequest,
    OntologyMetadataFieldRequest,
    OntologyMetadataUnbindRequest,
)
from ext_components.aidp.apps.aidp_ontology_validation import (
    _bad_request,
    _domain_id_path,
    _require_ontology_manager,
)
from ext_components.aidp.services.aidp_ontology_common import METADATA_FIELD_LIMIT
from ext_components.aidp.services.aidp_ontology_metadata_service import (
    batch_unbind_metadata_impl,
    create_ontology_metadata_field_impl,
    delete_ontology_metadata_field_impl,
    list_ontology_metadata_fields_impl,
    rename_ontology_metadata_field_impl,
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
) -> JSONResponse:
    await _auth(request)
    server_url, api_key = _credentials()
    envelope = await run_blocking(
        "aidp-ontology-metadata-fields",
        list_ontology_metadata_fields_impl,
        server_url,
        api_key,
        domain_id,
        page=page,
        page_size=page_size,
        lane="control-io",
        owner="config",
    )
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
            "column_index": result.get("columnIndex")
            or result.get("column_index"),
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
        return JSONResponse(status_code=HTTPStatus.OK, content=async_task_summary(result))
    return JSONResponse(status_code=HTTPStatus.OK, content={"success": True})


@aidp_ontology_metadata_router.delete("/domains/{domain_id}/metadata-fields/{field_ref}")
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
    return JSONResponse(status_code=HTTPStatus.OK, content={"success": True})

