"""Network-isolated unit tests for the bundled Mem0 provider."""

from __future__ import annotations

import json

import httpx
import pytest

from nexent.memory.models import (
    ExternalMemoryItem,
    MemoryIngestRequest,
    MemoryIngestUnit,
    MemoryLayer,
    MemorySearchRequest,
    MemorySearchResult,
)
from nexent.memory.providers.retry import (
    NonRetryableProviderError,
    RetryableProviderError,
)
from nexent.memory.retrieval.normalizer import Normalizer

from backend.memory_provider_plugins.mem0.provider import Mem0Provider


def _install_transport(monkeypatch, handler):
    original_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def _client(**kwargs):
        return original_async_client(transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client)


def _search_request(**overrides):
    values = {
        "query": "Jules interview",
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "top_k": 5,
    }
    values.update(overrides)
    return MemorySearchRequest(**values)


@pytest.mark.asyncio
async def test_ac_p3_24_search_success_uses_mock_http(monkeypatch):
    def handler(request):
        assert request.headers["Authorization"] == "Token test-key"
        return httpx.Response(
            200,
            json={
                "results": [
                    {"id": "m1", "memory": "Jules uses COMET-913", "score": 0.9}
                ]
            },
        )

    _install_transport(monkeypatch, handler)
    results = await Mem0Provider({"api_key": "test-key"}).search(_search_request())

    assert [item.content for item in results] == ["Jules uses COMET-913"]
    assert results[0].source == "mem0"


@pytest.mark.asyncio
async def test_ac_p3_24_search_forwards_filters_and_org_header(monkeypatch):
    def handler(request):
        payload = json.loads(request.content)
        assert payload["filters"] == {
            "AND": [{"user_id": "user-1"}, {"category": "preference"}]
        }
        assert request.headers["X-Org-Id"] == "org-1"
        return httpx.Response(200, json=[])

    _install_transport(monkeypatch, handler)
    results = await Mem0Provider({"api_key": "test-key", "org_id": "org-1"}).search(
        _search_request(), filters={"category": "preference"}
    )

    assert results == []


@pytest.mark.asyncio
async def test_ac_p3_24_search_falls_back_to_user_scope(monkeypatch):
    payloads = []

    def handler(request):
        payloads.append(json.loads(request.content))
        if len(payloads) == 1:
            return httpx.Response(200, json={"results": []})
        return httpx.Response(
            200,
            json={
                "results": [
                    {"id": "m2", "memory": "COMET-913 belongs to Jules", "score": 0.8}
                ]
            },
        )

    _install_transport(monkeypatch, handler)
    results = await Mem0Provider({"api_key": "test-key"}).search(
        _search_request(agent_id="agent-5")
    )

    assert payloads[0]["filters"] == {
        "AND": [{"user_id": "user-1"}, {"agent_id": "agent-5"}]
    }
    assert payloads[1]["filters"] == {"user_id": "user-1"}
    assert results[0].external_id == "m2"


@pytest.mark.asyncio
async def test_ac_p3_24_ingest_success_uses_mock_http(monkeypatch):
    payloads = []

    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"results": [{"id": "m3", "event": "ADD"}]})

    _install_transport(monkeypatch, handler)
    result = await Mem0Provider({"api_key": "test-key"}).ingest(
        MemoryIngestRequest(
            tenant_id="tenant-1",
            user_id="user-1",
            agent_id="agent-5",
            units=[
                MemoryIngestUnit(
                    event_id="event-1",
                    event_type="conversation",
                    unit_type="user_message",
                    unit_content="Remember COMET-913",
                )
            ],
            idempotency_key="test:event-1",
        )
    )

    assert result.status == "ok"
    assert result.accepted_count == 1
    assert payloads[0]["user_id"] == "user-1"
    assert payloads[0]["agent_id"] == "agent-5"


@pytest.mark.asyncio
async def test_custom_base_url_uses_latest_ingest_and_search_api(monkeypatch):
    stored = []

    def handler(request):
        assert request.url.host == "partner-mem0.example"
        payload = json.loads(request.content) if request.content else {}
        if request.url.path == "/v3/memories/add/":
            assert payload["infer"] is False
            stored.append(payload["messages"][0]["content"])
            return httpx.Response(200, json={"status": "PENDING", "event_id": "evt-1"})
        if request.url.path == "/v1/event/evt-1/":
            return httpx.Response(200, json={"status": "SUCCEEDED"})
        if request.url.path == "/v3/memories/search/":
            assert payload["filters"] == {
                "AND": [{"user_id": "user-1"}, {"agent_id": "agent-5"}]
            }
            assert payload["top_k"] == 5
            return httpx.Response(
                200,
                json={"results": [{"id": "m-v3", "memory": stored[0], "score": 0.95}]},
            )
        return httpx.Response(404)

    _install_transport(monkeypatch, handler)
    provider = Mem0Provider(
        {"api_key": "test-key", "base_url": "https://partner-mem0.example"}
    )
    content = "The user prefers concise summaries."
    ingest_result = await provider.ingest(
        MemoryIngestRequest(
            tenant_id="tenant-1",
            user_id="user-1",
            agent_id="agent-5",
            units=[
                MemoryIngestUnit(
                    event_id="event-v3",
                    event_type="memory_stored",
                    unit_type="agent",
                    unit_content=content,
                )
            ],
            idempotency_key="test:v3",
        )
    )
    results = await provider.search(_search_request(agent_id="agent-5"))

    assert ingest_result.accepted_count == 1
    assert [item.content for item in results] == [content]


@pytest.mark.asyncio
async def test_ac_p3_37_38_mem0_dual_write_search_and_cross_source_dedup(monkeypatch):
    """Exercise the real Mem0 plugin HTTP contract and retrieval normalizer."""
    stored_memories = []

    def handler(request):
        payload = json.loads(request.content)
        if request.url.path == "/v3/memories/add/":
            stored_memories.append(payload["messages"][0]["content"])
            return httpx.Response(
                200, json={"results": [{"id": "mem0-1", "event": "ADD"}]}
            )
        if request.url.path == "/v3/memories/search/":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"id": "mem0-1", "memory": content, "score": 0.88}
                        for content in stored_memories
                    ]
                },
            )
        return httpx.Response(404)

    _install_transport(monkeypatch, handler)
    provider = Mem0Provider({"api_key": "test-key"})
    content = "The user prefers concise weekly status summaries."

    internal_result = MemorySearchResult(
        memory_id=101,
        content=content,
        score=0.93,
        layer=MemoryLayer.AGENT,
        source="internal",
        metadata={"memory_type": "short_term"},
    )
    ingest_result = await provider.ingest(
        MemoryIngestRequest(
            tenant_id="tenant-1",
            user_id="user-1",
            agent_id="agent-5",
            conversation_id="conversation-1",
            units=[
                MemoryIngestUnit(
                    event_id="memory-101",
                    event_type="memory_stored",
                    unit_type="agent",
                    unit_content=content,
                )
            ],
            idempotency_key="nexent:tenant-1:agent-5:user-1:conversation-1:memory_stored:101",
        )
    )
    external_results = await provider.search(
        _search_request(query="weekly status summaries", agent_id="agent-5")
    )

    assert ingest_result.status == "ok"
    assert stored_memories == [content]
    assert [result.content for result in external_results] == [content]

    normalized = Normalizer().normalize(
        [internal_result],
        external_results=[
            ExternalMemoryItem(
                id=result.external_id or "",
                content=result.content,
                score=result.score,
                provider=result.source,
                metadata=result.metadata,
            )
            for result in external_results
        ],
    )
    assert len(normalized) == 1
    assert normalized[0].content == content
    assert normalized[0].is_external is False


@pytest.mark.asyncio
async def test_ac_p3_24_ingest_reports_partial_acceptance(monkeypatch):
    call_count = 0

    def handler(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json={})
        return httpx.Response(403, text="forbidden")

    _install_transport(monkeypatch, handler)
    units = [
        MemoryIngestUnit(
            event_id=f"event-{index}",
            event_type="conversation",
            unit_type="user_message",
            unit_content=f"memory {index}",
        )
        for index in (1, 2)
    ]
    result = await Mem0Provider({"api_key": "test-key"}).ingest(
        MemoryIngestRequest(
            tenant_id="tenant-1",
            user_id="user-1",
            conversation_id="conversation-1",
            units=units,
            idempotency_key="test:partial",
        )
    )

    assert result.status == "partial"
    assert result.accepted_count == 1
    assert result.rejected_count == 1


@pytest.mark.asyncio
async def test_ac_p3_24_unauthorized_is_non_retryable(monkeypatch):
    _install_transport(
        monkeypatch, lambda request: httpx.Response(401, text="invalid token")
    )

    with pytest.raises(NonRetryableProviderError) as exc_info:
        await Mem0Provider({"api_key": "bad-key"}).search(_search_request())

    assert exc_info.value.error.code.value == "unauthorized"


@pytest.mark.asyncio
async def test_ac_p3_24_timeout_is_retryable(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("simulated timeout", request=request)

    _install_transport(monkeypatch, handler)

    with pytest.raises(RetryableProviderError) as exc_info:
        await Mem0Provider({"api_key": "test-key"}).search(_search_request())

    assert exc_info.value.error.code.value == "timeout"


@pytest.mark.asyncio
async def test_ac_p3_24_transport_error_is_retryable(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("simulated connection failure", request=request)

    _install_transport(monkeypatch, handler)

    with pytest.raises(RetryableProviderError) as exc_info:
        await Mem0Provider({"api_key": "test-key"}).search(_search_request())

    assert exc_info.value.error.code.value == "provider_error"


@pytest.mark.parametrize(
    ("status_code", "headers", "body", "exception_type", "error_code"),
    [
        (403, {}, "forbidden", NonRetryableProviderError, "forbidden"),
        (429, {"Retry-After": "7"}, "limited", RetryableProviderError, "rate_limited"),
        (503, {}, "unavailable", RetryableProviderError, "provider_error"),
        (418, {}, '{"detail":"teapot"}', NonRetryableProviderError, "unknown"),
        (400, {}, "not-json", NonRetryableProviderError, "unknown"),
    ],
)
def test_ac_p3_24_response_error_matrix(
    status_code, headers, body, exception_type, error_code
):
    provider = Mem0Provider({"api_key": "test-key"})
    response = httpx.Response(status_code, headers=headers, content=body)

    with pytest.raises(exception_type) as exc_info:
        provider._check_response(response)

    assert exc_info.value.error.code.value == error_code
