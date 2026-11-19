# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded external DataMate inventory count; provider pagination stays local."""

import httpx
from nexent.storage.errors import DeadlineExceeded, OperationCancelled


def datamate_collection_count(base_url, *, context, client_factory=httpx.Client):
    context.remaining()
    with client_factory(timeout=min(5, context.remaining()), trust_env=False) as client:
        page, total_pages, count = 1, 1, 0
        while page <= total_pages:
            remaining = context.remaining()
            try:
                response = client.post(base_url.rstrip('/') + '/api/knowledge-base/list',
                                       json={'page': page, 'size': 20}, timeout=min(5, remaining))
            except httpx.TimeoutException:
                raise
            except httpx.HTTPError as error:
                raise RuntimeError(f'Failed to fetch DataMate knowledge bases: {error}') from error
            try:
                if response.status_code != 200:
                    detail = (response.json().get('detail', 'unknown error')
                              if response.headers.get('content-type', '').startswith('application/json') else response.text)
                    raise RuntimeError(f'Failed to get knowledge base list (status {response.status_code}): {detail}')
                data = response.json().get('data')
                if data:
                    if page == 1:
                        total_pages = data.get('totalPages', 1)
                    count += sum(item.get('id') is not None and item.get('type') == 'DOCUMENT'
                                 for item in data.get('content', []))
            except (DeadlineExceeded, OperationCancelled):
                raise
            except Exception as error:
                raise RuntimeError(f'Failed to fetch DataMate knowledge bases: {error}') from error
            finally:
                response.close()
            context.remaining()
            page += 1
        return count
