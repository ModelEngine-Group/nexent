"""
AIDP Service Layer
Handles API calls to AIDP for paginated knowledge base listing.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List
from urllib.parse import quote, urljoin

import httpx
from nexent.utils.http_client_manager import http_client_manager

from consts.const import AIDP_TENANT_ID
from consts.error_code import ErrorCode
from consts.exceptions import AppException


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


def _raise_aidp_http_error(error: httpx.HTTPStatusError, operation: str) -> NoReturn:
    """Map an AIDP HTTP error to the common application exception format."""
    response = error.response
    upstream_reason = _extract_upstream_error(response)
    logger.exception(
        "AIDP %s HTTP error: status_code=%s upstream_reason=%s",
        operation,
        response.status_code,
        upstream_reason or "unavailable",
    )
    details = {
        "upstream_status": response.status_code,
        "upstream_reason": upstream_reason,
    }
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


# AIDP wraps list payloads in ``value`` (the shape every established endpoint in
# this adapter returns). The remaining keys cover builds that put the items
# behind a transport envelope, and a bare array is accepted as-is, so a renamed
# wrapper cannot silently turn a populated list into "nothing returned".
_AIDP_LIST_KEYS = ("value", "data", "result", "records", "items", "list")


def _extract_list_payload(payload: Any) -> list | None:
    """Return the item list carried by an AIDP list response, if there is one.

    ``None`` means the response does not carry a list at all, which callers
    report as an unexpected response format instead of degrading into an empty
    result that looks like "no data upstream".
    """
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return None
    for key in _AIDP_LIST_KEYS:
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return candidate
    return None


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


def _normalize_doc_status(value: Any) -> str | None:
    """Normalize an AIDP file status to its canonical upper-case token.

    AIDP reports ``COMPLETED`` / ``PROCESSING`` / ``FAILED``; normalizing here
    means the frontend can compare against one form regardless of upstream
    capitalization. ``None`` is returned for missing/blank values so callers can
    tell "no status reported" apart from a real status. Non-string values (for
    example a numeric ``state``) are ignored instead of being stringified.
    """
    if isinstance(value, str) and value.strip():
        return value.strip().upper()
    return None


# Deployments spell the per-file processing status differently, so it is read
# through aliases like the channel fields further down (``_CHANNEL_*_KEYS``).
# Only the forms actually observed are listed; adding one here is enough to
# support another deployment.
_HISTORY_STATUS_KEYS = (
    "status",
    "file_status",
    "fileStatus",
    "file_state",
    "doc_status",
)


def _extract_doc_status(raw: Dict[str, Any]) -> str | None:
    """Return the first recognized file status carried by ``raw``.

    The canonical ``status`` wins, then the observed aliases in order, so a
    deployment that renames the field keeps working without a code change.
    """
    for key in _HISTORY_STATUS_KEYS:
        status = _normalize_doc_status(raw.get(key))
        if status is not None:
            return status
    return None


def _normalize_history_doc(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map an AIDP knowledge-file history item to the frontend document shape.

    The history payload carries the same identity fields as the document list
    (``file_ino_no`` / ``file_name`` / ``file_size`` / ``file_type`` /
    ``first_upload_time``) plus a processing status. Whatever field the upstream
    used, the value is re-emitted under the canonical ``status`` key so the
    frontend only has to read one field. A blank or missing upstream status is
    dropped rather than forwarded as whitespace, so callers can treat "no status
    reported" as a single state.
    """
    out = _normalize_aidp_doc(raw)
    status = _extract_doc_status(raw)
    if status is None:
        out.pop("status", None)
    else:
        out["status"] = status
    return out


def _warn_when_history_status_unreadable(items: List[Any], fs_id: str) -> None:
    """Log the payload shape when no history item carries a usable status.

    The processing status is the reason the history endpoint is used at all: a
    payload whose status field we cannot read renders as a column of dashes, so
    the keys of a sample item are logged to make the real field name
    discoverable from the service log instead of leaving the gap invisible.
    """
    item_dicts = [item for item in items if isinstance(item, dict)]
    if not item_dicts or any("status" in item for item in item_dicts):
        return
    logger.warning(
        "AIDP file history for fs_id=%s returned %d item(s) with no readable status; "
        "sample keys=%s",
        fs_id,
        len(item_dicts),
        sorted(item_dicts[0].keys()),
    )


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
_AIDP_DOWNLOAD_TIMEOUT_SECONDS = 120.0


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
    keyword: str | None = None,
) -> Dict[str, Any]:
    """Fetch a single page from AIDP API (simple passthrough).

    ``keyword`` is forwarded to AIDP as an optional server-side filter.
    """
    normalized_url = _validate_params(server_url, api_key)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    list_path = f"{_get_list_path()}{_build_list_query(page, page_size, keyword)}"
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


def _kb_matches_keyword(item: Dict[str, Any], keyword: str) -> bool:
    """Return whether a KB row carries ``keyword`` in its name or description.

    Only used as the fallback for AIDP builds that ignore the server-side
    filter, so plain case-insensitive substring semantics are enough — the
    upstream match set is always trusted when the upstream actually narrowed.
    """
    needle = keyword.lower()
    for field in ("kds_name", "name", "description"):
        value = item.get(field)
        if isinstance(value, str) and needle in value.lower():
            return True
    return False


def fetch_all_aidp_knowledge_bases_impl(
    server_url: str,
    api_key: str,
    keyword: str | None = None,
) -> Dict[str, Any]:
    """Fetch every AIDP knowledge-base page using the dedicated Count API.

    The list response does not expose a reliable global count and its
    ``next_link`` may contain a sentinel tenant. The Count endpoint determines
    the number of pages, and every list request uses the configured tenant.
    Duplicate resources are removed by ``kds_id`` while preserving their
    first-seen order.

    ``keyword`` is forwarded to every list call so AIDP filters server-side.
    The Count API has no keyword support, so the page count is deliberately
    derived from the unfiltered total: AIDP returns the matching subset on the
    earliest pages and empty pages afterwards, which this loop tolerates. The
    caller therefore still receives every match.

    A build that ignores ``keyword`` answers with the whole catalog instead. That
    is detected after the loop (the collected set is not narrower than the
    reported total) and the keyword is then applied locally, so a search cannot
    silently return the unfiltered list.
    """
    normalized_url = _validate_params(server_url, api_key)
    normalized_keyword = (keyword or "").strip()
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
            page_path = (
                f"{_get_list_path()}"
                f"{_build_list_query(current_page, page_size, keyword)}"
            )
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
        result_count = accumulated_count
        if normalized_keyword and accumulated_count >= total_count:
            # The upstream answered a keyword request with the entire catalog, so
            # this AIDP build ignores the parameter. Narrow locally instead of
            # reporting an unfiltered list as a search result: every KB has
            # already been fetched above, so the match set stays complete.
            all_items = [
                item
                for item in all_items
                if _kb_matches_keyword(item, normalized_keyword)
            ]
            result_count = len(all_items)
            logger.info(
                "AIDP returned the full catalog (%d of %d reported KBs) for keyword %r; "
                "applied the local name/description filter -> %d match(es)",
                accumulated_count,
                total_count,
                normalized_keyword,
                result_count,
            )
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
            "total_count": result_count,
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


def remove_aidp_docs_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    file_uuids: List[str],
) -> Dict[str, Any]:
    """Remove one or more documents from an AIDP knowledge base."""
    normalized_url = _validate_params(server_url, api_key)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    remove_path = f"{_get_list_path()}/{kds_id}/KnowledgeFiles/Remove"
    remove_url = urljoin(f"{normalized_url}/", remove_path)
    logger.info("Removing %d AIDP documents from %s", len(file_uuids), remove_url)

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=_AIDP_READ_TIMEOUT_SECONDS,
            verify_ssl=False,
        )
        response = _request_with_retry(
            lambda: client.post(
                remove_url,
                headers=headers,
                json={"file_uuids": file_uuids},
            ),
            context=f"remove-docs:{kds_id}",
        )
        response.raise_for_status()
        result = response.json()
        return result
    except httpx.RequestError as e:
        logger.exception("AIDP document removal request failed: %s", e)
        raise AppException(
            ErrorCode.AIDP_CONNECTION_ERROR,
            f"AIDP API request failed: {str(e)}",
        )
    except httpx.HTTPStatusError as e:
        _raise_aidp_http_error(e, "document removal")
    except ValueError as e:
        logger.exception("Failed to parse AIDP document removal response: %s", e)
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            f"Failed to parse AIDP API response: {str(e)}",
        )


async def stream_aidp_doc_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    file_uuid: str,
) -> httpx.Response:
    """Open a streaming response for one AIDP document."""
    normalized_url = _validate_params(server_url, api_key)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    download_path = f"{_get_list_path()}/{kds_id}/KnowledgeFiles/Download"
    download_url = urljoin(f"{normalized_url}/", download_path)
    logger.info("Downloading AIDP document %s from %s", file_uuid, download_url)

    response: httpx.Response | None = None
    try:
        client = http_client_manager.get_async_client(
            base_url=normalized_url,
            timeout=_AIDP_DOWNLOAD_TIMEOUT_SECONDS,
            verify_ssl=False,
        )
        response = await client.send(
            client.build_request(
                "POST",
                download_url,
                headers=headers,
                json={"file_uuid": file_uuid},
            ),
            stream=True,
        )
        if response.status_code >= 400:
            await response.aread()
        response.raise_for_status()
        return response
    except httpx.RequestError as e:
        if response is not None:
            await response.aclose()
        logger.exception("AIDP document download request failed: %s", e)
        raise AppException(
            ErrorCode.AIDP_CONNECTION_ERROR,
            f"AIDP API request failed: {str(e)}",
        )
    except httpx.HTTPStatusError as e:
        if response is not None:
            await response.aclose()
        _raise_aidp_http_error(e, "document download")


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


# ==================== Knowledge-file history (all-status listing) ====================

# Channel entries are read through alias lists because AIDP deployments spell
# these fields differently. Only the forms actually observed are listed; adding
# a new spelling here is enough to support another deployment.
_CHANNEL_FS_ID_KEYS = (
    "fs_id",
    "fsId",
    "fsid",
    "file_system_id",
    "fileSystemId",
    "file_sys_id",
    "filesystem_id",
)
_CHANNEL_SRC_DIR_KEYS = (
    "src_dir",
    "srcDir",
    "source_dir",
    "sourceDir",
    "source_path",
    "sourcePath",
    "dir_path",
    "dirPath",
    "input_dir",
    "inputDir",
)
_CHANNEL_KB_ID_KEYS = (
    "kds_id",
    "kdsId",
    "knowledge_base_id",
    "knowledgeBaseId",
    "kb_id",
    "kbId",
    "knowledge_base_ids",
    "knowledgeBaseIds",
)


def _first_non_empty_string(item: Dict[str, Any], keys: tuple) -> str | None:
    """Return the first non-empty string among ``keys``, or ``None``."""
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _lookup_channel_field(item: Dict[str, Any], keys: tuple) -> str | None:
    """Return the first non-empty string among ``keys``, nested dicts included.

    Deployments nest the addressing fields differently (for example under a
    ``config`` or ``file_system`` object next to the channel's own keys), so one
    level of nested dictionaries is inspected before giving up. Without this a
    channel holding both values could look unusable purely because of nesting,
    which silently drops the whole status feature back to the ingested-files
    listing.
    """
    found = _first_non_empty_string(item, keys)
    if found is not None:
        return found
    for value in item.values():
        if isinstance(value, dict):
            found = _first_non_empty_string(value, keys)
            if found is not None:
                return found
    return None


def _references_kb_id(value: Any, kds_id: str) -> bool:
    """Return whether a channel field references ``kds_id``.

    Accepts a scalar id, a list of ids, or a directory string such as
    ``/knowledge/<kds_id>`` — a channel is bound to a knowledge base either by
    an explicit id field or by pointing its source directory at that KB.
    """
    if isinstance(value, str):
        return value == kds_id or kds_id in value.split("/")
    if isinstance(value, (list, tuple, set)):
        return any(_references_kb_id(entry, kds_id) for entry in value)
    return False


def _channel_references_kb_id(item: Dict[str, Any], kds_id: str) -> bool:
    """Return whether any channel field (nested ones included) references the KB.

    Fields are matched by name first, then every remaining scalar/list value is
    checked so a build that binds a channel to its knowledge base through an
    undocumented field (a pipeline name, a path) still resolves.
    """
    for key, value in item.items():
        if key in _CHANNEL_KB_ID_KEYS and _references_kb_id(value, kds_id):
            return True
        if isinstance(value, dict) and _channel_references_kb_id(value, kds_id):
            return True
        if isinstance(value, (str, list, tuple, set)) and _references_kb_id(
            value, kds_id
        ):
            return True
    return False


def select_aidp_channel(
    channels: List[Dict[str, Any]],
    kds_id: str | None = None,
) -> Dict[str, str] | None:
    """Pick the ingestion channel whose files feed ``kds_id``.

    Selection order:
      1. a channel that references ``kds_id`` (id field or source directory),
      2. otherwise the first channel carrying both ``fs_id`` and a source dir.

    Step 2 covers deployments that keep a single channel per tenant, where the
    history lookup is intentionally directory-wide. Returns ``None`` when no
    channel carries the pair the history API needs, so the caller can fall back
    to the completed-files listing.
    """
    usable: List[Dict[str, str]] = []
    for channel in channels:
        if not isinstance(channel, dict):
            continue
        fs_id = _lookup_channel_field(channel, _CHANNEL_FS_ID_KEYS)
        src_dir = _lookup_channel_field(channel, _CHANNEL_SRC_DIR_KEYS)
        if not fs_id or not src_dir:
            continue
        usable.append({"fs_id": fs_id, "src_dir": src_dir})
        if kds_id and _channel_references_kb_id(channel, kds_id):
            return usable[-1]

    return usable[0] if usable else None


def list_aidp_channels_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    tenant_id: str | None = None,
) -> Dict[str, Any]:
    """List the ingestion pipelines feeding one knowledge base via AIDP API.

    Endpoint: ``GET /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{kds_id}/Channels``
    Response: ``{"value": [{"fs_id": ..., "src_dir": ...}, ...]}``
    """
    normalized_url = _validate_params(server_url, api_key)
    if not isinstance(kds_id, str) or not kds_id.strip():
        raise AppException(
            ErrorCode.AIDP_CONFIG_INVALID,
            "AIDP channel listing requires a non-empty knowledge base id",
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    channels_path = _get_channels_path(kds_id, tenant_id)
    channels_url = urljoin(f"{normalized_url}/", channels_path)
    logger.info("Listing AIDP channels from %s", channels_url)

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=_AIDP_READ_TIMEOUT_SECONDS,
            verify_ssl=False,
        )
        response = _request_with_retry(
            lambda: client.get(channels_url, headers=headers),
            context="list-channels",
        )
        response.raise_for_status()
        result = response.json()
        items = _extract_list_payload(result)
        if items is None:
            raise AppException(
                ErrorCode.AIDP_RESPONSE_ERROR,
                "Unexpected AIDP channel list response format",
            )
        # Downstream readers always read ``value``, so the extracted items are
        # re-emitted under that canonical key whichever envelope this build used.
        payload = result if isinstance(result, dict) else {}
        payload["value"] = [item for item in items if isinstance(item, dict)]
        return payload
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


def list_aidp_doc_history_impl(
    server_url: str,
    api_key: str,
    fs_id: str,
    dir_path: str,
    kds_id: str,
    tenant_id: str | None = None,
) -> Dict[str, Any]:
    """List every file in a channel directory regardless of processing status.

    Endpoint: ``POST /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{kds_id}/KnowledgeFiles/History``
    Body: ``{"fs_id": <str>, "dir_path": <str>}``
    Response: ``{"value": [<document with status>, ...]}``

    Unlike ``list_aidp_docs_impl`` this returns files that are still being
    chunked/embedded (``PROCESSING``) or that failed (``FAILED``), which is what
    lets the UI show an upload immediately instead of only after ingestion.
    """
    normalized_url = _validate_params(server_url, api_key)

    if not isinstance(kds_id, str) or not kds_id.strip():
        raise AppException(
            ErrorCode.AIDP_CONFIG_INVALID,
            "AIDP file history requires a non-empty knowledge base id",
        )
    normalized_fs_id = fs_id.strip() if isinstance(fs_id, str) else ""
    normalized_dir_path = dir_path.strip() if isinstance(dir_path, str) else ""
    if not normalized_fs_id or not normalized_dir_path:
        raise AppException(
            ErrorCode.AIDP_CONFIG_INVALID,
            "AIDP file history requires a non-empty fs_id and dir_path",
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    history_path = _get_doc_history_path(kds_id, tenant_id)
    history_url = urljoin(f"{normalized_url}/", history_path)
    logger.info(
        "Listing AIDP knowledge-file history from %s (fs_id=%s, dir_path=%s)",
        history_url,
        normalized_fs_id,
        normalized_dir_path,
    )

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=_AIDP_READ_TIMEOUT_SECONDS,
            verify_ssl=False,
        )
        response = _request_with_retry(
            lambda: client.post(
                history_url,
                headers=headers,
                json={"fs_id": normalized_fs_id, "dir_path": normalized_dir_path},
            ),
            context=f"list-doc-history:{normalized_fs_id}",
        )
        response.raise_for_status()
        result = response.json()
        items = _extract_list_payload(result)
        if items is None:
            raise AppException(
                ErrorCode.AIDP_RESPONSE_ERROR,
                "Unexpected AIDP file history response format",
            )
        normalized_items = [
            _normalize_history_doc(item) if isinstance(item, dict) else item
            for item in items
        ]
        _warn_when_history_status_unreadable(normalized_items, normalized_fs_id)
        payload = result if isinstance(result, dict) else {}
        payload["value"] = normalized_items
        return payload
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
