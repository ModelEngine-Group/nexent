# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Ontology JSON import/export routes."""
from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from nexent.core.concurrency import run_blocking

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from ext_components.aidp.apps.aidp_mgmt_common import _auth, _credentials
from ext_components.aidp.apps.aidp_ontology_models import (
    OntologyExportRequest,
    OntologyImportRequest,
)
from ext_components.aidp.apps.aidp_ontology_validation import (
    _bad_request,
    _domain_id_path,
    _numeric_domain_id,
    _require_ontology_manager,
)
from ext_components.aidp.services.aidp_ontology_batch_service import (
    export_ontology_impl,
    import_ontology_impl,
)
from ext_components.aidp.services.aidp_ontology_domain_service import (
    get_ontology_domain_impl,
)
from ext_components.aidp.services.aidp_ontology_transform import (
    OntologyImportValidationError,
    async_task_summary,
    build_import_request,
    is_async_task_payload,
    normalize_export_result,
    normalize_import_errors,
    normalize_import_result,
    sanitize_export_filename,
)


logger = logging.getLogger("aidp_ontology_batch_routes")
aidp_ontology_batch_router = APIRouter()


@aidp_ontology_batch_router.post("/domains/{domain_id}/export")
async def export_ontology(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    body: OntologyExportRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    _numeric_domain_id(domain_id)
    server_url, api_key = _credentials()
    payload = await run_blocking(
        "aidp-ontology-export",
        export_ontology_impl,
        server_url,
        api_key,
        domain_id,
        include_properties=body.include_properties,
        include_relations=body.include_relations,
        kind=body.kind,
        lane="control-io",
        owner="config",
    )
    try:
        normalized = normalize_export_result(payload)
    except ValueError as error:
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            "AIDP 导出响应缺少本体库数据",
            details={"operation": "export-ontology"},
        ) from error
    if normalized.get("accepted"):
        return JSONResponse(status_code=HTTPStatus.OK, content=normalized)
    try:
        domain = await run_blocking(
            "aidp-ontology-export-domain",
            get_ontology_domain_impl,
            server_url,
            api_key,
            domain_id,
            lane="control-io",
            owner="config",
        )
    except AppException as error:
        logger.warning("AIDP export filename lookup failed for domain %s: %s", domain_id, error)
        domain = {}
    domain_name = domain.get("name") or domain.get("display_name") or ""
    normalized["filename"] = sanitize_export_filename(
        domain_name, fallback=f"ontology-{domain_id}"
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=normalized)


@aidp_ontology_batch_router.post("/domains/{domain_id}/import")
async def import_ontology(
    request: Request,
    domain_id: Annotated[str, _domain_id_path()],
    body: OntologyImportRequest,
) -> JSONResponse:
    user_id, tenant_id = await _auth(request)
    _require_ontology_manager(user_id, tenant_id)
    _numeric_domain_id(domain_id)
    server_url, api_key = _credentials()
    try:
        domain = await run_blocking(
            "aidp-ontology-import-domain",
            get_ontology_domain_impl,
            server_url,
            api_key,
            domain_id,
            lane="control-io",
            owner="config",
        )
    except AppException as error:
        logger.warning("AIDP import domain lookup failed for %s: %s", domain_id, error)
        domain = {}
    domain_name = (
        domain.get("name") or domain.get("display_name") or domain.get("od_name")
    )
    if not isinstance(domain_name, str) or not domain_name.strip():
        raise _bad_request("无法读取目标本体库名称，导入已取消")
    try:
        import_body, counts = build_import_request(body.document, domain_name.strip())
    except OntologyImportValidationError as error:
        logger.info(
            "Ontology import file %s rejected before submit with %d validation errors",
            body.file_name,
            len(error.errors),
        )
        raise _bad_request("导入文件校验失败", error.errors) from error

    payload = await run_blocking(
        "aidp-ontology-import",
        import_ontology_impl,
        server_url,
        api_key,
        domain_id,
        import_body,
        lane="control-io",
        owner="config",
    )
    if is_async_task_payload(payload):
        result = async_task_summary(payload)
        result["counts"] = counts
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    result = normalize_import_result(payload)
    result["counts"] = counts
    result["errors"] = normalize_import_errors(payload)
    return JSONResponse(status_code=HTTPStatus.OK, content=result)

