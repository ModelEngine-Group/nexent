import json
import logging
from typing import Any, Dict

import httpx

from consts.error_code import ErrorCode
from consts.exceptions import AppException
from nexent.utils.http_client_manager import http_client_manager

logger = logging.getLogger("ragflow_service")


def fetch_ragflow_datasets_impl(
    ragflow_api_base: str,
    api_key: str,
) -> Dict[str, Any]:
    """
    Fetch datasets from RAGFlow API.

    Args:
        ragflow_api_base: RAGFlow API base URL (e.g., 'http://localhost:9380')
        api_key: RAGFlow API key

    Returns:
        Dictionary containing datasets:
        {
            "data": [
                {
                    "id": "dataset_id",
                    "name": "Dataset Name",
                    "description": "...",
                    "doc_count": 10,
                    "chunk_count": 100,
                    "create_time": "...",
                    "update_time": "...",
                }
            ]
        }
    """
    if not ragflow_api_base or not isinstance(ragflow_api_base, str):
        raise AppException(
            ErrorCode.RAGFLOW_CONFIG_INVALID,
            "RAGFlow API URL is required and must be a non-empty string"
        )

    if not (ragflow_api_base.startswith("http://") or ragflow_api_base.startswith("https://")):
        raise AppException(
            ErrorCode.RAGFLOW_CONFIG_INVALID,
            "RAGFlow API URL must start with http:// or https://"
        )

    if not api_key or not isinstance(api_key, str):
        raise AppException(ErrorCode.RAGFLOW_CONFIG_INVALID,
                           "RAGFlow API key is required and must be a non-empty string")

    api_base = ragflow_api_base.rstrip("/")

    url = f"{api_base}/api/v1/datasets"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    logger.info(f"Fetching RAGFlow datasets from: {url}")

    try:
        client = http_client_manager.get_sync_client(
            base_url=api_base,
            timeout=10.0,
            verify_ssl=False
        )
        response = client.get(url, headers=headers)
        response.raise_for_status()

        result = response.json()

        if result.get("code") != 0:
            raise AppException(
                ErrorCode.RAGFLOW_SERVICE_ERROR,
                f"RAGFlow API returned error code {result.get('code')}: {result.get('message', 'Unknown error')}"
            )

        datasets = result.get("data", [])
        data = []
        for ds in datasets:
            data.append({
                "id": str(ds.get("id", "")),
                "name": ds.get("name", ""),
                "description": ds.get("description", ""),
                "doc_count": ds.get("doc_num", 0) or ds.get("document_count", 0),
                "chunk_count": ds.get("chunk_num", 0) or ds.get("chunk_count", 0),
                "create_time": str(ds.get("create_time", "")) or str(ds.get("create_date", "")),
                "update_time": str(ds.get("update_time", "")) or str(ds.get("update_date", "")),
            })

        return {"data": data}

    except httpx.RequestError as e:
        logger.error(f"RAGFlow API request failed: {str(e)}")
        raise AppException(ErrorCode.RAGFLOW_CONNECTION_ERROR,
                           f"RAGFlow API request failed: {str(e)}")
    except httpx.HTTPStatusError as e:
        logger.error(f"RAGFlow API HTTP error: {str(e)}, status_code: {e.response.status_code}")
        if e.response.status_code == 401:
            raise AppException(ErrorCode.RAGFLOW_AUTH_ERROR,
                               f"RAGFlow authentication failed: {str(e)}")
        elif e.response.status_code == 403:
            raise AppException(ErrorCode.RAGFLOW_AUTH_ERROR,
                               f"RAGFlow access forbidden: {str(e)}")
        else:
            raise AppException(ErrorCode.RAGFLOW_SERVICE_ERROR,
                               f"RAGFlow API HTTP error {e.response.status_code}: {str(e)}")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse RAGFlow API response: {str(e)}")
        raise AppException(ErrorCode.RAGFLOW_RESPONSE_ERROR,
                           f"Failed to parse RAGFlow API response: {str(e)}")
