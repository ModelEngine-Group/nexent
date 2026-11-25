# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Ontology domain, entity and relation proxy operations."""

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


logger = logging.getLogger("aidp_ontology_domain_service")


def list_ontology_domains_impl(
    server_url: str,
    api_key: str,
    *,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"page": page, "page_size": page_size}
    if search and search.strip():
        params["search"] = search.strip()
    payload = _ontology_request(
        server_url,
        api_key,
        "GET",
        _get_ontology_path(tenant_id),
        operation="list-ontology-domains",
        params=params,
    )
    _log_business_failure(payload, "list-ontology-domains")
    return _list_envelope(payload, page=page, page_size=page_size)


def get_ontology_domain_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    *,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    payload = _ontology_request(
        server_url,
        api_key,
        "GET",
        f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}",
        operation="get-ontology-domain",
    )
    # Confirmed contract wraps the row in a named `domain` object; older builds
    # answered with `data` or a bare object.
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        return data
    domain = payload.get("domain") if isinstance(payload, dict) else None
    return (
        domain
        if isinstance(domain, dict)
        else (payload if isinstance(payload, dict) else {})
    )


def create_ontology_domain_impl(
    server_url: str,
    api_key: str,
    body: dict[str, Any],
    *,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    payload = _ontology_request(
        server_url,
        api_key,
        "PUT",
        _get_ontology_path(tenant_id),
        operation="create-ontology-domain",
        json_body=body,
    )
    _log_business_failure(payload, "create-ontology-domain")
    data = payload.get("data") if isinstance(payload, dict) else None
    return (
        data
        if isinstance(data, dict)
        else (payload if isinstance(payload, dict) else {})
    )


def update_ontology_domain_impl(
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
        "PATCH",
        f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}",
        operation="update-ontology-domain",
        json_body=body,
    )
    _log_business_failure(payload, "update-ontology-domain")
    data = payload.get("data") if isinstance(payload, dict) else None
    return (
        data
        if isinstance(data, dict)
        else (payload if isinstance(payload, dict) else {})
    )


def delete_ontology_domain_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    *,
    tenant_id: str | None = None,
) -> bool:
    try:
        _ontology_request(
            server_url,
            api_key,
            "DELETE",
            f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}",
            operation="delete-ontology-domain",
        )
        return True
    except AppException as error:
        upstream_status = (error.details or {}).get("upstream_status")
        if upstream_status == HTTPStatus.NOT_FOUND:
            return True
        raise


def _request_entity_page(
    server_url: str,
    api_key: str,
    domain_id: str,
    *,
    page: int,
    page_size: int,
    keyword: str | None,
    kind: str | None,
    tenant_id: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"page": page, "size": page_size}
    if keyword and keyword.strip():
        params["keyword"] = keyword.strip()
    if kind:
        params["kind"] = kind
    payload = _ontology_request(
        server_url,
        api_key,
        "GET",
        f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}/Entities",
        operation="list-ontology-entities",
        params=params,
    )
    _log_business_failure(payload, "list-ontology-entities")
    return _list_envelope(payload, page=page, page_size=page_size)


def list_ontology_entities_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    *,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    kind: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Request one entity page.

    AIDP filters by ``kind`` server-side and returns the filtered total, so the
    page is passed through as-is instead of aggregating every page locally.
    """
    return _request_entity_page(
        server_url,
        api_key,
        domain_id,
        page=page,
        page_size=page_size,
        keyword=keyword,
        kind=kind,
        tenant_id=tenant_id,
    )


def get_ontology_entity_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    entity_id: str,
    *,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    payload = _ontology_request(
        server_url,
        api_key,
        "GET",
        f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}/Entities/{entity_id}",
        operation="get-ontology-entity",
    )
    # Confirmed contract: {"entity": {...}, "neighbor": []}. The entity object
    # itself carries no id, so callers keep the path id.
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        return data
    entity = payload.get("entity") if isinstance(payload, dict) else None
    return (
        entity
        if isinstance(entity, dict)
        else (payload if isinstance(payload, dict) else {})
    )


def create_ontology_entity_impl(
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
        f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}/Entities",
        operation="create-ontology-entity",
        json_body=body,
    )
    _log_business_failure(payload, "create-ontology-entity")
    data = payload.get("data") if isinstance(payload, dict) else None
    return (
        data
        if isinstance(data, dict)
        else (payload if isinstance(payload, dict) else {})
    )


def update_ontology_entity_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    entity_id: str,
    body: dict[str, Any],
    *,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    payload = _ontology_request(
        server_url,
        api_key,
        "PATCH",
        f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}/Entities/{entity_id}",
        operation="update-ontology-entity",
        json_body=body,
    )
    _log_business_failure(payload, "update-ontology-entity")
    data = payload.get("data") if isinstance(payload, dict) else None
    return (
        data
        if isinstance(data, dict)
        else (payload if isinstance(payload, dict) else {})
    )


def delete_ontology_entity_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    entity_id: str,
    *,
    kind: str | None = None,
    tenant_id: str | None = None,
) -> bool:
    params = {"kind": kind} if kind else None
    try:
        _ontology_request(
            server_url,
            api_key,
            "DELETE",
            f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}/Entities/{entity_id}",
            operation="delete-ontology-entity",
            params=params,
        )
        return True
    except AppException as error:
        upstream_status = (error.details or {}).get("upstream_status")
        if upstream_status == HTTPStatus.NOT_FOUND:
            return True
        raise


def _get_relations_path(domain_id: str, tenant_id: str | None = None) -> str:
    return f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}/Relations"


def _normalize_relation(item: dict[str, Any]) -> dict[str, Any]:
    subject = item.get("subject_entity") or {}
    obj = item.get("object_entity") or {}

    def endpoint(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        entity_id = value.get("entity_id") or value.get("id")
        return {
            "entity_id": str(entity_id) if entity_id is not None else None,
            "api_name": value.get("api_name") or value.get("name"),
            "display_name": value.get("display_name") or value.get("name"),
            "kind": value.get("kind"),
        }

    relation_id = item.get("relation_id") or item.get("id")
    return {
        "relation_id": str(relation_id) if relation_id is not None else None,
        "api_name": item.get("api_name"),
        "display_name": item.get("display_name") or "",
        "subject_entity": endpoint(subject),
        "object_entity": endpoint(obj),
        "create_time": item.get("create_time"),
        "update_time": item.get("update_time"),
    }


def list_ontology_relations_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    *,
    page: int = 1,
    size: int = 100,
    relation_type: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"page": page, "size": size}
    if relation_type:
        params["relation_type"] = relation_type
    payload = _ontology_request(
        server_url,
        api_key,
        "GET",
        _get_relations_path(domain_id, tenant_id),
        operation="list-ontology-relations",
        params=params,
    )
    _log_business_failure(payload, "list-ontology-relations")
    envelope = _list_envelope(payload, page=page, page_size=size)
    envelope["value"] = [_normalize_relation(item) for item in envelope["value"]]
    return envelope


def create_ontology_relation_impl(
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
        _get_relations_path(domain_id, tenant_id),
        operation="create-ontology-relation",
        json_body=body,
    )
    _log_business_failure(payload, "create-ontology-relation")
    data = payload.get("data") if isinstance(payload, dict) else None
    return (
        data
        if isinstance(data, dict)
        else (payload if isinstance(payload, dict) else {})
    )


def delete_ontology_relation_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    relation_id: str,
    *,
    tenant_id: str | None = None,
) -> bool:
    try:
        _ontology_request(
            server_url,
            api_key,
            "DELETE",
            f"{_get_relations_path(domain_id, tenant_id)}/{relation_id}",
            operation="delete-ontology-relation",
        )
        return True
    except AppException as error:
        upstream_status = (error.details or {}).get("upstream_status")
        if upstream_status == HTTPStatus.NOT_FOUND:
            return True
        raise
