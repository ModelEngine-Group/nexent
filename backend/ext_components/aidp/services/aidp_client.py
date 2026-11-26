# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Low-level AIDP HTTP, path, retry and error helpers shared by services."""

from __future__ import annotations

import logging
import time
from contextvars import ContextVar
from typing import Any, Callable, Dict, NoReturn
from urllib.parse import quote, urljoin

import httpx
from nexent.utils.http_client_manager import http_client_manager

from contracts.constants.environment import AIDP_TENANT_ID
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException


logger = logging.getLogger("aidp_service")

_MAX_UPSTREAM_ERROR_REASON_LENGTH = 1000
_UPSTREAM_ERROR_KEYS = (
    "reason_zh",
    "reason_en",
    "details",
    "message",
    "detail",
    "error",
)

_AIDP_RETRY_MAX_ATTEMPTS = 3
_AIDP_RETRY_BACKOFF_FACTOR = 0.5
_AIDP_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_AIDP_READ_TIMEOUT_SECONDS = 30.0
_AIDP_DOWNLOAD_TIMEOUT_SECONDS = 120.0

# Per-request language from the frontend. Calls without a frontend request
# (background jobs, server-side evaluation) fall back to Chinese.
_DEFAULT_AIDP_LANGUAGE = "zh-CN"
_aidp_accept_language: ContextVar[str | None] = ContextVar(
    "aidp_accept_language", default=None
)


def set_aidp_accept_language(value: str | None) -> None:
    """Store the current request's language for downstream AIDP calls."""
    if value and value.strip():
        _aidp_accept_language.set(value.strip())


def _current_aidp_accept_language() -> str:
    return _aidp_accept_language.get() or _DEFAULT_AIDP_LANGUAGE


def _aidp_headers(api_key: str, *, content_type: bool = True) -> dict[str, str]:
    """Build the common headers for an outbound AIDP request."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept-Language": _current_aidp_accept_language(),
    }
    if content_type:
        headers["Content-Type"] = "application/json"
    return headers


def _normalize_upstream_error(value: Any) -> str | None:
    """Extract a concise human-readable reason from an upstream error value."""
    if isinstance(value, str):
        normalized = " ".join(value.split())
        return normalized or None
    if isinstance(value, dict):
        for key in _UPSTREAM_ERROR_KEYS:
            reason = _normalize_upstream_error(value.get(key))
            if reason:
                return reason
    if isinstance(value, list):
        reasons = [
            reason
            for item in value
            if (reason := _normalize_upstream_error(item))
        ]
        if reasons:
            return "; ".join(reasons)
    return None


def _extract_upstream_error(response: httpx.Response) -> str | None:
    """Read a bounded error reason from AIDP's fixed error envelope."""
    try:
        payload = response.json()
    except (TypeError, ValueError):
        payload = None

    reason = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                reason = _normalize_upstream_error(message)

    if not reason:
        content_type = response.headers.get("content-type", "").lower()
        if "text/plain" in content_type:
            reason = _normalize_upstream_error(response.text)

    if not reason:
        return None
    return reason[:_MAX_UPSTREAM_ERROR_REASON_LENGTH]


def _extract_upstream_code(response: httpx.Response) -> int | None:
    """Read AIDP's business code from ``{"error": {"code": <int>}}``."""
    try:
        payload = response.json()
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    if isinstance(code, bool) or not isinstance(code, int):
        return None
    return code


def _raise_aidp_http_error(error: httpx.HTTPStatusError, operation: str) -> NoReturn:
    """Map an AIDP HTTP error to the common application exception format."""
    response = error.response
    upstream_reason = _extract_upstream_error(response)
    upstream_code = _extract_upstream_code(response)
    logger.exception(
        "AIDP %s HTTP error: status_code=%s upstream_code=%s upstream_reason=%s",
        operation,
        response.status_code,
        upstream_code,
        upstream_reason or "unavailable",
    )
    details = {
        "upstream_status": response.status_code,
        "upstream_reason": upstream_reason,
    }
    if upstream_code is not None:
        details["upstream_code"] = upstream_code
    error_code = {
        401: ErrorCode.AIDP_AUTH_ERROR,
        403: ErrorCode.AIDP_AUTH_ERROR,
        429: ErrorCode.AIDP_RATE_LIMIT,
    }.get(response.status_code, ErrorCode.AIDP_SERVICE_ERROR)
    fallback_message = {
        ErrorCode.AIDP_AUTH_ERROR: f"AIDP authentication failed: {str(error)}",
        ErrorCode.AIDP_RATE_LIMIT: f"AIDP rate limit exceeded: {str(error)}",
    }.get(
        error_code,
        f"AIDP API HTTP error {response.status_code}: {str(error)}",
    )
    raise AppException(
        error_code,
        upstream_reason or fallback_message,
        details=details,
    )


def _resolve_tenant_id(tenant_id: Any = None) -> str:
    """Resolve a valid AIDP tenant identifier from explicit or configured input."""
    configured_tenant = AIDP_TENANT_ID if isinstance(AIDP_TENANT_ID, str) else "aidp"
    resolved_tenant = tenant_id if isinstance(tenant_id, str) else configured_tenant
    return resolved_tenant.strip() or "aidp"


def _get_list_path(tenant_id: str | None = None) -> str:
    """Build the tenant-scoped knowledge-base API path."""
    return f"/KnowledgeBase/Tenants/{_resolve_tenant_id(tenant_id)}/KnowledgeBases"


def _get_channels_path(kds_id: str, tenant_id: str | None = None) -> str:
    """Build the knowledge-base scoped ingestion-pipeline (channel) API path.

    AIDP exposes the channel catalog per knowledge base
    (``.../KnowledgeBases/{kds_id}/Channels``), mirroring the knowledge-file
    endpoints. The channel carries the ``fs_id`` + source directory the history
    request is addressed with, which is why the KB id is part of the path.
    """
    return (
        f"/KnowledgeBase/Tenants/{_resolve_tenant_id(tenant_id)}"
        f"/KnowledgeBases/{kds_id}/Channels"
    )


def _get_doc_history_path(kds_id: str, tenant_id: str | None = None) -> str:
    """Build the knowledge-base scoped knowledge-file history API path.

    Like the channel catalog, the history endpoint belongs to one knowledge base
    (``.../KnowledgeBases/{kds_id}/KnowledgeFiles/History``); the body addresses
    the request to a channel directory inside that knowledge base.
    """
    return (
        f"/KnowledgeBase/Tenants/{_resolve_tenant_id(tenant_id)}"
        f"/KnowledgeBases/{kds_id}/KnowledgeFiles/History"
    )


def _get_folders_path(kds_id: str, tenant_id: str | None = None) -> str:
    """Build the knowledge-base scoped folder collection API path."""
    return (
        f"/KnowledgeBase/Tenants/{_resolve_tenant_id(tenant_id)}"
        f"/KnowledgeBases/{kds_id}/Folders"
    )


def _get_sensitive_words_path(
    kds_id: str, tenant_id: str | None = None
) -> str:
    """Build the knowledge-base scoped sensitive-word collection API path."""
    return (
        f"/KnowledgeBase/Tenants/{_resolve_tenant_id(tenant_id)}"
        f"/KnowledgeBases/{quote(str(kds_id), safe='')}/SensitiveWords"
    )


def _get_folder_tree_path(
    kds_id: str,
    folder_id: int = 0,
    tenant_id: str | None = None,
) -> str:
    """Build the new AIDP folder-tree path addressed by numeric FolderId."""
    return f"{_get_folders_path(kds_id, tenant_id)}/{int(folder_id)}"


def _join_folder_path(parent: str, name: str) -> str:
    """Join one folder segment to an AIDP path rooted at ``/``."""
    if parent == "/":
        return f"/{name}"
    return f"{parent.rstrip('/')}/{name}"


def _get_aidp_folder_level(
    server_url: str,
    api_key: str,
    kds_id: str,
    folder_id: int,
    folder_path: str,
    *,
    include_files: bool = False,
    page: int = 1,
    page_size: int = 1,
    keyword: str | None = None,
    file_type: str | None = None,
    file_status: str | None = None,
) -> Dict[str, Any]:
    """Read one folder level from the new folder-id addressed AIDP endpoint."""
    params: Dict[str, Any] = {
        "folder_path": folder_path,
        "page": page,
        "page_size": page_size,
        "include_files": str(include_files).lower(),
    }
    if keyword and keyword.strip():
        params["keyword"] = keyword.strip()
    if file_type and file_type.strip():
        params["file_type"] = file_type.strip()
    if file_status and file_status.strip():
        params["file_status"] = file_status.strip()

    return _request_aidp_json(
        server_url,
        api_key,
        "GET",
        _get_folder_tree_path(kds_id, folder_id),
        context=f"folder-tree:{kds_id}:{folder_id}",
        params=params,
    )


def _resolve_aidp_folder_id(
    server_url: str,
    api_key: str,
    kds_id: str,
    folder_path: str,
) -> int:
    """Resolve an AIDP path to its numeric FolderId.

    The new AIDP API never accepts a path in the route; it accepts the numeric
    FolderId and keeps the path as a query/body attribute. Root is always 0.
    Each segment is resolved through a folders-only tree read; this also gives
    us an explicit error instead of forwarding a malformed path as a 404.
    """
    if folder_path == "/":
        return 0

    current_id = 0
    current_path = "/"
    for segment in folder_path.strip("/").split("/"):
        if not segment:
            continue
        level = _get_aidp_folder_level(
            server_url,
            api_key,
            kds_id,
            current_id,
            current_path,
            include_files=False,
            page=1,
            page_size=200,
        )
        # AIDP's folder-tree response is fixed. Resolving a deep path is
        # deliberately one upstream request per segment; the public route
        # still addresses folders by path, so this cost is accepted.
        folders = level["folders"]
        match = next(
            (folder for folder in folders if folder["folder_name"] == segment),
            None,
        )
        if match is None:
            raise AppException(
                ErrorCode.AIDP_SERVICE_ERROR,
                f"AIDP folder not found: {folder_path}",
                details={"folder_path": folder_path, "segment": segment},
            )
        current_id = int(match["folder_id"])
        current_path = _join_folder_path(current_path, segment)
    return current_id


def _get_knowledge_files_path(kds_id: str, tenant_id: str | None = None) -> str:
    """Build the knowledge-file collection API path."""
    return (
        f"/KnowledgeBase/Tenants/{_resolve_tenant_id(tenant_id)}"
        f"/KnowledgeBases/{kds_id}/KnowledgeFiles"
    )


def _get_ocr_annotate_path(
    kds_id: str, file_uuid: str, tenant_id: str | None = None
) -> str:
    """Build the knowledge-base scoped preview (OCR annotate) API path.

    Unlike the file action endpoints (``Download``/``Remove``/``History``),
    which address the file in the request body, the preview endpoint carries it
    in the path (``.../KnowledgeBases/{kds_id}/OcrAnnotate/{file_uuid}``). AIDP
    serves the original bytes for the formats it can render itself
    (docx/xlsx/pptx/pdf/txt) and converts every other format to PDF, reporting
    the served name in the ``X-File-Name`` response header.
    """
    return (
        f"/KnowledgeBase/Tenants/{_resolve_tenant_id(tenant_id)}"
        f"/KnowledgeBases/{kds_id}/OcrAnnotate/{file_uuid}"
    )


def _get_chunks_path(kds_id: str, tenant_id: str | None = None) -> str:
    """Build the knowledge-base scoped document chunk API path.

    The chunk endpoints follow the same tenant-scoped shape as the other
    knowledge-file endpoints, but address the file through a query parameter
    (list) or the chunk id in the path (detail/update).
    """
    return (
        f"/KnowledgeBase/Tenants/{_resolve_tenant_id(tenant_id)}"
        f"/KnowledgeBases/{kds_id}/Chunks"
    )


def _get_view_image_path(
    kds_id: str, file_id: str, tenant_id: str | None = None
) -> str:
    """Build the ViewImage path that returns a chunk image as PNG bytes.

    AIDP stores each image chunk's picture under
    ``{kds_id}/{file_ino_no}/{image_uuid}.png`` (the chunk's ``file_url``) and
    serves it by ``file_id = {file_ino_no}_{image_uuid}.png`` (2026-11-20
    contract note, verified on five real knowledge bases).
    """
    return (
        f"/KnowledgeBase/Tenants/{_resolve_tenant_id(tenant_id)}"
        f"/KnowledgeBases/{kds_id}/ViewImage/{file_id}"
    )


def _get_retrieval_path(tenant_id: str | None = None) -> str:
    """Build the FusionSearch retrieval path shared by chunk search and tools."""
    return (
        f"/KnowledgeBase/Tenants/{_resolve_tenant_id(tenant_id)}"
        "/Retrieval/FusionSearch"
    )


def _get_batch_metadata_path(
    kds_id: str, *, async_mode: bool = False, tenant_id: str | None = None
) -> str:
    """Build the batch chunk-metadata edit path (sync or async variant)."""
    suffix = "BatchMetadataJsonAsync" if async_mode else "BatchMetadataJson"
    return f"{_get_chunks_path(kds_id, tenant_id)}/{suffix}"


def _get_tags_sync_path(tenant_id: str | None = None) -> str:
    """Build the knowledge-base level auto-tagging trigger path."""
    return (
        f"/KnowledgeBase/Tenants/{_resolve_tenant_id(tenant_id)}"
        "/KnowledgeBases/Tags/Sync"
    )


def _build_list_query(page: int, page_size: int, keyword: str | None = None) -> str:
    """Build the query string for a knowledge-base list request.

    AIDP applies ``keyword`` server-side (matching on the KB name), so the
    value is forwarded verbatim. The parameter is omitted entirely when no
    keyword is supplied, which keeps plain listing requests byte-identical to
    the pre-search behaviour (same URL, so upstream caches still hit).
    """
    query = f"?page={page}&page_size={page_size}"
    normalized_keyword = (keyword or "").strip()
    if normalized_keyword:
        query += f"&keyword={quote(normalized_keyword, safe='')}"
    return query


def _validate_params(server_url: str, api_key: str) -> str:
    """Validate parameters and return normalized base URL."""
    if not server_url or not isinstance(server_url, str):
        raise AppException(
            ErrorCode.AIDP_CONFIG_INVALID,
            "AIDP server_url is required and must be a non-empty string",
        )
    if not server_url.startswith(("http://", "https://")):
        raise AppException(
            ErrorCode.AIDP_CONFIG_INVALID,
            "AIDP server_url must start with http:// or https://",
        )
    if not api_key or not isinstance(api_key, str):
        raise AppException(
            ErrorCode.AIDP_CONFIG_INVALID,
            "AIDP api_key is required and must be a non-empty string",
        )
    return server_url.rstrip("/")


def _request_with_retry(
    request_fn: Callable[[], httpx.Response],
    context: str,
    max_attempts: int = _AIDP_RETRY_MAX_ATTEMPTS,
) -> httpx.Response:
    """Execute a sync httpx request with retries for transient failures.

    Retries on:
        * HTTP 408, 429, 500, 502, 503, and 504
        * httpx.RequestError (connection refused, timeouts, DNS, etc.)

    Exponential backoff: 0.5s, 1s, 2s. Respects Retry-After header on 429.

    The last response (successful or final failure) is returned to the
    caller so `response.raise_for_status()` can raise the existing AppException
    flow. On a final RequestError, the exception propagates directly.
    """
    last_exception: Exception | None = None

    for attempt in range(max_attempts):
        try:
            response = request_fn()
            if 200 <= response.status_code < 300:
                return response
            if response.status_code not in _AIDP_RETRYABLE_STATUS_CODES:
                return response
            if attempt < max_attempts - 1:
                wait_time = _compute_retry_wait(response, attempt)
                logger.warning(
                    "HTTP %d for %s, retrying in %ss (attempt %d/%d)",
                    response.status_code, context, wait_time,
                    attempt + 1, max_attempts,
                )
                time.sleep(wait_time)
                continue
            # Last attempt — return so callers can raise_for_status()
            return response
        except httpx.RequestError as e:
            last_exception = e
            if attempt < max_attempts - 1:
                wait_time = _AIDP_RETRY_BACKOFF_FACTOR * (2 ** attempt)
                logger.warning(
                    "AIDP request error for %s: [%s] %s, retrying in %ss (%d/%d)",
                    context, type(e).__name__, e, wait_time,
                    attempt + 1, max_attempts,
                )
                time.sleep(wait_time)
            else:
                break

    # All retries exhausted on RequestError — let caller translate to AppException.
    assert last_exception is not None
    raise last_exception


def _compute_retry_wait(response: httpx.Response, attempt: int) -> float:
    """Determine backoff wait time for a retryable response.

    Honors the standard ``Retry-After`` header (seconds) when present.
    Falls back to exponential backoff: ``backoff_factor * 2^attempt``.
    """
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except (TypeError, ValueError):
            pass
    return _AIDP_RETRY_BACKOFF_FACTOR * (2 ** attempt)


def _request_aidp_json(
    server_url: str,
    api_key: str,
    method: str,
    path: str,
    *,
    context: str,
    params: Dict[str, Any] | None = None,
    json_body: Dict[str, Any] | None = None,
    retry: bool = True,
) -> Dict[str, Any]:
    """Run one AIDP JSON request and translate transport/HTTP faults.

    Folder and knowledge-file path operations share the same small contract:
    JSON in, JSON (or an empty body for 204) out. Only the URL and body differ,
    so they go through one helper instead of repeating the error mapping.
    ``retry`` defaults to True; non-idempotent writes pass False so a lost
    response cannot replay the write upstream.
    """
    normalized_url = _validate_params(server_url, api_key)
    headers = _aidp_headers(api_key)
    request_url = urljoin(f"{normalized_url}/", path.lstrip("/"))
    logger.info("AIDP %s request to %s", method, request_url)

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=_AIDP_READ_TIMEOUT_SECONDS,
            verify_ssl=False,
        )
        def request_fn():
            return client.request(
                method,
                request_url,
                headers=headers,
                params=params,
                json=json_body,
            )

        response = (
            _request_with_retry(request_fn, context=context)
            if retry
            else request_fn()
        )
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return {}
        result = response.json()
        if not isinstance(result, dict):
            raise AppException(
                ErrorCode.AIDP_RESPONSE_ERROR,
                "Unexpected AIDP response format",
            )
        return result
    except httpx.RequestError as e:
        logger.exception("AIDP request failed: context=%s error=%s", context, e)
        raise AppException(
            ErrorCode.AIDP_CONNECTION_ERROR,
            f"AIDP API request failed: {str(e)}",
        )
    except httpx.HTTPStatusError as e:
        _raise_aidp_http_error(e, context)
    except ValueError as e:
        logger.exception("Failed to parse AIDP response: %s", e)
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            f"Failed to parse AIDP API response: {str(e)}",
        )

