# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Knowledge base to ontology-domain binding proxy operations.

The deployed AIDP exposes bind/unbind on the knowledge-base side and a
per-domain binding list without BindingId; a by-KB lookup scans domains."""

from __future__ import annotations

import logging
from typing import Any

from ext_components.aidp.services.aidp_ontology_common import (
    _BINDING_SCAN_DOMAIN_LIMIT,
    _domain_id_value,
    _list_envelope,
    _log_business_failure,
    _ontology_request,
    _resolve_tenant_id,
)
from ext_components.aidp.services.aidp_ontology_domain_service import (
    list_ontology_domains_impl,
)


logger = logging.getLogger("aidp_ontology_binding_service")


def _normalize_binding(item: dict[str, Any]) -> dict[str, Any] | None:
    kds_id = item.get("kb_id") or item.get("kds_id") or item.get("kdsId")
    od_id = item.get("domain_id") or item.get("od_id") or item.get("odId")
    if kds_id is None or od_id is None:
        return None
    return {
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
        envelope = _list_envelope(
            payload, page=params["page"], page_size=params["page_size"]
        )
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
        raw_id = item.get("od_id") or item.get("domain_id") or item.get("id")
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
    POST ``/KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{kdsId}/OntologyDomain/{DomainId}/Bind``.
    """
    payload = _ontology_request(
        server_url,
        api_key,
        "POST",
        f"{_get_binding_base(tenant_id)}/KnowledgeBases/{kds_id}"
        f"/OntologyDomain/{_domain_id_value(domain_id)}/Bind",
        operation="create-ontology-binding",
        json_body={},
    )
    _log_business_failure(payload, "create-ontology-binding")
    data = payload.get("data") if isinstance(payload, dict) else None
    return (
        data
        if isinstance(data, dict)
        else (payload if isinstance(payload, dict) else {})
    )


def delete_ontology_binding_impl(
    server_url: str,
    api_key: str,
    *,
    domain_id: str,
    kds_id: str,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Unbind a knowledge base from an ontology domain.

    Confirmed route: POST ``/KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{kdsId}/
    OntologyDomain/{DomainId}/Unbind``. It only acknowledges a background
    tag-clear task.
    """
    payload = _ontology_request(
        server_url,
        api_key,
        "POST",
        f"{_get_binding_base(tenant_id)}/KnowledgeBases/{kds_id}"
        f"/OntologyDomain/{_domain_id_value(domain_id)}/Unbind",
        operation="delete-ontology-binding",
        json_body={},
    )
    _log_business_failure(payload, "delete-ontology-binding")
    data = payload.get("data") if isinstance(payload, dict) else None
    return (
        data
        if isinstance(data, dict)
        else (payload if isinstance(payload, dict) else {})
    )
