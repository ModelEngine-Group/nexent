"""
iData Service Layer
Handles API calls to iData for knowledge space operations.

This service layer provides functionality to interact with iData's API,
including fetching knowledge spaces and transforming responses
to a format compatible with the frontend.
"""
import json
import logging
from typing import Any, Dict, List

import httpx

from consts.error_code import ErrorCode
from consts.exceptions import AppException
from nexent.utils.http_client_manager import http_client_manager

logger = logging.getLogger("idata_service")


def _validate_idata_base_params(
        idata_api_base: str,
        api_key: str,
        user_id: str,
) -> None:
    """
    Validate common iData API parameters.

    Args:
        idata_api_base: iData API base URL
        api_key: iData API key
        user_id: iData user ID

    Raises:
        AppException: If any parameter is invalid
    """
    if not idata_api_base or not isinstance(idata_api_base, str):
        raise AppException(
            ErrorCode.IDATA_CONFIG_INVALID,
            "iData API URL is required and must be a non-empty string"
        )

    if not (idata_api_base.startswith("http://") or idata_api_base.startswith("https://")):
        raise AppException(
            ErrorCode.IDATA_CONFIG_INVALID,
            "iData API URL must start with http:// or https://"
        )

    if not api_key or not isinstance(api_key, str):
        raise AppException(
            ErrorCode.IDATA_CONFIG_INVALID,
            "iData API key is required and must be a non-empty string"
        )

    if not user_id or not isinstance(user_id, str):
        raise AppException(
            ErrorCode.IDATA_CONFIG_INVALID,
            "iData user ID is required and must be a non-empty string"
        )


def _normalize_api_base(idata_api_base: str) -> str:
    """
    Normalize API base URL by removing trailing slash.

    Args:
        idata_api_base: iData API base URL

    Returns:
        Normalized API base URL
    """
    return idata_api_base.rstrip("/")


def _make_idata_request(
        api_base: str,
        url: str,
        headers: Dict[str, str],
        request_body: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Make HTTP POST request to iData API and handle common errors.

    Args:
        api_base: Normalized API base URL
        url: Full request URL
        headers: Request headers
        request_body: Request body as dictionary

    Returns:
        Parsed JSON response

    Raises:
        AppException: If request fails or response is invalid
    """
    logger.info(f"Making iData API request to: {url}")

    try:
        # Use shared HttpClientManager for connection pooling
        # Note: ssl_verify is set to False as per requirement (self-signed certificate)
        client = http_client_manager.get_sync_client(
            base_url=api_base,
            timeout=10.0,
            verify_ssl=False
        )
        response = client.post(url, headers=headers, json=request_body)
        response.raise_for_status()

        return response.json()

    except httpx.RequestError as e:
        logger.error(f"iData API request failed: {str(e)}")
        raise AppException(
            ErrorCode.IDATA_CONNECTION_ERROR,
            f"iData API request failed: {str(e)}"
        )
    except httpx.HTTPStatusError as e:
        logger.error(
            f"iData API HTTP error: {str(e)}, status_code: {e.response.status_code}")
        # Map HTTP status to specific error code
        if e.response.status_code == 401:
            logger.error("Raising IDATA_AUTH_ERROR for 401 error")
            raise AppException(
                ErrorCode.IDATA_AUTH_ERROR,
                f"iData authentication failed: {str(e)}"
            )
        elif e.response.status_code == 403:
            logger.error("Raising IDATA_AUTH_ERROR for 403 error")
            raise AppException(
                ErrorCode.IDATA_AUTH_ERROR,
                f"iData access forbidden: {str(e)}"
            )
        elif e.response.status_code == 429:
            logger.error("Raising IDATA_RATE_LIMIT for 429 error")
            raise AppException(
                ErrorCode.IDATA_RATE_LIMIT,
                f"iData API rate limit exceeded: {str(e)}"
            )
        else:
            logger.error(
                f"Raising IDATA_SERVICE_ERROR for status {e.response.status_code}")
            raise AppException(
                ErrorCode.IDATA_SERVICE_ERROR,
                f"iData API HTTP error {e.response.status_code}: {str(e)}"
            )
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse iData API response: {str(e)}")
        raise AppException(
            ErrorCode.IDATA_RESPONSE_ERROR,
            f"Failed to parse iData API response: {str(e)}"
        )


def _parse_idata_response(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Parse iData API response and validate format.

    Args:
        result: Parsed JSON response from iData API

    Returns:
        List of data items from response

    Raises:
        AppException: If response format is invalid
    """
    # Expected format: {"code": "1", "msg": "...", "data": [...], "msgParams": null}
    code = result.get("code", "")
    if code != "1":
        msg = result.get("msg", "Unknown error")
        logger.error(
            f"iData API returned error code: {code}, message: {msg}")
        raise AppException(
            ErrorCode.IDATA_SERVICE_ERROR,
            f"iData API error: {msg}"
        )

    data = result.get("data", [])
    if not isinstance(data, list):
        logger.error(
            f"Unexpected iData API response format: data is not a list")
        raise AppException(
            ErrorCode.IDATA_RESPONSE_ERROR,
            "Unexpected iData API response format: data is not a list"
        )

    return data


def fetch_idata_knowledge_spaces_impl(
        idata_api_base: str,
        api_key: str,
        user_id: str,
) -> List[Dict[str, str]]:
    """
    Fetch knowledge spaces from iData API.

    Args:
        idata_api_base: iData API base URL
        api_key: iData API key with Bearer token
        user_id: iData user ID

    Returns:
        List of dictionaries containing knowledge spaces with id and name:
        [
            {
                "id": "6cbf949946bf4b769c073259406b04f8",
                "name": "test1"
            },
            ...
        ]

    Raises:
        AppException: If API request fails or response is invalid
    """
    # Validate inputs
    _validate_idata_base_params(idata_api_base, api_key, user_id)

    # Normalize API base URL
    api_base = _normalize_api_base(idata_api_base)

    # Build request URL
    url = f"{api_base}/apiaccess/modelmate/north/machine/v1/knowledgeSpaces/query"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Request body
    request_body = {
        "userId": user_id
    }

    # Make request and parse response
    result = _make_idata_request(api_base, url, headers, request_body)
    data = _parse_idata_response(result)

    # Extract id and name from each knowledge space
    knowledge_spaces = []
    for item in data:
        if not isinstance(item, dict):
            continue

        space_id = item.get("id")
        space_name = item.get("name")

        if space_id and space_name:
            knowledge_spaces.append({
                "id": str(space_id),
                "name": str(space_name)
            })

    return knowledge_spaces


def fetch_idata_datasets_impl(
        idata_api_base: str,
        api_key: str,
        user_id: str,
        knowledge_space_id: str,
) -> Dict[str, Any]:
    """
    Fetch datasets (knowledge bases) from iData API and transform to DataMate-compatible format.

    Args:
        idata_api_base: iData API base URL
        api_key: iData API key with Bearer token
        user_id: iData user ID
        knowledge_space_id: Knowledge space ID

    Returns:
        Dictionary containing knowledge bases in DataMate-compatible format:
        {
            "indices": ["dataset_id_1", "dataset_id_2", ...],
            "count": 2,
            "indices_info": [
                {
                    "name": "dataset_id_1",
                    "display_name": "知识库名称",
                    "stats": {
                        "base_info": {
                            "doc_count": 10,
                            "process_source": "iData"
                        }
                    }
                },
                ...
            ]
        }

    Raises:
        AppException: If API request fails or response is invalid
    """
    # Validate inputs
    _validate_idata_base_params(idata_api_base, api_key, user_id)

    if not knowledge_space_id or not isinstance(knowledge_space_id, str):
        raise AppException(
            ErrorCode.IDATA_CONFIG_INVALID,
            "Knowledge space ID is required and must be a non-empty string"
        )

    # Normalize API base URL
    api_base = _normalize_api_base(idata_api_base)

    # Build request URL
    url = f"{api_base}/apiaccess/modelmate/north/machine/v1/knowledgeBases/query"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Request body
    request_body = {
        "userId": user_id,
        "knowledgeSpaceId": knowledge_space_id
    }

    # Make request and parse response
    result = _make_idata_request(api_base, url, headers, request_body)
    data = _parse_idata_response(result)

    # Transform to DataMate-compatible format
    indices = []
    indices_info = []

    for knowledge_base in data:
        if not isinstance(knowledge_base, dict):
            continue

        kb_id = knowledge_base.get("id", "")
        kb_name = knowledge_base.get("name", "")
        file_count = knowledge_base.get("fileCount", 0)

        if not kb_id:
            continue

        indices.append(kb_id)

        # Create indices_info entry (compatible with DataMate format)
        indices_info.append({
            "name": kb_id,
            "display_name": kb_name,
            "stats": {
                "base_info": {
                    "doc_count": file_count,
                    "process_source": "iData"
                }
            }
        })

    return {
        "indices": indices,
        "count": len(indices),
        "indices_info": indices_info
    }
