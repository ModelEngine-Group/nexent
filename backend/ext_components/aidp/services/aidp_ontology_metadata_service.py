# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Ontology Metadata definition operations."""
from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from contracts.errors.exceptions import AppException
from ext_components.aidp.services.aidp_ontology_common import (
    _domain_id_value,
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
