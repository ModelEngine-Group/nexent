# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared FusionSearch transport, response contract and errors."""
import logging
import time

import httpx


logger = logging.getLogger(__name__)
RETRY_STATUSES = frozenset({502, 503, 504})
MAX_ATTEMPTS = 3


class AidpRetrievalError(RuntimeError):
    """Raised when a retrieval request or its response cannot be consumed."""


def post_retrieval(client, url, api_key, payload):
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = client.post(
                url, headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                json=payload,
            )
        except httpx.HTTPError as exc:
            message = f"AIDP HTTP error: request failed ({type(exc).__name__}, attempt {attempt + 1}/{MAX_ATTEMPTS})"
            logger.error(message)
            raise AidpRetrievalError(message) from exc
        if response.status_code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS - 1:
            break
        delay = 0.5 * 2 ** attempt
        logger.warning(
            "AIDP retrieval returned HTTP %d; attempt %d/%d failed; retrying in %.1f seconds",
            response.status_code, attempt + 1, MAX_ATTEMPTS, delay,
        )
        time.sleep(delay)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        message = f"AIDP FusionSearch returned HTTP {response.status_code} after {attempt + 1} attempts"
        logger.error(message)
        raise AidpRetrievalError(message) from exc
    try:
        data = response.json()
    except ValueError as exc:
        message = "AIDP returned invalid JSON"
        logger.error(message)
        raise AidpRetrievalError(message) from exc
    if not isinstance(data, dict) or not isinstance(data.get("result"), list):
        message = "AIDP response field 'result' must be a list"
        logger.error(message)
        raise AidpRetrievalError(message)
    return data["result"]
