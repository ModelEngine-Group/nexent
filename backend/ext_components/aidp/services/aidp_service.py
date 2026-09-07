"""
AIDP Service Layer
Handles API calls to AIDP for paginated knowledge base listing.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List
from urllib.parse import urljoin

import httpx

from consts.const import AIDP_TENANT_ID
from consts.error_code import ErrorCode
from consts.exceptions import AppException
from nexent.utils.http_client_manager import http_client_manager

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
    """Read a bounded error reason from an AIDP HTTP response."""
    try:
        reason = _normalize_upstream_error(response.json())
    except (TypeError, ValueError):
        reason = None

    if not reason:
        content_type = response.headers.get("content-type", "").lower()
        if "text/plain" in content_type:
            reason = _normalize_upstream_error(response.text)

    if not reason:
        return None
    return reason[:_MAX_UPSTREAM_ERROR_REASON_LENGTH]


def _extract_upload_failures(response: httpx.Response) -> List[Dict[str, str]]:
    """Extract per-file upload failures from AIDP's structured error body."""
    try:
        payload = response.json()
    except (TypeError, ValueError):
        return []

    if not isinstance(payload, dict):
        return []
    error = payload.get("error")
    if not isinstance(error, dict):
        return []
    raw_details = error.get("details")
    if not isinstance(raw_details, list):
        return []

    fallback_reason = _normalize_upstream_error(error.get("message")) or "Upload failed"
    failures: List[Dict[str, str]] = []
    for item in raw_details:
        if not isinstance(item, dict):
            continue
        file_name = _normalize_upstream_error(item.get("file_name") or item.get("filename"))
        reason_zh = _normalize_upstream_error(item.get("reason_zh"))
        reason_en = _normalize_upstream_error(item.get("reason_en"))
        if not file_name or not (reason_zh or reason_en):
            continue
        failures.append(
            {
                "file_name": file_name,
                "reason_zh": reason_zh or reason_en or fallback_reason,
                "reason_en": reason_en or reason_zh or fallback_reason,
            }
        )
    return failures

def _resolve_tenant_id(tenant_id: Any = None) -> str:
    """Resolve a valid AIDP tenant identifier from explicit or configured input."""
    configured_tenant = AIDP_TENANT_ID if isinstance(AIDP_TENANT_ID, str) else "aidp"
    resolved_tenant = tenant_id if isinstance(tenant_id, str) else configured_tenant
    return resolved_tenant.strip() or "aidp"


def _get_list_path(tenant_id: str | None = None) -> str:
    """Build the tenant-scoped knowledge-base API path."""
    return f"/KnowledgeBase/Tenants/{_resolve_tenant_id(tenant_id)}/KnowledgeBases"


def _timestamp_to_iso(value: Any) -> str | None:
    """Convert a numeric Unix timestamp (seconds or milliseconds) to ISO-8601 UTC.

    Returns None for genuine "no timestamp" inputs only:
      - ``None``
      - empty string (AIDP occasionally returns ``""`` for unset fields)
      - literal ``False`` (distinct from numeric zero)

    Numeric zero (``0`` or ``0.0``) is treated as the Unix epoch — a valid
    timestamp that AIDP can return for legacy rows or placeholder records.
    The ``is`` identity checks (rather than ``==``) are deliberate:
    ``0 == False`` evaluates to True in Python because ``bool`` is a
    subclass of ``int``, which would silently drop legitimate epoch
    timestamps if we used equality comparison here.
    """
    if value is None or value == "" or value is False:
        return None
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    # Millisecond timestamps (13+ digits) common in some AIDP responses
    if ts > 10_000_000_000:
        ts = ts / 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_aidp_doc(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map an AIDP document item to the shape the frontend expects.

    AIDP returns ``first_upload_time`` / ``create_time`` as the creation timestamp
    and ``update_time`` as the last-modified timestamp. The frontend schema
    expects ``created_at`` (ISO string). This mapper performs that conversion
    and carries through all other fields unchanged.
    """
    out = dict(raw)
    created_raw = raw.get("first_upload_time") or raw.get("create_time")
    out["created_at"] = _timestamp_to_iso(created_raw)

    updated_raw = raw.get("update_time")
    out["updated_at"] = _timestamp_to_iso(updated_raw)
    return out


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


# ==================== Retry helpers ====================
_AIDP_RETRY_MAX_ATTEMPTS = 3
# Exponential backoff: 0.5s, 1s, 2s
_AIDP_RETRY_BACKOFF_FACTOR = 0.5
_AIDP_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_AIDP_READ_TIMEOUT_SECONDS = 30.0


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


def fetch_aidp_knowledge_bases_impl(
    server_url: str,
    api_key: str,
    page: int = 1,
    page_size: int = 10,
) -> Dict[str, Any]:
    """Fetch a single page from AIDP API (simple passthrough)."""
    normalized_url = _validate_params(server_url, api_key)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    list_path = f"{_get_list_path()}?page={page}&page_size={page_size}"
    list_url = urljoin(f"{normalized_url}/", list_path)
    logger.info("Fetching AIDP knowledge bases from %s", list_url)

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=_AIDP_READ_TIMEOUT_SECONDS,
            verify_ssl=False,
        )
        response = _request_with_retry(
            lambda: client.get(list_url, headers=headers),
            context="list-kbs",
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise AppException(
                ErrorCode.AIDP_SERVICE_ERROR,
                "Unexpected AIDP knowledge base response format",
            )
        return _normalize_response(result)
    except httpx.RequestError as e:
        logger.exception("AIDP request failed: %s", e)
        raise AppException(
            ErrorCode.AIDP_CONNECTION_ERROR,
            f"AIDP API request failed: {str(e)}",
        )
    except httpx.HTTPStatusError as e:
        logger.exception(
            "AIDP API HTTP error: %s, status_code: %s",
            e,
            e.response.status_code,
        )
        if e.response.status_code in (401, 403):
            raise AppException(
                ErrorCode.AIDP_AUTH_ERROR,
                f"AIDP authentication failed: {str(e)}",
            )
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"AIDP API HTTP error {e.response.status_code}: {str(e)}",
        )
    except ValueError as e:
        logger.exception("Failed to parse AIDP API response: %s", e)
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"Failed to parse AIDP API response: {str(e)}",
        )


def _normalize_response(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map AIDP API response fields to the canonical {value, total_count, next_link} shape."""
    items = (
        raw.get("value")
        if raw.get("value") is not None
        else raw.get("data")
        if raw.get("data") is not None
        else raw.get("items")
        if raw.get("items") is not None
        else raw.get("knowledge_bases")
        if raw.get("knowledge_bases") is not None
        else []
    )
    total_keys = ("total_count", "total", "totalRecords", "count")
    total = next((raw.get(k) for k in total_keys if raw.get(k) is not None), None)
    next_link = raw.get("next_link") or raw.get("next") or None
    return {
        "value": items,
        "total_count": total,
        "next_link": next_link,
    }


def fetch_all_aidp_knowledge_bases_impl(
    server_url: str,
    api_key: str,
) -> Dict[str, Any]:
    """Fetch every AIDP knowledge-base page using the dedicated Count API.

    The list response does not expose a reliable global count and its
    ``next_link`` may contain a sentinel tenant. The Count endpoint determines
    the number of pages, and every list request uses the configured tenant.
    Duplicate resources are removed by ``kds_id`` while preserving their
    first-seen order.
    """
    normalized_url = _validate_params(server_url, api_key)
    page_size = 100
    started_at = time.perf_counter()
    count_started_at = time.perf_counter()
    total_count = count_aidp_kbs_impl(normalized_url, api_key)
    count_ms = (time.perf_counter() - count_started_at) * 1000
    if total_count <= 0:
        logger.info(
            "AIDP KB catalog timing: total_ms=%.1f count_ms=%.1f list_ms=0.0 "
            "reported_total=0 pages=0 accumulated=0",
            (time.perf_counter() - started_at) * 1000,
            count_ms,
        )
        return {"value": [], "total_count": 0, "next_link": None}

    total_pages = (total_count + page_size - 1) // page_size
    max_pages = 1000
    if total_pages > max_pages:
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            f"AIDP knowledge base pagination exceeded {max_pages} pages",
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=_AIDP_READ_TIMEOUT_SECONDS,
            verify_ssl=False,
        )

        all_items: List[Any] = []
        seen_kds_ids: set[str] = set()
        list_started_at = time.perf_counter()

        for current_page in range(1, total_pages + 1):
            page_path = f"{_get_list_path()}?page={current_page}&page_size={page_size}"
            current_url = urljoin(f"{normalized_url}/", page_path)

            logger.info(
                "Fetching AIDP KBs — page %d/%d from %s",
                current_page,
                total_pages,
                current_url,
            )

            response = _request_with_retry(
                lambda: client.get(current_url, headers=headers),
                context=f"list-kbs-all:page{current_page}",
            )
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise AppException(
                    ErrorCode.AIDP_SERVICE_ERROR,
                    "Unexpected AIDP knowledge base response format",
                )

            page_items = (
                result.get("value")
                if result.get("value") is not None
                else result.get("data")
                if result.get("data") is not None
                else result.get("items")
                if result.get("items") is not None
                else result.get("knowledge_bases")
                if result.get("knowledge_bases") is not None
                else []
            )
            if not isinstance(page_items, list):
                page_items = []

            for item in page_items:
                if not isinstance(item, dict):
                    all_items.append(item)
                    continue
                raw_kds_id = item.get("kds_id") or item.get("id")
                if raw_kds_id is None:
                    all_items.append(item)
                    continue
                kds_id = str(raw_kds_id)
                if kds_id in seen_kds_ids:
                    continue
                seen_kds_ids.add(kds_id)
                all_items.append(item)

        accumulated_count = len(all_items)
        list_ms = (time.perf_counter() - list_started_at) * 1000
        logger.info(
            "AIDP KB catalog timing: total_ms=%.1f count_ms=%.1f list_ms=%.1f "
            "reported_total=%d pages=%d accumulated=%d",
            (time.perf_counter() - started_at) * 1000,
            count_ms,
            list_ms,
            total_count,
            total_pages,
            accumulated_count,
        )

        return {
            "value": all_items,
            "total_count": accumulated_count,
            "next_link": None,
        }
    except httpx.RequestError as e:
        logger.exception("AIDP request failed: %s", e)
        raise AppException(
            ErrorCode.AIDP_CONNECTION_ERROR,
            f"AIDP API request failed: {str(e)}",
        )
    except httpx.HTTPStatusError as e:
        logger.exception(
            "AIDP API HTTP error: %s, status_code: %s",
            e,
            e.response.status_code,
        )
        if e.response.status_code in (401, 403):
            raise AppException(
                ErrorCode.AIDP_AUTH_ERROR,
                f"AIDP authentication failed: {str(e)}",
            )
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"AIDP API HTTP error {e.response.status_code}: {str(e)}",
        )
    except ValueError as e:
        logger.exception("Failed to parse AIDP API response: %s", e)
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"Failed to parse AIDP API response: {str(e)}",
        )


# ==================== New CRUD Service Functions ====================


def count_aidp_kbs_impl(server_url: str, api_key: str) -> int:
    """Get total count of knowledge bases via AIDP POST .../Count endpoint.

    AIDP's list endpoint does NOT return a total count, so we must call the
    dedicated Count API: POST /KnowledgeBases/0/Count with {"is_personal": 0}.
    """
    normalized_url = _validate_params(server_url, api_key)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    count_path = f"{_get_list_path()}/0/Count"
    count_url = urljoin(f"{normalized_url}/", count_path)
    logger.info("Counting AIDP knowledge bases from %s", count_url)

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=_AIDP_READ_TIMEOUT_SECONDS,
            verify_ssl=False,
        )
        response = _request_with_retry(
            lambda: client.post(count_url, headers=headers, json={"is_personal": 0}),
            context="count-kbs",
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise AppException(
                ErrorCode.AIDP_RESPONSE_ERROR,
                "Unexpected AIDP count response format",
            )
        return int(result.get("count") or 0)
    except httpx.RequestError as e:
        logger.exception("AIDP request failed: %s", e)
        raise AppException(
            ErrorCode.AIDP_CONNECTION_ERROR,
            f"AIDP API request failed: {str(e)}",
        )
    except httpx.HTTPStatusError as e:
        logger.exception(
            "AIDP API HTTP error: %s, status_code: %s",
            e,
            e.response.status_code,
        )
        if e.response.status_code in (401, 403):
            raise AppException(
                ErrorCode.AIDP_AUTH_ERROR,
                f"AIDP authentication failed: {str(e)}",
            )
        if e.response.status_code == 429:
            raise AppException(
                ErrorCode.AIDP_RATE_LIMIT,
                f"AIDP rate limit exceeded: {str(e)}",
            )
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"AIDP API HTTP error {e.response.status_code}: {str(e)}",
        )
    except ValueError as e:
        logger.exception("Failed to parse AIDP API response: %s", e)
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            f"Failed to parse AIDP API response: {str(e)}",
        )


# Default values for AIDP create KB payload, aligned with
# sdk/nexent/core/knowledge_base/config.py (build_create_payload).
# Used as defense-in-depth: any client calling create_aidp_kb_impl
# without these fields will get them filled in automatically.
_AIDP_CREATE_DEFAULTS: Dict[str, Any] = {
    "chunk_token_num": 1024,
    "chunk_overlap_num": 128,
    "embedding_model": "default",
    # AIDP expects the VLM model identifier exactly as registered in its system.
    "vlm_model": "Qwen3-VL-8B-Instruct",
    "is_personal": 0,
    "topk": 10,
    "similarity": 0.0,
    "smartsplit": 1,
    # caption_enable: int 0/1, not string or bool.
    "caption_enable": 0,
}


def _apply_create_defaults(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fill missing AIDP create-KB fields with reference defaults.

    Defensive layer: if the client omits any of these fields, the backend
    injects them before forwarding to AIDP. Matches the frontend
    AIDP_CREATE_DEFAULTS and the SDK build_create_payload defaults exactly.

    Special rules:
      * if payload.is_multimodal is truthy, caption_enable defaults to ``1``
        (matching SDK mapper logic).
      * when caption_enable is disabled (``0`` or ``"0"``), clear ``vlm_model``
        so AIDP never receives a stale model identifier for a non-multimodal KB.
      * ``description`` is normalized: AIDP rejects empty strings (the spec
        declares length 1-255). Any None/empty/whitespace-only description is
        replaced with the KB name, falling back to ``"Nexent knowledge base"``
        if name is also empty. This converts an AIDP 500 into a successful
        create, because the server-side 500 we observed was traced to an
        empty description in the UI payload.
    """
    result = dict(payload)
    for key, default in _AIDP_CREATE_DEFAULTS.items():
        if key not in result:
            result[key] = default

    # Normalize description: AIDP spec declares length 1-255, but some
    # backend implementations return HTTP 500 (instead of 400) when a
    # required string field arrives as an empty string. This defensive
    # rewrite guarantees the field is never forwarded empty.
    desc = result.get("description")
    if not isinstance(desc, str) or not desc.strip():
        fallback_name = result.get("name")
        if isinstance(fallback_name, str) and fallback_name.strip():
            result["description"] = fallback_name.strip()
        else:
            result["description"] = "Nexent knowledge base"

    if result.get("is_multimodal") and "caption_enable" not in payload:
        result["caption_enable"] = 1

    caption = result.get("caption_enable")
    if caption in (0, "0", False):
        result["vlm_model"] = ""
    return result


def create_aidp_kb_impl(
    server_url: str,
    api_key: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Create a new knowledge base via AIDP API."""
    normalized_url = _validate_params(server_url, api_key)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Fill missing fields with SDK-aligned defaults before forwarding.
    full_payload = _apply_create_defaults(payload)

    create_url = urljoin(f"{normalized_url}/", _get_list_path())
    logger.info("Creating AIDP knowledge base at %s with payload=%s", create_url, full_payload)

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=60.0,
            verify_ssl=False,
        )
        response = client.put(create_url, headers=headers, json=full_payload)

        if response.status_code >= 400:
            # Log the full AIDP response body so we can see exactly what
            # the remote service is complaining about. httpx's own
            # HTTPStatusError only carries URL + status, so this body
            # dump is the most valuable diagnostic for 500s and other
            # non-2xx codes. api_key is intentionally omitted to prevent
            # credential leakage even in masked form.
            logger.warning(
                "AIDP create KB failed: url=%s status=%d api_key=*** body=%s",
                create_url,
                response.status_code,
                response.text[:3000],
            )

        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise AppException(
                ErrorCode.AIDP_RESPONSE_ERROR,
                "Unexpected AIDP create response format",
            )
        return result
    except httpx.RequestError as e:
        logger.exception("AIDP request failed: %s", e)
        raise AppException(
            ErrorCode.AIDP_CONNECTION_ERROR,
            f"AIDP API request failed: {str(e)}",
        )
    except httpx.HTTPStatusError as e:
        # Body is already logged above before raise_for_status, so we
        # only re-log the status for correlation with existing searches.
        logger.exception(
            "AIDP API HTTP error: %s, status_code: %s",
            e,
            e.response.status_code,
        )
        if e.response.status_code in (401, 403):
            raise AppException(
                ErrorCode.AIDP_AUTH_ERROR,
                f"AIDP authentication failed: {str(e)}",
            )
        if e.response.status_code == 429:
            raise AppException(
                ErrorCode.AIDP_RATE_LIMIT,
                f"AIDP rate limit exceeded: {str(e)}",
            )
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"AIDP API HTTP error {e.response.status_code}: {str(e)}",
        )
    except ValueError as e:
        logger.exception("Failed to parse AIDP API response: %s", e)
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            f"Failed to parse AIDP API response: {str(e)}",
        )


def get_aidp_kb_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
) -> Dict[str, Any]:
    """Get details of a specific knowledge base."""
    normalized_url = _validate_params(server_url, api_key)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    get_path = f"{_get_list_path()}/{kds_id}"
    get_url = urljoin(f"{normalized_url}/", get_path)
    logger.info("Getting AIDP knowledge base from %s", get_url)

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=_AIDP_READ_TIMEOUT_SECONDS,
            verify_ssl=False,
        )
        response = _request_with_retry(
            lambda: client.get(get_url, headers=headers),
            context="get-kb-detail",
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise AppException(
                ErrorCode.AIDP_RESPONSE_ERROR,
                "Unexpected AIDP knowledge base response format",
            )
        # Normalize timestamps to ISO-8601 strings so the frontend receives
        # ``created_at`` / ``updated_at`` uniformly (mirrors the doc-level
        # normalizer in ``_normalize_aidp_doc``). AIDP returns raw numeric
        # ``create_time`` / ``update_time`` fields.
        created_raw = result.get("create_time")
        updated_raw = result.get("update_time")
        if created_raw is not None and "created_at" not in result:
            result["created_at"] = _timestamp_to_iso(created_raw)
        if updated_raw is not None and "updated_at" not in result:
            result["updated_at"] = _timestamp_to_iso(updated_raw)
        return result
    except httpx.RequestError as e:
        logger.exception("AIDP request failed: %s", e)
        raise AppException(
            ErrorCode.AIDP_CONNECTION_ERROR,
            f"AIDP API request failed: {str(e)}",
        )
    except httpx.HTTPStatusError as e:
        logger.exception(
            "AIDP API HTTP error: %s, status_code: %s",
            e,
            e.response.status_code,
        )
        if e.response.status_code in (401, 403):
            raise AppException(
                ErrorCode.AIDP_AUTH_ERROR,
                f"AIDP authentication failed: {str(e)}",
            )
        if e.response.status_code == 429:
            raise AppException(
                ErrorCode.AIDP_RATE_LIMIT,
                f"AIDP rate limit exceeded: {str(e)}",
            )
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"AIDP API HTTP error {e.response.status_code}: {str(e)}",
        )
    except ValueError as e:
        logger.exception("Failed to parse AIDP API response: %s", e)
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            f"Failed to parse AIDP API response: {str(e)}",
        )


def update_aidp_kb_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Update a knowledge base via AIDP API."""
    normalized_url = _validate_params(server_url, api_key)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    update_path = f"{_get_list_path()}/{kds_id}"
    update_url = urljoin(f"{normalized_url}/", update_path)
    logger.info("Updating AIDP knowledge base at %s", update_url)

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=60.0,
            verify_ssl=False,
        )
        response = client.patch(update_url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise AppException(
                ErrorCode.AIDP_RESPONSE_ERROR,
                "Unexpected AIDP update response format",
            )
        return result
    except httpx.RequestError as e:
        logger.exception("AIDP request failed: %s", e)
        raise AppException(
            ErrorCode.AIDP_CONNECTION_ERROR,
            f"AIDP API request failed: {str(e)}",
        )
    except httpx.HTTPStatusError as e:
        logger.exception(
            "AIDP API HTTP error: %s, status_code: %s",
            e,
            e.response.status_code,
        )
        if e.response.status_code in (401, 403):
            raise AppException(
                ErrorCode.AIDP_AUTH_ERROR,
                f"AIDP authentication failed: {str(e)}",
            )
        if e.response.status_code == 429:
            raise AppException(
                ErrorCode.AIDP_RATE_LIMIT,
                f"AIDP rate limit exceeded: {str(e)}",
            )
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"AIDP API HTTP error {e.response.status_code}: {str(e)}",
        )
    except ValueError as e:
        logger.exception("Failed to parse AIDP API response: %s", e)
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            f"Failed to parse AIDP API response: {str(e)}",
        )


def delete_aidp_kb_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
) -> bool:
    """Delete a knowledge base via AIDP API."""
    normalized_url = _validate_params(server_url, api_key)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    delete_path = f"{_get_list_path()}/{kds_id}"
    delete_url = urljoin(f"{normalized_url}/", delete_path)
    logger.info("Deleting AIDP knowledge base at %s", delete_url)

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=60.0,
            verify_ssl=False,
        )
        response = client.delete(delete_url, headers=headers)
        response.raise_for_status()
        return True
    except httpx.RequestError as e:
        logger.exception("AIDP request failed: %s", e)
        raise AppException(
            ErrorCode.AIDP_CONNECTION_ERROR,
            f"AIDP API request failed: {str(e)}",
        )
    except httpx.HTTPStatusError as e:
        logger.exception(
            "AIDP API HTTP error: %s, status_code: %s",
            e,
            e.response.status_code,
        )
        if e.response.status_code in (401, 403):
            raise AppException(
                ErrorCode.AIDP_AUTH_ERROR,
                f"AIDP authentication failed: {str(e)}",
            )
        if e.response.status_code == 429:
            raise AppException(
                ErrorCode.AIDP_RATE_LIMIT,
                f"AIDP rate limit exceeded: {str(e)}",
            )
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"AIDP API HTTP error {e.response.status_code}: {str(e)}",
        )


def upload_aidp_docs_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    files: List[Any],
) -> Dict[str, Any]:
    """Upload documents to a knowledge base via AIDP API."""
    normalized_url = _validate_params(server_url, api_key)

    headers = {
        "Authorization": f"Bearer {api_key}",
    }

    upload_path = f"{_get_list_path()}/{kds_id}/KnowledgeFiles/Upload"
    upload_url = urljoin(f"{normalized_url}/", upload_path)
    logger.info("Uploading documents to AIDP knowledge base at %s", upload_url)

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=120.0,
            verify_ssl=False,
        )
        # httpx files= expects: [(field_name, (filename, file_obj, content_type)), ...]
        # Previously incorrectly passed [(filename, file_obj, content_type), ...]
        # which caused "too many values to unpack (expected 2)" at httpx level.
        file_tuples = [
            ("files", (f.filename, f.file, f.content_type or "application/octet-stream"))
            for f in files
        ]
        response = client.post(upload_url, headers=headers, files=file_tuples)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise AppException(
                ErrorCode.AIDP_RESPONSE_ERROR,
                "Unexpected AIDP upload response format",
            )
        return result
    except httpx.RequestError as e:
        logger.exception("AIDP request failed: %s", e)
        raise AppException(
            ErrorCode.AIDP_CONNECTION_ERROR,
            f"AIDP API request failed: {str(e)}",
        )
    except httpx.HTTPStatusError as e:
        upload_failures = _extract_upload_failures(e.response)
        if upload_failures:
            logger.warning(
                "AIDP rejected %d uploaded file(s) with structured reasons, status_code=%s",
                len(upload_failures),
                e.response.status_code,
            )
            return {
                "summary": {
                    "total": len(files),
                    "success": 0,
                    "failed": len(upload_failures),
                },
                "success_list": [],
                "failed_list": upload_failures,
            }

        upstream_reason = _extract_upstream_error(e.response)
        logger.exception(
            "AIDP API HTTP error: %s, status_code: %s, upstream_reason=%s",
            e,
            e.response.status_code,
            upstream_reason or "unavailable",
        )
        details = {
            "upstream_status": e.response.status_code,
            "upstream_reason": upstream_reason,
        }
        if e.response.status_code in (401, 403):
            raise AppException(
                ErrorCode.AIDP_AUTH_ERROR,
                upstream_reason or f"AIDP authentication failed: {str(e)}",
                details=details,
            )
        if e.response.status_code == 429:
            raise AppException(
                ErrorCode.AIDP_RATE_LIMIT,
                upstream_reason or f"AIDP rate limit exceeded: {str(e)}",
                details=details,
            )
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            upstream_reason or f"AIDP API HTTP error {e.response.status_code}: {str(e)}",
            details=details,
        )
    except ValueError as e:
        logger.exception("Failed to parse AIDP API response: %s", e)
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            f"Failed to parse AIDP API response: {str(e)}",
        )


def count_aidp_docs_impl(server_url: str, api_key: str, kds_id: str) -> int:
    """Get total document count in a KB via AIDP POST .../Count endpoint.

    Mirrors the KB Count API pattern. Endpoint:
        POST /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{kdsId}/KnowledgeFiles/Count
    Body: (empty)
    Response: {"count": <int>}

    AIDP's document list endpoint does NOT return a true total count (its
    `total_count` field is the current page count, not the global total),
    so we must use this dedicated Count API to get the accurate number.
    """
    normalized_url = _validate_params(server_url, api_key)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    count_path = f"{_get_list_path()}/{kds_id}/KnowledgeFiles/Count"
    count_url = urljoin(f"{normalized_url}/", count_path)
    logger.info("Counting AIDP documents in KB %s from %s", kds_id, count_url)

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=_AIDP_READ_TIMEOUT_SECONDS,
            verify_ssl=False,
        )
        # Body is empty per AIDP contract; use content=b"" to send an explicit
        # empty POST (httpx may skip the body otherwise).
        response = _request_with_retry(
            lambda: client.post(count_url, headers=headers, content=b""),
            context=f"count-docs:{kds_id}",
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise AppException(
                ErrorCode.AIDP_RESPONSE_ERROR,
                "Unexpected AIDP doc count response format",
            )
        return int(result.get("count") or 0)
    except httpx.RequestError as e:
        logger.exception("AIDP request failed: %s", e)
        raise AppException(
            ErrorCode.AIDP_CONNECTION_ERROR,
            f"AIDP API request failed: {str(e)}",
        )
    except httpx.HTTPStatusError as e:
        logger.exception(
            "AIDP API HTTP error: %s, status_code: %s",
            e,
            e.response.status_code,
        )
        if e.response.status_code in (401, 403):
            raise AppException(
                ErrorCode.AIDP_AUTH_ERROR,
                f"AIDP authentication failed: {str(e)}",
            )
        if e.response.status_code == 404:
            # KB does not exist or Count endpoint is not supported
            logger.warning("AIDP doc Count API returned 404 for KB %s", kds_id)
            return 0
        if e.response.status_code == 429:
            raise AppException(
                ErrorCode.AIDP_RATE_LIMIT,
                f"AIDP rate limit exceeded: {str(e)}",
            )
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"AIDP API HTTP error {e.response.status_code}: {str(e)}",
        )
    except ValueError as e:
        logger.exception("Failed to parse AIDP API response: %s", e)
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            f"Failed to parse AIDP API response: {str(e)}",
        )


def list_aidp_docs_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    page: int = 1,
    page_size: int = 10,
) -> Dict[str, Any]:
    """List documents in a knowledge base via AIDP API."""
    normalized_url = _validate_params(server_url, api_key)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    list_path = f"{_get_list_path()}/{kds_id}/KnowledgeFiles?page={page}&page_size={page_size}"
    list_url = urljoin(f"{normalized_url}/", list_path)
    logger.info("Listing AIDP documents from %s", list_url)

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=_AIDP_READ_TIMEOUT_SECONDS,
            verify_ssl=False,
        )
        response = _request_with_retry(
            lambda: client.get(list_url, headers=headers),
            context=f"list-docs:{kds_id}",
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise AppException(
                ErrorCode.AIDP_RESPONSE_ERROR,
                "Unexpected AIDP document list response format",
            )
        # Normalize each document item so the frontend receives `created_at`
        # (ISO string) instead of AIDP's raw `first_upload_time` timestamp.
        value = result.get("value")
        if isinstance(value, list):
            result["value"] = [
                _normalize_aidp_doc(item) if isinstance(item, dict) else item
                for item in value
            ]
        return result
    except httpx.RequestError as e:
        logger.exception("AIDP request failed: %s", e)
        raise AppException(
            ErrorCode.AIDP_CONNECTION_ERROR,
            f"AIDP API request failed: {str(e)}",
        )
    except httpx.HTTPStatusError as e:
        logger.exception(
            "AIDP API HTTP error: %s, status_code: %s",
            e,
            e.response.status_code,
        )
        if e.response.status_code in (401, 403):
            raise AppException(
                ErrorCode.AIDP_AUTH_ERROR,
                f"AIDP authentication failed: {str(e)}",
            )
        if e.response.status_code == 429:
            raise AppException(
                ErrorCode.AIDP_RATE_LIMIT,
                f"AIDP rate limit exceeded: {str(e)}",
            )
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"AIDP API HTTP error {e.response.status_code}: {str(e)}",
        )
    except ValueError as e:
        logger.exception("Failed to parse AIDP API response: %s", e)
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            f"Failed to parse AIDP API response: {str(e)}",
        )


# AIDP ModelService endpoint for listing applicable models.
def _get_models_path(tenant_id: str | None = None) -> str:
    """Build the tenant-scoped model service API path."""
    return f"/ModelService/Tenants/{_resolve_tenant_id(tenant_id)}/Service"


def _is_kb_applicable(model: Dict[str, Any]) -> bool:
    """Return True if an AIDP model is applicable to the KnowledgeBase application.

    The ``application`` field can be:
      - the string "All" (applicable to every app, including KnowledgeBase)
      - a string like "KnowledgeBase"
      - a list like ["KnowledgeBase", "..."]
      - the list ["All"] (treated as universal)
      - None / missing (excluded — safer to skip than guess)
    """
    app_val = model.get("application")
    if not app_val:
        return False
    if isinstance(app_val, str):
        return app_val.lower() == "all" or app_val == "KnowledgeBase"
    if isinstance(app_val, list):
        return "All" in app_val or "KnowledgeBase" in app_val
    return False


def list_aidp_models_impl(
    server_url: str,
    api_key: str,
    service: str = "llm",
    app: str = "KnowledgeBase",
) -> Dict[str, Any]:
    """Fetch available models from AIDP ModelService.

    Queries ``GET /ModelService/Tenants/{tenant_id}/Service?service=<service>&app=<app>``
    and post-filters the response to only include models whose ``application``
    field matches ``All`` or the requested ``app`` (AIDP's query parameter is
    advisory; it does not enforce filtering on its own).

    Returns:
        {
          "service": <str>,
          "app": <str>,
          "models": [ { "model_name": str, ... }, ... ],
          "total_count": int,
        }
    """
    normalized_url = _validate_params(server_url, api_key)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    models_path = f"{_get_models_path()}?service={service}&app={app}"
    models_url = urljoin(f"{normalized_url}/", models_path.lstrip("/"))
    logger.info("Fetching AIDP models from %s", models_url)

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=60.0,
            verify_ssl=False,
        )
        response = _request_with_retry(
            lambda: client.get(models_url, headers=headers),
            context=f"list-models:service={service},app={app}",
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise AppException(
                ErrorCode.AIDP_RESPONSE_ERROR,
                "Unexpected AIDP models response format",
            )
        raw_models = result.get("models") or []
        if not isinstance(raw_models, list):
            raise AppException(
                ErrorCode.AIDP_RESPONSE_ERROR,
                "AIDP models response: 'models' field is not a list",
            )
        filtered = [
            m for m in raw_models
            if isinstance(m, dict) and _is_kb_applicable(m)
        ]
        return {
            "service": service,
            "app": app,
            "models": filtered,
            "total_count": len(filtered),
        }
    except httpx.RequestError as e:
        logger.exception("AIDP models request failed: %s", e)
        raise AppException(
            ErrorCode.AIDP_CONNECTION_ERROR,
            f"AIDP models API request failed: {str(e)}",
        )
    except httpx.HTTPStatusError as e:
        logger.exception(
            "AIDP models API HTTP error: %s, status_code: %s",
            e,
            e.response.status_code,
        )
        if e.response.status_code in (401, 403):
            raise AppException(
                ErrorCode.AIDP_AUTH_ERROR,
                f"AIDP authentication failed: {str(e)}",
            )
        if e.response.status_code == 429:
            raise AppException(
                ErrorCode.AIDP_RATE_LIMIT,
                f"AIDP rate limit exceeded: {str(e)}",
            )
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"AIDP models API HTTP error {e.response.status_code}: {str(e)}",
        )
    except ValueError as e:
        logger.exception("Failed to parse AIDP models response: %s", e)
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            f"Failed to parse AIDP models response: {str(e)}",
        )
