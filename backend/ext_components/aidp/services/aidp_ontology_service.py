# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP ontology, metadata and chunk proxy service.

The AIDP service holds the only copy of ontology domains, entities, knowledge
base bindings, metadata field definitions and chunk metadata. These helpers
build the tenant-scoped requests, translate transport failures into the shared
application exception contract and normalize list envelopes. No database
persistence is introduced on the Nexent side.
"""
from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any
from urllib.parse import urljoin

import httpx
from nexent.utils.http_client_manager import http_client_manager

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from ext_components.aidp.services.aidp_service import (
    _extract_list_payload,
    _extract_upstream_error,
    _raise_aidp_http_error,
    _request_with_retry,
    _resolve_tenant_id,
    _validate_params,
)


logger = logging.getLogger("aidp_ontology_service")

_ONTOLOGY_TIMEOUT_SECONDS = 60.0
_CHUNK_BATCH_MAX_IDS = 100
_METADATA_FIELD_LIMIT = 20
_METADATA_KEY_MAX_BYTES = 64
_METADATA_VALUE_MAX_BYTES = 256
_METADATA_TYPES = ("string", "number", "date")
# AIDP has no all-bindings endpoint; by-KB lookups scan domains. Cap the scan
# so one page request cannot fan out without bound.
_BINDING_SCAN_DOMAIN_LIMIT = 100


def _get_ontology_path(tenant_id: str | None = None) -> str:
    return f"/KnowledgeBase/Tenants/{_resolve_tenant_id(tenant_id)}/OntologyDomain"


def _domain_id_value(domain_id: Any) -> int:
    """AIDP ontology domain IDs are integers.

    The browser keeps a string identifier for routing stability, but every
    upstream path segment, query parameter and request body uses the numeric
    form confirmed by the AIDP contact.
    """
    try:
        value = int(domain_id)
    except (TypeError, ValueError):
        raise AppException(
            ErrorCode.COMMON_PARAMETER_INVALID,
            "AIDP ontology domain ID must be numeric",
        ) from None
    if value < 0:
        raise AppException(
            ErrorCode.COMMON_PARAMETER_INVALID,
            "AIDP ontology domain ID must not be negative",
        )
    return value


def _get_chunks_path(kds_id: str, tenant_id: str | None = None) -> str:
    # Confirmed real-environment route is KB-side; the tenant-scoped path is
    # kept only as a fallback for deployments that still expose it.
    return f"/KnowledgeBase/KnowledgeBases/{kds_id}/Chunks"


def _get_legacy_chunks_path(kds_id: str, tenant_id: str | None = None) -> str:
    return (
        f"/KnowledgeBase/Tenants/{_resolve_tenant_id(tenant_id)}"
        f"/KnowledgeBases/{kds_id}/Chunks"
    )


def _ontology_request(
    server_url: str,
    api_key: str,
    method: str,
    path: str,
    *,
    operation: str,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float = _ONTOLOGY_TIMEOUT_SECONDS,
) -> Any:
    """Execute one authenticated AIDP request and return its JSON body."""
    base_url = _validate_params(server_url, api_key)
    url = urljoin(f"{base_url}/", path)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    client = http_client_manager.get_sync_client(
        base_url=base_url, timeout=timeout, verify_ssl=False
    )
    try:
        response = _request_with_retry(
            lambda: client.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
            ),
            context=operation,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        if 400 <= status < 500 and status not in (401, 403, 429):
            # Domain validation, conflicts and in-use fields are caller errors,
            # not gateway failures. Preserve the readable upstream reason.
            reason = _extract_upstream_error(error.response) or (
                f"AIDP rejected the request (HTTP {status})"
            )
            logger.warning(
                "AIDP %s rejected with status=%s reason=%s",
                operation,
                status,
                reason,
            )
            raise AppException(
                ErrorCode.COMMON_RESOURCE_NOT_FOUND
                if status == 404
                else ErrorCode.COMMON_PARAMETER_INVALID,
                reason,
                details={"upstream_status": status, "operation": operation},
            ) from error
        _raise_aidp_http_error(error, operation)
    except httpx.RequestError as error:
        logger.error("AIDP %s connection error: [%s] %s", operation, type(error).__name__, error)
        raise AppException(
            ErrorCode.AIDP_CONNECTION_ERROR,
            f"AIDP connection failed: {error}",
            details={"operation": operation},
        ) from error

    if response.status_code == HTTPStatus.NO_CONTENT or not response.content:
        return {}
    try:
        return response.json()
    except ValueError as error:
        logger.error("AIDP %s returned a non-JSON response", operation)
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            "AIDP returned a non-JSON response",
            details={"operation": operation},
        ) from error


def _log_business_failure(payload: Any, operation: str) -> None:
    if not isinstance(payload, dict):
        return
    code = payload.get("code")
    if code is None or str(code) in ("200", "0"):
        return
    logger.warning(
        "AIDP %s business failure: code=%s message=%s",
        operation,
        code,
        payload.get("message"),
    )


def _as_items(payload: Any) -> list[dict[str, Any]]:
    raw = _extract_list_payload(payload)
    return [item for item in raw if isinstance(item, dict)]


def _list_envelope(
    payload: Any,
    *,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """Normalize every AIDP list envelope into one Nexent shape.

    The deployed service answers with four different envelopes depending on the
    endpoint: ``value/next_link/total_count`` (domains, rules, domain bindings),
    ``items/next_link/page/page_size/total`` (entities, chunks, relations),
    ``value/has_next/next_link/total_count`` (Metadata fields) and
    ``task_list/total`` (Tasks). Items and totals may sit at the top level or
    inside a ``data`` wrapper, so both levels are inspected.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    source = data if isinstance(data, dict) else (payload if isinstance(payload, dict) else {})
    raw_items = source.get("items")
    if not isinstance(raw_items, list):
        raw_items = source.get("value")
    if not isinstance(raw_items, list) and isinstance(payload, dict):
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raw_items = payload.get("value")
    items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
    # AIDP's ontology-domain list exposes `total`; most other endpoints use
    # `total_count`. Accept both, preferring `total`.
    raw_total = source.get("total")
    if raw_total is None:
        raw_total = source.get("total_count")
    if raw_total is None and isinstance(payload, dict):
        raw_total = payload.get("total")
        if raw_total is None:
            raw_total = payload.get("total_count")
    total_reliable = isinstance(raw_total, int) and not isinstance(raw_total, bool)
    total = raw_total if total_reliable else (page - 1) * page_size + len(items)
    # `has_next` is authoritative when present (Metadata list). `next_link` is
    # NOT a terminator: AIDP returns it even for an empty last page, so page
    # math wins whenever the total is trustworthy.
    has_next = source.get("has_next")
    if isinstance(has_next, bool):
        has_more = has_next
    elif total_reliable:
        has_more = page * page_size < total
    else:
        has_more = len(items) >= page_size
    return {
        "value": items,
        "total_count": total,
        "has_more": has_more,
        "total_reliable": total_reliable,
    }


# ============================ Ontology domains ============================


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
    return domain if isinstance(domain, dict) else (payload if isinstance(payload, dict) else {})


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
    return data if isinstance(data, dict) else (payload if isinstance(payload, dict) else {})


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
    return data if isinstance(data, dict) else (payload if isinstance(payload, dict) else {})


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


# ================================ Entities ================================


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
    # Confirmed contract puts items/page/page_size/total at the top level; the
    # generic envelope already accepts that shape as well as data-wrapped ones.
    return _list_envelope(payload, page=page, page_size=page_size)


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
    return entity if isinstance(entity, dict) else (payload if isinstance(payload, dict) else {})


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
    return data if isinstance(data, dict) else (payload if isinstance(payload, dict) else {})


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
    return data if isinstance(data, dict) else (payload if isinstance(payload, dict) else {})


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


# ================================ Bindings ================================


def _normalize_binding(item: dict[str, Any]) -> dict[str, Any] | None:
    kds_id = item.get("kb_id") or item.get("kds_id") or item.get("kdsId")
    od_id = item.get("domain_id") or item.get("od_id") or item.get("odId")
    if kds_id is None or od_id is None:
        return None
    # Confirmed contract exposes no BindingId: a row is addressed by the
    # (domain_id, kb_id) pair. The legacy id fallback keeps older mocks alive.
    binding_id = item.get("binding_id")
    return {
        "binding_id": str(binding_id) if binding_id is not None else None,
        "binding_type": item.get("binding_type") or "ontology",
        "kds_id": str(kds_id),
        "od_id": str(od_id),
        "kds_name": item.get("kb_name")
        or item.get("kds_name")
        or item.get("knowledge_base_name"),
        "create_time": item.get("create_time"),
    }


def _get_binding_base(tenant_id: str | None = None) -> str:
    """Bindings are addressed through the tenant-scoped OntologyDomain root."""
    return f"/KnowledgeBase/Tenants/{_resolve_tenant_id(tenant_id)}"


def _list_domain_bindings_raw(
    server_url: str,
    api_key: str,
    domain_id: str,
    *,
    tenant_id: str | None = None,
) -> list[dict[str, Any]]:
    """Page through one domain's bindings.

    Confirmed route: GET ``{base}/{DomainId}/Bindings`` (singular
    ``OntologyDomain``) answering the ``value/next_link/total_count`` envelope.
    """
    path = f"{_get_binding_base(tenant_id)}/OntologyDomain/{_domain_id_value(domain_id)}/Bindings"
    params: dict[str, Any] = {"page": 1, "page_size": 100}
    rows: list[dict[str, Any]] = []
    for _ in range(20):
        payload = _ontology_request(
            server_url,
            api_key,
            "GET",
            path,
            operation="list-ontology-bindings",
            params=params,
        )
        _log_business_failure(payload, "list-ontology-bindings")
        envelope = _list_envelope(payload, page=params["page"], page_size=params["page_size"])
        rows.extend(
            binding
            for item in envelope["value"]
            if (binding := _normalize_binding(item)) is not None
        )
        if not envelope["has_more"]:
            break
        params["page"] += 1
    return rows


def list_ontology_bindings_impl(
    server_url: str,
    api_key: str,
    *,
    domain_id: str | None = None,
    kds_id: str | None = None,
    tenant_id: str | None = None,
) -> list[dict[str, Any]]:
    """List ontology bindings.

    AIDP only exposes a per-domain query. By-domain reads page that endpoint;
    by-KB and all-bindings reads scan every domain and filter locally (bounded
    by ``_BINDING_SCAN_DOMAIN_LIMIT``). The scan is how the KB detail tab and
    the "one KB, one domain" pre-check work in real deployments.
    """
    if domain_id:
        rows = _list_domain_bindings_raw(
            server_url, api_key, domain_id, tenant_id=tenant_id
        )
        if kds_id:
            rows = [row for row in rows if row["kds_id"] == str(kds_id)]
        return rows

    domains = list_ontology_domains_impl(
        server_url,
        api_key,
        page=1,
        page_size=100,
        tenant_id=tenant_id,
    )["value"]
    rows = []
    for item in domains[:_BINDING_SCAN_DOMAIN_LIMIT]:
        raw_id = item.get("domain_id") or item.get("id")
        if raw_id is None:
            continue
        for binding in _list_domain_bindings_raw(
            server_url, api_key, str(raw_id), tenant_id=tenant_id
        ):
            if kds_id and binding["kds_id"] != str(kds_id):
                continue
            rows.append(binding)
    return rows


def create_ontology_binding_impl(
    server_url: str,
    api_key: str,
    *,
    domain_id: str,
    kds_id: str,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Bind one knowledge base to one ontology domain.

    Confirmed route lives on the KB side and takes no body:
    POST ``/KnowledgeBase/KnowledgeBases/{kdsId}/OntologyDomain/{DomainId}/Bind``.
    """
    payload = _ontology_request(
        server_url,
        api_key,
        "POST",
        f"/KnowledgeBase/KnowledgeBases/{kds_id}"
        f"/OntologyDomain/{_domain_id_value(domain_id)}/Bind",
        operation="create-ontology-binding",
        json_body={},
    )
    _log_business_failure(payload, "create-ontology-binding")
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else (payload if isinstance(payload, dict) else {})


def delete_ontology_binding_impl(
    server_url: str,
    api_key: str,
    *,
    domain_id: str,
    kds_id: str,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Unbind a knowledge base from an ontology domain.

    Confirmed route: POST ``/KnowledgeBase/KnowledgeBases/{kdsId}/OntologyDomain/
    {DomainId}/Unbind``. It only acknowledges a background tag-clear task.
    """
    payload = _ontology_request(
        server_url,
        api_key,
        "POST",
        f"/KnowledgeBase/KnowledgeBases/{kds_id}"
        f"/OntologyDomain/{_domain_id_value(domain_id)}/Unbind",
        operation="delete-ontology-binding",
        json_body={},
    )
    _log_business_failure(payload, "delete-ontology-binding")
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else (payload if isinstance(payload, dict) else {})


# ============================ Metadata definitions ========================


def _normalize_field(item: dict[str, Any]) -> dict[str, Any]:
    raw_chunk_count = item.get("associatedChunkCount")
    if raw_chunk_count is None:
        raw_chunk_count = item.get("associated_chunk_count")
    return {
        "id": item.get("id") or item.get("metadata_id"),
        "field_name": item.get("fieldName") or item.get("field_name"),
        "field_type": item.get("fieldType") or item.get("field_type"),
        "column_index": item.get("columnIndex") or item.get("column_index"),
        "candidates": item.get("candidates") or item.get("candidate_values") or [],
        "extended_properties": item.get("extendedProperties")
        or item.get("extended_properties")
        or [],
        "associated_chunk_count": (
            raw_chunk_count
            if isinstance(raw_chunk_count, int)
            and not isinstance(raw_chunk_count, bool)
            else None
        ),
        "create_time": item.get("createTime") or item.get("create_time"),
        "update_time": item.get("updateTime") or item.get("update_time"),
        "status": item.get("status"),
        "demo_task": item.get("demoTask") or item.get("demo_task"),
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


# =================================== Rules ==================================


def _rules_envelope(
    payload: Any,
    *,
    page: int,
    size: int,
) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) else None
    source = data if isinstance(data, dict) else (payload if isinstance(payload, dict) else {})
    raw_items = source.get("value")
    if not isinstance(raw_items, list):
        raw_items = source.get("rules")
    items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
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
    source = data if isinstance(data, dict) else (payload if isinstance(payload, dict) else {})
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
    return data if isinstance(data, dict) else (payload if isinstance(payload, dict) else {})


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
    return data if isinstance(data, dict) else (payload if isinstance(payload, dict) else {})


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
    return data if isinstance(data, dict) else (payload if isinstance(payload, dict) else {})


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


# =================================== Tasks =================================


def _get_tasks_path(tenant_id: str | None = None) -> str:
    return f"/KnowledgeBase/Tenants/{_resolve_tenant_id(tenant_id)}/Tasks"


def _normalize_task(item: dict[str, Any]) -> dict[str, Any]:
    task_id = item.get("id") or item.get("task_id")
    progress = item.get("progress")
    return {
        "task_id": str(task_id) if task_id is not None else None,
        "task_type": item.get("task_type") or item.get("type"),
        "status": item.get("status"),
        "progress": progress if isinstance(progress, int) and not isinstance(progress, bool) else None,
        "description": item.get("description") or "",
        "error_message": item.get("error_message") or "",
        "start_time": item.get("start_time"),
        "end_time": item.get("end_time"),
    }


def list_tasks_impl(
    server_url: str,
    api_key: str,
    *,
    page: int = 1,
    page_size: int = 20,
    task_type: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Query AIDP background tasks (fourth envelope: task_list/total)."""
    params: dict[str, Any] = {"page": page, "page_size": page_size}
    if task_type:
        params["task_type"] = task_type
    payload = _ontology_request(
        server_url,
        api_key,
        "GET",
        _get_tasks_path(tenant_id),
        operation="list-tasks",
        params=params,
    )
    _log_business_failure(payload, "list-tasks")
    data = payload.get("data") if isinstance(payload, dict) else None
    source = data if isinstance(data, dict) else (payload if isinstance(payload, dict) else {})
    raw_items = source.get("task_list")
    if not isinstance(raw_items, list):
        raw_items = source.get("value")
    if not isinstance(raw_items, list):
        raw_items = source.get("items")
    items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
    raw_total = source.get("total")
    if raw_total is None:
        raw_total = source.get("total_count")
    total_reliable = isinstance(raw_total, int) and not isinstance(raw_total, bool)
    total = raw_total if total_reliable else (page - 1) * page_size + len(items)
    task_count = source.get("task_count")
    return {
        "value": [_normalize_task(item) for item in items],
        "total_count": total,
        "task_count": task_count if isinstance(task_count, int) and not isinstance(task_count, bool) else None,
        "has_more": page * page_size < total,
        "total_reliable": total_reliable,
    }


def get_task_impl(
    server_url: str,
    api_key: str,
    task_id: str,
    *,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    payload = _ontology_request(
        server_url,
        api_key,
        "GET",
        f"{_get_tasks_path(tenant_id)}/{task_id}",
        operation="get-task",
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    source = data if isinstance(data, dict) else (payload if isinstance(payload, dict) else {})
    task = source.get("task") if isinstance(source, dict) else None
    if isinstance(task, dict):
        source = task
    return _normalize_task(source) if isinstance(source, dict) else {}


# ================================= Relations ================================


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
    envelope["value"] = [
        _normalize_relation(item) for item in envelope["value"]
    ]
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
    return data if isinstance(data, dict) else (payload if isinstance(payload, dict) else {})


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


# ================================== Chunks =================================


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


# ============================= Import / export ============================


def export_ontology_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    *,
    include_properties: bool = True,
    include_relations: bool = True,
    kind: str | None = None,
    tenant_id: str | None = None,
) -> Any:
    return _ontology_request(
        server_url,
        api_key,
        "POST",
        f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}/batch/export",
        operation="export-ontology",
        json_body={
            "DOMAIN_ID": _domain_id_value(domain_id),
            "INCLUDE_PROPERTIES": bool(include_properties),
            "INCLUDE_RELATIONS": bool(include_relations),
            "KIND": kind,
        },
    )


def import_ontology_impl(
    server_url: str,
    api_key: str,
    domain_id: str,
    body: dict[str, Any],
    *,
    tenant_id: str | None = None,
) -> Any:
    return _ontology_request(
        server_url,
        api_key,
        "POST",
        f"{_get_ontology_path(tenant_id)}/{_domain_id_value(domain_id)}/batch/import",
        operation="import-ontology",
        json_body=body,
    )


# ========================== Annotation validation =========================

METADATA_FIELD_LIMIT = _METADATA_FIELD_LIMIT
METADATA_KEY_MAX_BYTES = _METADATA_KEY_MAX_BYTES
METADATA_VALUE_MAX_BYTES = _METADATA_VALUE_MAX_BYTES
METADATA_TYPES = _METADATA_TYPES
CHUNK_BATCH_MAX_IDS = _CHUNK_BATCH_MAX_IDS


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
