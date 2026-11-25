# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own and release isolated ES indices on an explicitly supplied test service."""

import os
from uuid import uuid4

import pytest
from elasticsearch import AsyncElasticsearch, Elasticsearch


@pytest.fixture
def owned_resource_es(monkeypatch):
    from management.services.conversation import nl2agent_resource_index as storage

    url = os.environ.get("NEXENT_TEST_NL2AGENT_ES_URL")
    if not url:
        raise RuntimeError("A disposable NEXENT_TEST_NL2AGENT_ES_URL is required")
    prefix = "nl2agent-resources-test-" + uuid4().hex
    monkeypatch.setattr(storage, "INDEX_PREFIX", prefix)
    monkeypatch.setattr(storage, "create_client", lambda: Elasticsearch(url, max_retries=0))
    monkeypatch.setattr(storage, "create_async_client", lambda: AsyncElasticsearch(
        url, max_retries=0, connections_per_node=8))
    client = Elasticsearch(url, max_retries=0, request_timeout=10)
    assert client.info()["version"]["number"].startswith("8.")
    try:
        yield client, prefix
    finally:
        indices = list(client.indices.get(index=prefix + "-*", allow_no_indices=True))
        for name in indices:
            assert name.startswith(prefix + "-")
            client.indices.delete(index=name)
        assert not list(client.indices.get(index=prefix + "-*", allow_no_indices=True))
        client.close()
