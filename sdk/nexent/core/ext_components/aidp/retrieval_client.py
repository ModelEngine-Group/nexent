# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Retrieval-only transport; wrappers own their response and error semantics."""
import time


RETRY_STATUSES = frozenset({502, 503, 504})
MAX_ATTEMPTS = 3


def post_retrieval(client, url, api_key, payload):
    for attempt in range(MAX_ATTEMPTS):
        response = client.post(url, headers={"Content-Type": "application/json",
                                            "Authorization": f"Bearer {api_key}"}, json=payload)
        if response.status_code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS - 1:
            return response
        time.sleep(0.5 * 2 ** attempt)
