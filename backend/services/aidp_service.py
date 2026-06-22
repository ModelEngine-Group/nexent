"""
AIDP Service Layer
Handles API calls to AIDP for paginated knowledge base listing.
"""
import logging
from typing import Any, Dict
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
    page_size: int = 20,
) -> Dict[str, Any]:
    """Fetch paginated knowledge bases from AIDP API."""
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
            timeout=20.0,
            verify_ssl=True,
        )
        response = client.get(list_url, headers=headers)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise AppException(
                ErrorCode.AIDP_SERVICE_ERROR,
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
