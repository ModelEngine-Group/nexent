# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Ontology rule proxy operations."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from ext_components.aidp.services.aidp_ontology_common import (
    _domain_id_value,
    _get_ontology_path,
    _log_business_failure,
    _ontology_request,
)


logger = logging.getLogger("aidp_ontology_rule_service")


def _rules_envelope(
    payload: Any,
    *,
    page: int,
    size: int,
) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) else None
    source = (
        data
        if isinstance(data, dict)
        else (payload if isinstance(payload, dict) else {})
    )
    raw_items = source.get("value")
    if not isinstance(raw_items, list):
        raw_items = source.get("rules")
    items = (
        [item for item in raw_items if isinstance(item, dict)]
        if isinstance(raw_items, list)
        else []
    )
    raw_total = source.get("total_count")
    if raw_total is None:
        raw_total = source.get("total")
    total_reliable = isinstance(raw_total, int) and not isinstance(raw_total, bool)
    total = raw_total if total_reliable else (page - 1) * size + len(items)
    return {
        "value": items,
        "total_count": total,
        "has_more": page * size < total,
        "total_reliable": total_reliable,
    }


def list_ontology_rules_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    *,
    page: int = 1,
    size: int = 20,
    enabled_only: bool = False,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"page": page, "size": size}
    if enabled_only:
        params["enabled_only"] = "true"
    payload = _ontology_request(
        server_url,
        api_key,
        "GET",
        f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}/Rules",
        operation="list-ontology-rules",
        params=params,
    )
    _log_business_failure(payload, "list-ontology-rules")
    return _rules_envelope(payload, page=page, size=size)


def count_ontology_rules_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    *,
    tenant_id: str | None = None,
) -> int:
    payload = _ontology_request(
        server_url,
        api_key,
        "GET",
        f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}/Rules/Count",
        operation="count-ontology-rules",
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    source = (
        data
        if isinstance(data, dict)
        else (payload if isinstance(payload, dict) else {})
    )
    count = source.get("count")
    if isinstance(count, int) and not isinstance(count, bool):
        return count
    raise AppException(
        ErrorCode.AIDP_SERVICE_ERROR,
        "AIDP returned an unexpected rule count response",
        details={"operation": "count-ontology-rules"},
    )


def get_ontology_rule_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    rule_id: str,
    *,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    payload = _ontology_request(
        server_url,
        api_key,
        "GET",
        f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}/Rules/{rule_id}",
        operation="get-ontology-rule",
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    return (
        data
        if isinstance(data, dict)
        else (payload if isinstance(payload, dict) else {})
    )


def create_ontology_rule_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    body: dict[str, Any],
    *,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    payload = _ontology_request(
        server_url,
        api_key,
        "PUT",
        f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}/Rules",
        operation="create-ontology-rule",
        json_body=body,
    )
    _log_business_failure(payload, "create-ontology-rule")
    data = payload.get("data") if isinstance(payload, dict) else None
    return (
        data
        if isinstance(data, dict)
        else (payload if isinstance(payload, dict) else {})
    )


def update_ontology_rule_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    rule_id: str,
    body: dict[str, Any],
    *,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    payload = _ontology_request(
        server_url,
        api_key,
        "PATCH",
        f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}/Rules/{rule_id}",
        operation="update-ontology-rule",
        json_body=body,
    )
    _log_business_failure(payload, "update-ontology-rule")
    data = payload.get("data") if isinstance(payload, dict) else None
    return (
        data
        if isinstance(data, dict)
        else (payload if isinstance(payload, dict) else {})
    )


def delete_ontology_rule_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    rule_id: str,
    *,
    tenant_id: str | None = None,
) -> bool:
    try:
        _ontology_request(
            server_url,
            api_key,
            "DELETE",
            f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}/Rules/{rule_id}",
            operation="delete-ontology-rule",
        )
        return True
    except AppException as error:
        upstream_status = (error.details or {}).get("upstream_status")
        if upstream_status == HTTPStatus.NOT_FOUND:
            return True
        raise
