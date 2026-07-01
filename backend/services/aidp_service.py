"""
AIDP Service Layer
Handles API calls to AIDP for paginated knowledge base listing.
"""
import logging
from typing import Any, Dict, List
from urllib.parse import urljoin

import httpx

from consts.error_code import ErrorCode
from consts.exceptions import AppException
from nexent.utils.http_client_manager import http_client_manager

logger = logging.getLogger("aidp_service")

_LIST_PATH = "/KnowledgeBase/Tenants/aidp/KnowledgeBases"


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
