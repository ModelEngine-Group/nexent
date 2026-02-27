"""
Dify Service Layer
Handles API calls to Dify for knowledge base operations.

This service layer provides functionality to interact with Dify's API,
including fetching datasets (knowledge bases) and transforming responses
to DataMate-compatible format for frontend compatibility.
"""
import json
import logging
from typing import Any, Dict

import httpx

from consts.error_code import ErrorCode
from consts.exceptions import AppException
from nexent.utils.http_client_manager import http_client_manager

logger = logging.getLogger("dify_service")


def fetch_dify_datasets_impl(
        dify_api_base: str,
        api_key: str,
) -> Dict[str, Any]:
    """
    Fetch datasets (knowledge bases) from Dify API and transform to DataMate-compatible format.

    Args:
        dify_api_base: Dify API base URL
        api_key: Dify API key with Bearer token

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
                            "chunk_count": 100,
                            "store_size": "",
                            "process_source": "Dify",
                            "embedding_model": "",
                            "embedding_dim": 0,
                            "creation_date": timestamp,
                            "update_date": timestamp
                        },
                        "search_performance": {
                            "total_search_count": 0,
                            "hit_count": 0
                        }
                    }
                },
                ...
            ],
            "pagination": {
                "embedding_available": False
            }
        }

    Raises:
        ValueError: If invalid parameters provided
        Exception: If API request fails
    """
    # Validate inputs
    if not dify_api_base or not isinstance(dify_api_base, str):
        raise AppException(
            ErrorCode.DIFY_CONFIG_INVALID,
            "Dify API URL is required and must be a non-empty string"
        )

    # Validate URL format
    if not (dify_api_base.startswith("http://") or dify_api_base.startswith("https://")):
        raise AppException(
            ErrorCode.DIFY_CONFIG_INVALID,
            "Dify API URL must start with http:// or https://"
        )

    if not api_key or not isinstance(api_key, str):
        raise AppException(ErrorCode.DIFY_CONFIG_INVALID,
                           "Dify API key is required and must be a non-empty string")

    # Normalize API base URL
    api_base = dify_api_base.rstrip("/")

    # Remove /v1 suffix if present to avoid URL duplication
    # E.g., "https://api.dify.ai/v1" -> "https://api.dify.ai"
    if api_base.endswith("/v1"):
        api_base = api_base[:-3]

    # Build request URL with pagination
    url = f"{api_base}/v1/datasets"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    logger.info(f"Fetching Dify datasets from: {url}")

    try:
        # Use shared HttpClientManager for connection pooling
        client = http_client_manager.get_sync_client(
            base_url=api_base,
            timeout=5.0,
            verify_ssl=False
        )
        response = client.get(url, headers=headers)
        response.raise_for_status()

        result = response.json()

        # Parse Dify API response
        datasets_data = result.get("data", [])

        # Transform to DataMate-compatible format
        indices = []
        indices_info = []
        embedding_available = False  # Default value if no datasets or all skipped

        for dataset in datasets_data:
            dataset_id = dataset.get("id", "")
            dataset_name = dataset.get("name", "")
            document_count = dataset.get("document_count", 0)
            created_at = dataset.get("created_at", 0)
            updated_at = dataset.get("updated_at", 0)
            embedding_available = dataset.get("embedding_available", False)

            if not dataset_id:
                continue

            indices.append(dataset_id)

            # Create indices_info entry (compatible with DataMate format)
            indices_info.append({
                "name": dataset_id,
                "display_name": dataset_name,
                "stats": {
                    "base_info": {
                        "doc_count": document_count,
                        "chunk_count": 0,  # Dify doesn't provide chunk count directly
                        "store_size": "",
                        "process_source": "Dify",
                        "embedding_model": dataset.get("embedding_model", ""),
                        "embedding_dim": 0,
                        "creation_date": created_at * 1000 if created_at else 0,  # Convert to milliseconds
                        "update_date": updated_at * 1000 if updated_at else 0
                    },
                    "search_performance": {
                        "total_search_count": 0,
                        "hit_count": 0
                    }
                }
            })

        return {
            "indices": indices,
            "count": len(indices),
            "indices_info": indices_info,
            "pagination": {
                "embedding_available": embedding_available
            }
        }

    except httpx.RequestError as e:
        logger.error(f"Dify API request failed: {str(e)}")
        raise AppException(ErrorCode.DIFY_CONNECTION_ERROR,
                           f"Dify API request failed: {str(e)}")
    except httpx.HTTPStatusError as e:
        logger.error(
            f"Dify API HTTP error: {str(e)}, status_code: {e.response.status_code}")
        # Map HTTP status to specific error code
        if e.response.status_code == 401:
            logger.error("Raising DIFY_AUTH_ERROR for 401 error")
            raise AppException(ErrorCode.DIFY_AUTH_ERROR,
                               f"Dify authentication failed: {str(e)}")
        elif e.response.status_code == 403:
            logger.error("Raising DIFY_AUTH_ERROR for 403 error")
            raise AppException(ErrorCode.DIFY_AUTH_ERROR,
                               f"Dify access forbidden: {str(e)}")
        elif e.response.status_code == 429:
            logger.error("Raising DIFY_RATE_LIMIT for 429 error")
            raise AppException(ErrorCode.DIFY_RATE_LIMIT,
                               f"Dify API rate limit exceeded: {str(e)}")
        else:
            logger.error(
                f"Raising DIFY_SERVICE_ERROR for status {e.response.status_code}")
            raise AppException(ErrorCode.DIFY_SERVICE_ERROR,
                               f"Dify API HTTP error {e.response.status_code}: {str(e)}")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Dify API response: {str(e)}")
        raise AppException(ErrorCode.DIFY_RESPONSE_ERROR,
                           f"Failed to parse Dify API response: {str(e)}")
    except KeyError as e:
        logger.error(
            f"Unexpected Dify API response format: missing key {str(e)}")
        raise AppException(ErrorCode.DIFY_RESPONSE_ERROR,
                           f"Unexpected Dify API response format: missing key {str(e)}")
