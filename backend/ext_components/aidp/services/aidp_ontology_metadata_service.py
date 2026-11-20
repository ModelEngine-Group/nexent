# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Ontology Metadata definition and Chunk annotation proxy operations."""
from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from contracts.errors.exceptions import AppException
from ext_components.aidp.services.aidp_ontology_common import (
    _METADATA_VALUE_MAX_BYTES,
    _domain_id_value,
    _get_chunks_path,
    _get_legacy_chunks_path,
    _get_ontology_path,
    _list_envelope,
    _log_business_failure,
    _ontology_request,
)


logger = logging.getLogger("aidp_ontology_metadata_service")


def _normalize_field(item: dict[str, Any]) -> dict[str, Any]:
    """Project the confirmed AIDP metadata-field shape.

    AIDP returns only id/field_name/field_type/column_index for definitions;
    anything else the local mock used to carry is intentionally dropped.
    """
    return {
        "id": item.get("id") or item.get("metadata_id"),
        "field_name": item.get("fieldName") or item.get("field_name"),
        "field_type": item.get("fieldType") or item.get("field_type"),
        "column_index": item.get("columnIndex") or item.get("column_index"),
    }


def list_ontology_metadata_fields_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    *,
    page: int = 1,
    page_size: int = 100,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    payload = _ontology_request(
        server_url,
        api_key,
        "GET",
        f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}/Metadata",
        operation="list-ontology-metadata-fields",
        params={"page": page, "page_size": page_size},
    )
    _log_business_failure(payload, "list-ontology-metadata-fields")
    envelope = _list_envelope(payload, page=page, page_size=page_size)
    envelope["value"] = [
        _normalize_field(item) for item in envelope["value"] if isinstance(item, dict)
    ]
    envelope["has_next"] = envelope["has_more"]
    return envelope


def create_ontology_metadata_field_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    *,
    field_name: str,
    field_type: str,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    payload = _ontology_request(
        server_url,
        api_key,
        "PUT",
        f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}/Metadata",
        operation="create-ontology-metadata-field",
        json_body={"fieldName": field_name, "fieldType": field_type},
    )
    _log_business_failure(payload, "create-ontology-metadata-field")
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else (payload if isinstance(payload, dict) else {})


def rename_ontology_metadata_field_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    *,
    metadata_id: str | int,
    new_field_name: str,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    payload = _ontology_request(
        server_url,
        api_key,
        "PATCH",
        f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}/Metadata/{metadata_id}",
        operation="rename-ontology-metadata-field",
        json_body={"fieldName": new_field_name},
    )
    _log_business_failure(payload, "rename-ontology-metadata-field")
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else (payload if isinstance(payload, dict) else {})


def delete_ontology_metadata_field_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    metadata_id: str | int,
    *,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Delete a definition, returning the raw upstream payload.

    AIDP may answer with a task receipt while it updates chunk metadata keys;
    the caller must distinguish that acknowledgment from completed deletion.
    """
    try:
        payload = _ontology_request(
            server_url,
            api_key,
            "DELETE",
            f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}/Metadata/{metadata_id}",
            operation="delete-ontology-metadata-field",
        )
        return payload if isinstance(payload, dict) else {}
    except AppException as error:
        upstream_status = (error.details or {}).get("upstream_status")
        if upstream_status == HTTPStatus.NOT_FOUND:
            return {}
        raise


def batch_unbind_metadata_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    *,
    metadata_ids: list[int],
    creator: str,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Submit AIDP's domain-wide asynchronous field unbind task.

    The proxy supplies the authenticated creator; the browser never chooses it.
    The response is only an acceptance snapshot (task_id/status/progress).
    """
    return _ontology_request(
        server_url,
        api_key,
        "POST",
        f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}/Metadata/BatchUnbindAsync",
        operation="batch-unbind-metadata",
        json_body={"metadata_id_list": metadata_ids, "creator": creator},
    )


def _chunk_request_with_fallback(
    server_url: str,
    api_key: str,
    method: str,
    kds_id: str,
    suffix: str,
    *,
    operation: str,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    tenant_id: str | None = None,
) -> Any:
    """Call the KB-side chunk route, retrying the tenant-scoped one on 404."""
    try:
        return _ontology_request(
            server_url,
            api_key,
            method,
            f"{_get_chunks_path(kds_id, tenant_id)}{suffix}",
            operation=operation,
            params=params,
            json_body=json_body,
        )
    except AppException as error:
        if (error.details or {}).get("upstream_status") != HTTPStatus.NOT_FOUND:
            raise
        return _ontology_request(
            server_url,
            api_key,
            method,
            f"{_get_legacy_chunks_path(kds_id, tenant_id)}{suffix}",
            operation=operation,
            params=params,
            json_body=json_body,
        )


def list_aidp_chunks_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    *,
    file_uuid: str,
    page: int = 1,
    page_size: int = 20,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    payload = _chunk_request_with_fallback(
        server_url,
        api_key,
        "GET",
        kds_id,
        "",
        operation="list-aidp-chunks",
        params={"file_uuid": file_uuid, "page": page, "page_size": page_size},
        tenant_id=tenant_id,
    )
    _log_business_failure(payload, "list-aidp-chunks")
    return _list_envelope(payload, page=page, page_size=page_size)


def get_aidp_chunk_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    chunk_id: str,
    *,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    payload = _chunk_request_with_fallback(
        server_url,
        api_key,
        "GET",
        kds_id,
        f"/{chunk_id}",
        operation="get-aidp-chunk",
        tenant_id=tenant_id,
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else (payload if isinstance(payload, dict) else {})


def batch_set_chunk_metadata_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    *,
    domain_id: str,
    metadata: dict[str, Any],
    chunk_ids: list[int | str],
    tenant_id: str | None = None,
) -> dict[str, Any]:
    payload = _chunk_request_with_fallback(
        server_url,
        api_key,
        "PATCH",
        kds_id,
        "/BatchMetadataJson",
        operation="batch-set-chunk-metadata",
        json_body={
            "od_id": _domain_id_value(domain_id),
            "metadata_json": metadata,
            "chunk_id_list": chunk_ids,
        },
        tenant_id=tenant_id,
    )
    _log_business_failure(payload, "batch-set-chunk-metadata")
    return normalize_batch_metadata_result(payload)


def normalize_batch_metadata_result(payload: Any) -> dict[str, Any]:
    """Normalize per-chunk success/failure results for the annotation drawer."""
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
    data = data if isinstance(data, dict) else {}
    # Confirmed contract answers counters, not per-chunk lists:
    # {kds_id, od_id, partial_failure, total_chunks, updated_chunks}.
    if "updated_chunks" in data or "total_chunks" in data:
        total_chunks = data.get("total_chunks")
        updated_chunks = data.get("updated_chunks")
        total_value = total_chunks if isinstance(total_chunks, int) and not isinstance(total_chunks, bool) else 0
        success_value = updated_chunks if isinstance(updated_chunks, int) and not isinstance(updated_chunks, bool) else 0
        failed_value = max(total_value - success_value, 0)
        return {
            "total": total_value,
            "success_count": success_value,
            "failed_count": failed_value,
            "partial_failure": bool(data.get("partial_failure")),
            "success_list": [],
            "failed_list": [],
        }
    success_raw = data.get("success_list") or data.get("success") or []
    failed_raw = data.get("failed_list") or data.get("failed") or []
    results_raw = data.get("results")
    if isinstance(results_raw, list) and not (success_raw or failed_raw):
        success_raw = []
        failed_raw = []
        for item in results_raw:
            if not isinstance(item, dict):
                failed_raw.append({"chunk_id": item, "message": "标注失败"})
                continue
            chunk_id = item.get("chunk_id") or item.get("chunkId") or item.get("id")
            status = str(item.get("status") or "").lower()
            success = item.get("success")
            if isinstance(success, bool):
                succeeded = success
            elif status:
                succeeded = status in {"success", "succeeded", "ok", "completed"}
            else:
                succeeded = not any(
                    item.get(key) for key in ("error", "message", "reason", "reason_zh")
                )
            if succeeded:
                success_raw.append({"chunk_id": chunk_id})
            else:
                failed_raw.append(
                    {
                        "chunk_id": chunk_id,
                        "message_zh": item.get("message_zh")
                        or item.get("message")
                        or item.get("reason_zh")
                        or item.get("reason")
                        or item.get("error")
                        or "标注失败",
                    }
                )
    success_list = [
        {
            "chunk_id": item.get("chunk_id") if isinstance(item, dict) else item,
        }
        for item in success_raw
    ] if isinstance(success_raw, list) else []
    failed_list = []
    if isinstance(failed_raw, list):
        for item in failed_raw:
            if isinstance(item, dict):
                failed_list.append(
                    {
                        "chunk_id": item.get("chunk_id") or item.get("id"),
                        "message": item.get("message_zh")
                        or item.get("message")
                        or item.get("reason_zh")
                        or item.get("reason")
                        or "标注失败",
                    }
                )
            else:
                failed_list.append({"chunk_id": item, "message": "标注失败"})
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    total = summary.get("total")
    if not isinstance(total, int):
        total = len(success_list) + len(failed_list)
    success_count = summary.get("success")
    if not isinstance(success_count, int):
        success_count = len(success_list)
    failed_count = summary.get("failed")
    if not isinstance(failed_count, int):
        failed_count = len(failed_list)
    return {
        "total": total,
        "success_count": success_count,
        "failed_count": failed_count,
        "success_list": success_list,
        "failed_list": failed_list,
    }


def metadata_value_error(field_name: str, field_type: str, value: Any) -> str | None:
    """Return a readable error when a value does not match its field type."""
    if isinstance(value, bool):
        return f"字段「{field_name}」不接受布尔值"
    if field_type == "string":
        if not isinstance(value, str):
            return f"字段「{field_name}」需要字符串值"
    elif field_type == "number":
        if not isinstance(value, (int, float)):
            return f"字段「{field_name}」需要数字值"
    elif field_type in ("date", "time"):
        if not isinstance(value, str) or not value.strip():
            return f"字段「{field_name}」需要日期文本值"
    else:
        return f"字段「{field_name}」的类型 {field_type} 不受支持"
    if isinstance(value, str):
        size = len(value.encode("utf-8"))
        if size > _METADATA_VALUE_MAX_BYTES:
            return f"字段「{field_name}」的值超过 {_METADATA_VALUE_MAX_BYTES} 字节"
    return None

