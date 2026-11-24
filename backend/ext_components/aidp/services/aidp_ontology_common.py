# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Transport, envelope and shared constants for the AIDP ontology proxy.

All ontology resource modules build tenant-scoped requests through
:func:`_ontology_request` so transport failures and list envelopes are handled
identically. No state is persisted on the Nexent side."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any
from urllib.parse import urljoin

import httpx
from nexent.utils.http_client_manager import http_client_manager

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from ext_components.aidp.services.aidp_client import _extract_upstream_code
from ext_components.aidp.services.aidp_service import (
    _extract_upstream_error,
    _raise_aidp_http_error,
    _request_with_retry,
    _resolve_tenant_id,
    _validate_params,
)


logger = logging.getLogger("aidp_ontology_service")


_ONTOLOGY_TIMEOUT_SECONDS = 60.0


_METADATA_FIELD_LIMIT = 20


_METADATA_TYPES = ("string", "number", "date")


_BINDING_SCAN_DOMAIN_LIMIT = 100


# Entity/domain business codes documented by AIDP. They arrive with HTTP
# statuses that would otherwise be classified as auth or parameter errors.
_ONTOLOGY_BUSINESS_ERRORS = {
    1002: ErrorCode.COMMON_PARAMETER_INVALID,
    1025: ErrorCode.COMMON_RESOURCE_ALREADY_EXISTS,
    1056: ErrorCode.COMMON_RESOURCE_NOT_FOUND,
    1057: ErrorCode.COMMON_RESOURCE_ALREADY_EXISTS,
    1058: ErrorCode.COMMON_FORBIDDEN,
    1059: ErrorCode.COMMON_RESOURCE_NOT_FOUND,
}


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
        upstream_code = _extract_upstream_code(error.response)
        reason = _extract_upstream_error(error.response) or (
            f"AIDP rejected the request (HTTP {status})"
        )
        business_error = _ONTOLOGY_BUSINESS_ERRORS.get(upstream_code)
        if business_error is not None:
            logger.warning(
                "AIDP %s rejected with status=%s code=%s reason=%s",
                operation,
                status,
                upstream_code,
                reason,
            )
            raise AppException(
                business_error,
                reason,
                details={
                    "upstream_status": status,
                    "upstream_code": upstream_code,
                    "operation": operation,
                },
            ) from error
        if 400 <= status < 500 and status not in (401, 403, 429):
            # Domain validation, conflicts and in-use fields are caller errors,
            # not gateway failures. Preserve the readable upstream reason.
            logger.warning(
                "AIDP %s rejected with status=%s reason=%s",
                operation,
                status,
                reason,
            )
            details = {"upstream_status": status, "operation": operation}
            if upstream_code is not None:
                details["upstream_code"] = upstream_code
            raise AppException(
                ErrorCode.COMMON_RESOURCE_NOT_FOUND
                if status == 404
                else ErrorCode.COMMON_PARAMETER_INVALID,
                reason,
                details=details,
            ) from error
        _raise_aidp_http_error(error, operation)
    except httpx.RequestError as error:
        logger.error(
            "AIDP %s connection error: [%s] %s", operation, type(error).__name__, error
        )
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


def _list_envelope(
    payload: Any,
    *,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """Normalize every AIDP list envelope into one Nexent shape.

    The deployed service uses three envelopes in this module:
    ``value/next_link/total_count`` (domains, rules, domain bindings),
    ``items/next_link/page/page_size/total`` (entities, relations), and
    ``value/has_next/next_link/total_count`` (Metadata fields). Items and totals
    may sit at the top level or inside a ``data`` wrapper, so both levels are
    inspected. Tasks are normalized separately because they use ``task_list``.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    source = (
        data
        if isinstance(data, dict)
        else (payload if isinstance(payload, dict) else {})
    )
    raw_items = source.get("items")
    if not isinstance(raw_items, list):
        raw_items = source.get("value")
    if not isinstance(raw_items, list) and isinstance(payload, dict):
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raw_items = payload.get("value")
    items = (
        [item for item in raw_items if isinstance(item, dict)]
        if isinstance(raw_items, list)
        else []
    )
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


METADATA_FIELD_LIMIT = _METADATA_FIELD_LIMIT


METADATA_TYPES = _METADATA_TYPES
