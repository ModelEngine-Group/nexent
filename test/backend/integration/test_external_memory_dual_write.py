"""Integration coverage for internal + Mem0 transparent memory writes."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from unittest.mock import MagicMock

import httpx
import pytest

from nexent.memory.models import (
    ExternalMemoryItem,
    MemoryLayer,
    MemorySearchRequest,
    MemorySearchResult,
)
from nexent.memory.retrieval.normalizer import Normalizer
from services import memory_backend_adapter
from services import memory_external_provider_service as provider_service_module
from services import memory_ingestion_event_service as ingestion_service_module

from backend.memory_provider_plugins.mem0.provider import Mem0Provider


@pytest.mark.asyncio
async def test_ac_p3_36_37_38_transparent_dual_write_search_and_dedup(monkeypatch):
    stored_internal = []
    stored_mem0 = []
    original_async_client = httpx.AsyncClient

    def handler(request):
        payload = json.loads(request.content)
        if request.url.path == "/v3/memories/add/":
            stored_mem0.append(payload["messages"][0]["content"])
            return httpx.Response(
                200, json={"results": [{"id": "mem0-201", "event": "ADD"}]}
            )
        if request.url.path == "/v3/memories/search/":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"id": "mem0-201", "memory": content, "score": 0.89}
                        for content in stored_mem0
                    ]
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_async_client(transport=transport, **kwargs),
    )

    content = "The user prefers concise weekly status summaries."

    class InternalRecordService:
        def create_memory(self, **kwargs):
            stored_internal.append(kwargs["content"])
            return {"memory_id": 201, "content": kwargs["content"], "event": "ADD"}

    config = {
        "provider_config_id": 7,
        "provider_name": "mem0-partner",
        "enabled": True,
    }
    config_service = MagicMock()
    config_service.get_enabled_providers.return_value = [config]
    config_service.get_provider.return_value = config

    mem0 = Mem0Provider({"api_key": "test-key"})

    class ExternalProviderService:
        _config_service = config_service

        async def ingest(self, _config, _params, request):
            return await mem0.ingest(request)

    external_service = ExternalProviderService()
    monkeypatch.setattr(
        provider_service_module,
        "get_memory_external_provider_service",
        lambda: external_service,
    )
    monkeypatch.setattr(
        ingestion_service_module.memory_provider_config_param_db,
        "get_params",
        lambda _provider_id: {"plugin.name": "mem0", "plugin.api_key": "test-key"},
    )
    monkeypatch.setattr(
        ingestion_service_module.memory_external_ingest_event_log_db,
        "insert_event_log",
        lambda _data: 1,
    )
    monkeypatch.setattr(
        memory_backend_adapter,
        "get_memory_record_service",
        lambda: InternalRecordService(),
    )
    monkeypatch.setattr(
        memory_backend_adapter,
        "_resolve_tenant_embedding_model_info",
        lambda _tenant_id: MagicMock(),
    )

    result = await memory_backend_adapter._backend_store_hook(
        {
            "tenant_id": "tenant-1",
            "user_id": "user-1",
            "agent_id": "agent-5",
            "conversation_id": "conversation-1",
            "content": content,
            "layer": MemoryLayer.AGENT,
            "memory_type": "short_term",
        }
    )

    assert result["memory_id"] == 201
    assert stored_internal == [content]
    assert stored_mem0 == [content]

    external_results = await mem0.search(
        MemorySearchRequest(
            query="weekly status summaries",
            tenant_id="tenant-1",
            user_id="user-1",
            agent_id="agent-5",
            top_k=5,
        )
    )
    assert [item.content for item in external_results] == [content]

    normalized = Normalizer().normalize(
        [
            MemorySearchResult(
                memory_id=201,
                content=stored_internal[0],
                score=0.94,
                layer=MemoryLayer.AGENT,
                source="internal",
                metadata={"memory_type": "short_term"},
            )
        ],
        external_results=[
            ExternalMemoryItem(
                id=item.external_id or "",
                content=item.content,
                score=item.score,
                provider=item.source,
                metadata=item.metadata,
            )
            for item in external_results
        ],
    )

    assert len(normalized) == 1
    assert normalized[0].content == content
    assert normalized[0].is_external is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_mem0_transparent_dual_write_search_and_dedup(monkeypatch):
    api_key = os.environ.get("MEM0_API_KEY")
    if not api_key:
        pytest.skip("MEM0_API_KEY is required for live Mem0 verification")

    marker = uuid.uuid4().hex
    tenant_id = f"tenant-{marker}"
    user_id = f"nexent-live-{marker}"
    agent_id = f"agent-{marker}"
    conversation_id = f"conversation-{marker}"
    content = (
        f"Nexent live Mem0 verification marker {marker} prefers concise summaries."
    )
    base_url = os.environ.get("MEM0_BASE_URL", "https://api.mem0.ai")
    stored_internal = []

    class InternalRecordService:
        def create_memory(self, **kwargs):
            stored_internal.append(kwargs["content"])
            return {"memory_id": 301, "content": kwargs["content"], "event": "ADD"}

    config = {
        "provider_config_id": 9,
        "provider_name": "mem0-live",
        "enabled": True,
        "params": {
            "plugin.name": "mem0",
            "plugin.api_key": api_key,
            "plugin.base_url": base_url,
        },
    }
    config_service = MagicMock()
    config_service.get_enabled_providers.return_value = [config]
    config_service.get_provider.return_value = config
    mem0 = Mem0Provider({"api_key": api_key, "base_url": base_url})
    plugin_loader = MagicMock()
    plugin_loader.get_plugin.return_value = None
    plugin_loader.build_provider.return_value = mem0
    external_service = provider_service_module.MemoryExternalProviderService(
        plugin_loader=plugin_loader,
        config_service=config_service,
    )
    monkeypatch.setattr(
        provider_service_module,
        "get_memory_external_provider_service",
        lambda: external_service,
    )
    monkeypatch.setattr(
        ingestion_service_module.memory_provider_config_param_db,
        "get_params",
        lambda _provider_id: {
            "plugin.name": "mem0",
            "plugin.api_key": api_key,
            "plugin.base_url": base_url,
        },
    )
    monkeypatch.setattr(
        ingestion_service_module.memory_external_ingest_event_log_db,
        "insert_event_log",
        lambda _data: 1,
    )
    monkeypatch.setattr(
        memory_backend_adapter,
        "get_memory_record_service",
        lambda: InternalRecordService(),
    )
    monkeypatch.setattr(
        memory_backend_adapter,
        "_resolve_tenant_embedding_model_info",
        lambda _tenant_id: MagicMock(),
    )

    matching = []
    try:
        result = await memory_backend_adapter._backend_store_hook(
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "agent_id": agent_id,
                "conversation_id": conversation_id,
                "content": content,
                "layer": MemoryLayer.AGENT,
                "memory_type": "short_term",
            }
        )
        search_request = MemorySearchRequest(
            query=f"verification marker {marker}",
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_id,
            top_k=5,
        )
        external_results = []
        for _ in range(5):
            external_results = await external_service.search_all_enabled(
                tenant_id=tenant_id,
                request=search_request,
                limit=5,
            )
            if external_results:
                break
            await asyncio.sleep(2)
        matching = [item for item in external_results if marker in item.content]

        assert result["memory_id"] == 301
        assert stored_internal == [content]
        assert [item.content for item in matching] == [content]

        normalized = Normalizer().normalize(
            [
                MemorySearchResult(
                    memory_id=301,
                    content=stored_internal[0],
                    score=0.94,
                    layer=MemoryLayer.AGENT,
                    source="internal",
                    metadata={"memory_type": "short_term"},
                )
            ],
            external_results=[
                ExternalMemoryItem(
                    id=item.external_id or "",
                    content=item.content,
                    score=item.score,
                    provider=item.source,
                    metadata=item.metadata,
                )
                for item in matching
            ],
        )
        assert len(normalized) == 1
        assert normalized[0].content == content
        assert normalized[0].is_external is False
    finally:
        async with httpx.AsyncClient(timeout=30) as client:
            for item in matching:
                if item.external_id:
                    response = await client.delete(
                        f"{base_url.rstrip('/')}/v1/memories/{item.external_id}/",
                        headers=mem0._build_headers(),
                    )
                    assert response.status_code < 300
