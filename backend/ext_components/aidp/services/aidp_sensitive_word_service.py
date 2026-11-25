# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP knowledge-base sensitive word proxy service.

Sensitive words belong to one AIDP knowledge base. Every request addresses
``/KnowledgeBase/Tenants/aidp/KnowledgeBases/{KdsId}/SensitiveWords``; the
tenant segment remains AIDP's fixed ``aidp`` namespace and is never derived
from the Nexent login tenant. Word matching, normalisation and enforcement
stay inside AIDP.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote, urljoin

import httpx
from nexent.utils.http_client_manager import http_client_manager

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from ext_components.aidp.consts.aidp_exceptions import AidpSensitiveWordError
from ext_components.aidp.services.aidp_client import (
    _AIDP_ACCEPT_LANGUAGE,
    _AIDP_READ_TIMEOUT_SECONDS,
    _extract_upstream_code,
    _extract_upstream_error,
    _get_sensitive_words_path,
    _validate_params,
)


logger = logging.getLogger("aidp_sensitive_word_service")

# AIDP's fixed namespace for all knowledge-base requests.
AIDP_SENSITIVE_WORD_TENANT = "aidp"
AIDP_SENSITIVE_WORD_MAX_PAGE_SIZE = 100

_WORD_MODES = {"BLACK", "WHITE"}


def _validate_kds_id(kds_id: str) -> str:
    value = (kds_id or "").strip()
    if not value:
        raise AppException(
            ErrorCode.COMMON_PARAMETER_INVALID,
            "Knowledge base id is required",
        )
    return value


def _collection_path(kds_id: str) -> str:
    return _get_sensitive_words_path(
        _validate_kds_id(kds_id),
        tenant_id=AIDP_SENSITIVE_WORD_TENANT,
    )


def _item_path(kds_id: str, word_id: str) -> str:
    return f"{_collection_path(kds_id)}/{quote(str(word_id), safe='')}"


def _build_list_path(
    kds_id: str,
    page: int,
    page_size: int,
    keyword: str | None,
    mode: str | None,
) -> str:
    if page < 1:
        raise AppException(ErrorCode.COMMON_PARAMETER_INVALID, "page must be at least 1")
    if page_size < 1 or page_size > AIDP_SENSITIVE_WORD_MAX_PAGE_SIZE:
        raise AppException(
            ErrorCode.COMMON_PARAMETER_INVALID,
            f"page_size must be between 1 and {AIDP_SENSITIVE_WORD_MAX_PAGE_SIZE}",
        )
    if mode is not None and mode not in _WORD_MODES:
        raise AppException(
            ErrorCode.COMMON_PARAMETER_INVALID,
            "mode must be BLACK or WHITE",
        )

    query = f"?page={page}&page_size={page_size}"
    normalized_keyword = (keyword or "").strip()
    if normalized_keyword:
        query += f"&keyword={quote(normalized_keyword, safe='')}"
    if mode:
        query += f"&mode={mode}"
    return f"{_collection_path(kds_id)}{query}"


def _decode_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except (TypeError, ValueError):
        return None


def _request(
    method: str,
    normalized_url: str,
    path: str,
    *,
    api_key: str,
    json_body: dict[str, Any] | None = None,
) -> httpx.Response:
    """Send one AIDP request and preserve its upstream failure details.

    Deliberately no retry: a retried create or update is not idempotent, and a
    duplicate-word rejection would only repeat the same failure.
    """
    url = urljoin(f"{normalized_url}/", path)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept-Language": _AIDP_ACCEPT_LANGUAGE,
        "Content-Type": "application/json",
    }
    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=_AIDP_READ_TIMEOUT_SECONDS,
            verify_ssl=False,
        )
        response = client.request(method, url, headers=headers, json=json_body)
    except httpx.RequestError:
        logger.exception("AIDP sensitive word request failed: %s %s", method, path)
        raise AppException(
            ErrorCode.AIDP_CONNECTION_ERROR,
            "AIDP API request failed",
        )

    if response.status_code >= 400:
        upstream_message = _extract_upstream_error(response)
        upstream_code = _extract_upstream_code(response)
        reason = upstream_message or response.text[:500] or "no response body"
        logger.warning(
            "AIDP sensitive word %s %s failed: http_status=%s business_code=%s reason=%s",
            method,
            path,
            response.status_code,
            upstream_code,
            reason,
        )
        raise AidpSensitiveWordError(
            upstream_message
            or f"AIDP sensitive word request failed with HTTP {response.status_code}",
            upstream_code=str(upstream_code) if upstream_code is not None else None,
            upstream_status=response.status_code,
        )
    return response


def _unwrap(payload: Any) -> dict[str, Any]:
    """Merge a ``data`` envelope into the top-level object."""
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict):
        return {**payload, **data}
    return payload


def _normalize_mode(value: Any) -> str:
    mode = str(value or "").upper()
    return mode if mode in _WORD_MODES else ""


def _normalize_item(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    word_id = raw.get("id")
    if word_id is None:
        word_id = raw.get("sensitive_word_id") or raw.get("word_id")
    word = raw.get("word")
    if word_id is None or not isinstance(word, str) or not word:
        return None
    item = {
        "id": str(word_id),
        "word": word,
        "mode": _normalize_mode(raw.get("mode")),
        "description": raw.get("description") or "",
        "source": str(raw.get("source") or "CUSTOM").upper(),
    }
    for key in ("create_time", "update_time", "created_at", "updated_at"):
        if raw.get(key) is not None:
            item[key] = raw[key]
    return item


def _response_json(response: httpx.Response) -> dict[str, Any]:
    payload = _decode_body(response)
    if not isinstance(payload, dict):
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            "Unexpected AIDP sensitive word response format",
        )
    return payload


def list_sensitive_words_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    page: int,
    page_size: int,
    keyword: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """Return one page of the knowledge base dictionary in AIDP's format."""
    normalized_url = _validate_params(server_url, api_key)
    path = _build_list_path(kds_id, page, page_size, keyword, mode)
    response = _request("GET", normalized_url, path, api_key=api_key)
    payload = _response_json(response)

    container = _unwrap(payload)
    raw_items = container.get("value")
    if not isinstance(raw_items, list):
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            "Unexpected AIDP sensitive word list response format",
        )

    items: list[dict[str, Any]] = []
    for raw in raw_items:
        item = _normalize_item(raw)
        if item is None:
            logger.warning("Skipping malformed AIDP sensitive word row: %s", raw)
            continue
        items.append(item)

    raw_total = container.get("total_count")
    total = (
        int(raw_total)
        if isinstance(raw_total, int) and not isinstance(raw_total, bool)
        else (page - 1) * page_size + len(items)
    )
    next_link = container.get("next_link")
    return {
        "value": items,
        "next_link": next_link if isinstance(next_link, str) else None,
        "total_count": total,
    }


def get_sensitive_word_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    word_id: str,
) -> dict[str, Any]:
    """Read one word so the edit form never submits stale list data."""
    normalized_url = _validate_params(server_url, api_key)
    response = _request(
        "GET", normalized_url, _item_path(kds_id, word_id), api_key=api_key
    )
    item = _normalize_item(_unwrap(_response_json(response)))
    if item is None:
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            "Unexpected AIDP sensitive word detail response format",
        )
    return item


def create_sensitive_word_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    word: str,
    mode: str,
    description: str,
) -> dict[str, Any]:
    """Create one custom word in the knowledge base; AIDP returns only its id."""
    normalized_url = _validate_params(server_url, api_key)
    response = _request(
        "PUT",
        normalized_url,
        _collection_path(kds_id),
        api_key=api_key,
        json_body={"word": word, "mode": mode, "description": description},
    )
    payload = _decode_body(response)
    data = payload.get("data") if isinstance(payload, dict) else None
    word_id = data.get("id") if isinstance(data, dict) else None
    if word_id is None and isinstance(payload, dict):
        word_id = payload.get("id")
    if word_id is None:
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            "AIDP did not return a sensitive word id",
        )
    return {"id": str(word_id)}


def update_sensitive_word_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    word_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Patch one word with the fields the caller actually changed."""
    normalized_url = _validate_params(server_url, api_key)
    _request(
        "PATCH",
        normalized_url,
        _item_path(kds_id, word_id),
        api_key=api_key,
        json_body=updates,
    )
    return {}


def delete_sensitive_word_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    word_id: str,
) -> bool:
    """Delete one custom word. AIDP answers 204 with an empty body."""
    normalized_url = _validate_params(server_url, api_key)
    _request("DELETE", normalized_url, _item_path(kds_id, word_id), api_key=api_key)
    return True


__all__ = [
    "AIDP_SENSITIVE_WORD_MAX_PAGE_SIZE",
    "AIDP_SENSITIVE_WORD_TENANT",
    "create_sensitive_word_impl",
    "delete_sensitive_word_impl",
    "get_sensitive_word_impl",
    "list_sensitive_words_impl",
    "update_sensitive_word_impl",
]
