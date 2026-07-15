"""
AIDP Service Layer
Handles API calls to AIDP for paginated knowledge base listing.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import urljoin

import httpx

from consts.error_code import ErrorCode
from consts.exceptions import AppException
from nexent.utils.http_client_manager import http_client_manager

logger = logging.getLogger("aidp_service")

_LIST_PATH = "/KnowledgeBase/Tenants/aidp/KnowledgeBases"


def _timestamp_to_iso(value: Any) -> str | None:
    """Convert a numeric Unix timestamp (seconds or milliseconds) to ISO-8601 UTC.

    Returns None if the input is not a number, so optional fields stay optional
    in the output (frontend checks ``doc.created_at`` for undefined).
    """
    if value in (None, "", False):
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

    list_path = f"{_LIST_PATH}?page={page}&page_size={page_size}"
    list_url = urljoin(f"{normalized_url}/", list_path)
    logger.info("Fetching AIDP knowledge bases from %s", list_url)

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=60.0,
            verify_ssl=False,
        )
        response = client.get(list_url, headers=headers)
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


def _extract_tenant_from_url(url: str) -> str | None:
    """Extract tenant ID from a URL like /KnowledgeBase/Tenants/{tenant}/KnowledgeBases."""
    import re
    match = re.search(r"/Tenants/([^/]+)/", url)
    return match.group(1) if match else None


def fetch_all_aidp_knowledge_bases_impl(
    server_url: str,
    api_key: str,
) -> Dict[str, Any]:
    """Fetch all knowledge bases from AIDP by following next_link until exhausted.

    AIDP does not return a true total count, so we follow next_link pages
    until there is no next_link left. We also detect the real tenant ID
    from the first response's next_link (AIDP embeds it there) and use it
    for any manual page construction needed.
    """
    normalized_url = _validate_params(server_url, api_key)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=120.0,
            verify_ssl=False,
        )

        all_items: List[Any] = []
        current_page = 1
        max_pages = 1000
        page_size = 100
        detected_tenant: str | None = None

        # Build the first request URL using the known path pattern
        first_path = f"{_LIST_PATH}?page=1&page_size={page_size}"
        current_url: str | None = urljoin(f"{normalized_url}/", first_path)

        while current_page <= max_pages and current_url:
            logger.info(
                "Fetching AIDP KBs — page %d from %s",
                current_page,
                current_url,
            )

            response = client.get(current_url, headers=headers)
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

            all_items.extend(page_items)

            # Detect real tenant from next_link on the first page
            if current_page == 1 and detected_tenant is None:
                raw_next = result.get("next_link") or result.get("next") or ""
                detected_tenant = _extract_tenant_from_url(str(raw_next))
                if detected_tenant:
                    logger.info("Detected AIDP tenant: %s", detected_tenant)

            # Follow next_link if present, otherwise construct next page manually
            raw_next = result.get("next_link") or result.get("next") or ""
            next_url_str = str(raw_next).strip()
            if next_url_str:
                current_url = urljoin(normalized_url + "/", next_url_str)
                current_page += 1
            else:
                current_url = None

        total_count = len(all_items)
        logger.info("AIDP KBs: accumulated %d total items (tenant=%s)", total_count, detected_tenant)

        return {
            "value": all_items,
            "total_count": total_count,
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

    count_path = f"{_LIST_PATH}/0/Count"
    count_url = urljoin(f"{normalized_url}/", count_path)
    logger.info("Counting AIDP knowledge bases from %s", count_url)

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=60.0,
            verify_ssl=False,
        )
        response = client.post(count_url, headers=headers, json={"is_personal": 0})
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
    "vlm_model": "",
    "is_personal": 0,
    "topk": 10,
    "similarity": 0.0,
    "smartsplit": 1,
    "caption_enable": 0,
}


def _apply_create_defaults(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fill missing AIDP create-KB fields with reference defaults.

    Defensive layer: if the client omits any of these fields, the backend
    injects them before forwarding to AIDP. Matches the frontend
    AIDP_CREATE_DEFAULTS and the SDK build_create_payload defaults exactly.

    Special rule: if payload.is_multimodal is truthy, caption_enable defaults
    to 1 (matching SDK mapper logic).
    """
    result = dict(payload)
    for key, default in _AIDP_CREATE_DEFAULTS.items():
        if key not in result:
            result[key] = default
    if result.get("is_multimodal") and "caption_enable" not in payload:
        result["caption_enable"] = 1
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

    create_url = urljoin(f"{normalized_url}/", _LIST_PATH)
    logger.info("Creating AIDP knowledge base at %s", create_url)

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=60.0,
            verify_ssl=False,
        )
        response = client.put(create_url, headers=headers, json=full_payload)
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

    get_path = f"{_LIST_PATH}/{kds_id}"
    get_url = urljoin(f"{normalized_url}/", get_path)
    logger.info("Getting AIDP knowledge base from %s", get_url)

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=60.0,
            verify_ssl=False,
        )
        response = client.get(get_url, headers=headers)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise AppException(
                ErrorCode.AIDP_RESPONSE_ERROR,
                "Unexpected AIDP knowledge base response format",
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

    update_path = f"{_LIST_PATH}/{kds_id}"
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

    delete_path = f"{_LIST_PATH}/{kds_id}"
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

    upload_path = f"{_LIST_PATH}/{kds_id}/KnowledgeFiles/Upload"
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

    count_path = f"{_LIST_PATH}/{kds_id}/KnowledgeFiles/Count"
    count_url = urljoin(f"{normalized_url}/", count_path)
    logger.info("Counting AIDP documents in KB %s from %s", kds_id, count_url)

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=60.0,
            verify_ssl=False,
        )
        # Body is empty per AIDP contract; use content=b"" to send an explicit
        # empty POST (httpx may skip the body otherwise).
        response = client.post(count_url, headers=headers, content=b"")
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

    list_path = f"{_LIST_PATH}/{kds_id}/KnowledgeFiles?page={page}&page_size={page_size}"
    list_url = urljoin(f"{normalized_url}/", list_path)
    logger.info("Listing AIDP documents from %s", list_url)

    try:
        client = http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=60.0,
            verify_ssl=False,
        )
        response = client.get(list_url, headers=headers)
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
