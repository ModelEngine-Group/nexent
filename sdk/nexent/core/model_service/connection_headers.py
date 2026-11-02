# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Validate operator headers outside model snapshots and request bodies."""

import json

from nexent.core.model_service.http_contracts import validate_headers


def connection_headers(value, *, api_key=None):
    if not isinstance(value, dict) or len(value) > 32:
        raise ValueError("MODEL_HTTP_HEADERS_INVALID")
    headers = validate_headers(value, credentials=True)
    if len(json.dumps(headers).encode("utf-8")) > 16384 or "content-type" in headers:
        raise ValueError("MODEL_HTTP_HEADERS_INVALID")
    if api_key and api_key.strip() and "authorization" in headers:
        raise ValueError("MODEL_HTTP_AUTH_CONFLICT")
    return headers
