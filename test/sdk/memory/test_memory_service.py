"""Unit tests for ``sdk.nexent.memory.service`` (MemoryService facade).

These tests focus on memory_service.store_memory / search_memory and the
helper classmethods. They run without any database or network access; the
embedding model and backend hooks are replaced with lightweight fakes so we
can exercise the policy-enforcement branches and payload translation paths.
"""

import hashlib

import pytest

from nexent.memory.embedding_model import EmbeddingModelInfo
from nexent.memory.models import (
    MemoryLayer,
    MemorySearchRequest,
    MemorySearchResult,
    MemoryType,
)
from nexent.memory.service import (
    MemoryService,
    get_memory_service,
    reset_memory_service,
)


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


class _FakeEmbedding:
    """Minimal fake of OpenAICompatibleEmbedding used by MemoryService."""

    def __init__(self, vector=None, error=None):
        self._vector = vector if vector is not None else [0.1, 0.2, 0.3]
        self._error = error
        self.calls = []

    def get_embeddings(self, text):
        self.calls.append(text)
        if self._error is not None:
            raise self._error
        return [self._vector]


def _embedding_model_info(name="text-embedding-3-small", dim=3, repo="openai"):
    return EmbeddingModelInfo(
        model_name=name,
        dimension=dim,
        base_url="http://example.com",
        api_key="x",
        model_repo=repo,
    )


# ---------------------------------------------------------------------------
# store_memory: policy / permission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_memory_rejects_disallowed_layer():
    """Policy forbids agents from writing to user/tenant layers."""
    service = MemoryService()

    with pytest.raises(PermissionError):
        await service.store_memory(
            content="x",
            tenant_id="t",
            user_id="u",
            agent_id="a",
            layer=MemoryLayer.USER,
            memory_type=MemoryType.LONG_TERM,
        )


@pytest.mark.asyncio
async def test_store_memory_rejects_long_term_for_agent():
    """Even at the agent layer, long-term writes are forbidden for agents."""
    service = MemoryService()

    with pytest.raises(PermissionError):
        await service.store_memory(
            content="x",
            tenant_id="t",
            user_id="u",
            agent_id="a",
            layer=MemoryLayer.AGENT,
            memory_type=MemoryType.LONG_TERM,
        )


# ---------------------------------------------------------------------------
# store_memory: default behavior (no embedding model, no backend hook)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_memory_uses_generated_uuid_without_backend():
    """Without a backend hook, the SDK still produces a stable result."""
    service = MemoryService()

    result = await service.store_memory(
        content="hello",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        layer=MemoryLayer.AGENT,
        memory_type=MemoryType.SHORT_TERM,
    )

    assert result.event == "ADD"
    assert result.content == "hello"
    assert result.layer == MemoryLayer.AGENT
    assert result.memory_type == MemoryType.SHORT_TERM
    # memory_id is uuid-generated when no backend overrides it
    assert result.memory_id


@pytest.mark.asyncio
async def test_store_memory_uses_caller_provided_idempotency_key():
    captured = {}

    async def backend_store(payload):
        captured.update(payload)
        return {}

    service = MemoryService(backend_store=backend_store)
    await service.store_memory(
        content="hi",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        layer=MemoryLayer.AGENT,
        memory_type=MemoryType.SHORT_TERM,
        idempotency_key="custom-key",
    )

    assert captured["idempotency_key"] == "custom-key"


@pytest.mark.asyncio
async def test_store_memory_generates_default_idempotency_key():
    """When no key is provided, hash(tenant:user:agent:content) is used."""
    captured = {}

    async def backend_store(payload):
        captured.update(payload)
        return {}

    service = MemoryService(backend_store=backend_store)
    await service.store_memory(
        content="unique-content",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        layer=MemoryLayer.AGENT,
        memory_type=MemoryType.SHORT_TERM,
    )

    expected = hashlib.sha256(b"t:u:a:unique-content").hexdigest()
    assert captured["idempotency_key"] == expected


@pytest.mark.asyncio
async def test_store_memory_uses_provided_embedding_without_calling_model():
    captured = {}

    async def backend_store(payload):
        captured.update(payload)
        return {}

    fake_emb = _FakeEmbedding(vector=[9.0, 8.0])

    service = MemoryService(
        embedding_model=fake_emb, backend_store=backend_store,
    )
    await service.store_memory(
        content="hi",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        layer=MemoryLayer.AGENT,
        memory_type=MemoryType.SHORT_TERM,
        embedding=[1.0, 2.0],
    )

    # Provided embedding should win; the fake should never have been called.
    assert captured["embedding"] == [1.0, 2.0]
    assert fake_emb.calls == []


@pytest.mark.asyncio
async def test_store_memory_invokes_embedding_model_when_missing(caplog):
    captured = {}

    async def backend_store(payload):
        captured.update(payload)
        return {}

    fake_emb = _FakeEmbedding(vector=[0.5, 0.6, 0.7])
    service = MemoryService(
        embedding_model=fake_emb, backend_store=backend_store,
    )

    await service.store_memory(
        content="hello world",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        layer=MemoryLayer.AGENT,
        memory_type=MemoryType.SHORT_TERM,
    )

    assert captured["embedding"] == [0.5, 0.6, 0.7]
    assert fake_emb.calls == ["hello world"]


@pytest.mark.asyncio
async def test_store_memory_tolerates_embedding_failure(caplog):
    """If embedding generation fails, store_memory proceeds without it."""
    captured = {}

    async def backend_store(payload):
        captured.update(payload)
        return {}

    fake_emb = _FakeEmbedding(error=RuntimeError("down"))
    service = MemoryService(
        embedding_model=fake_emb, backend_store=backend_store,
    )

    result = await service.store_memory(
        content="hello",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        layer=MemoryLayer.AGENT,
        memory_type=MemoryType.SHORT_TERM,
    )

    assert result.event == "ADD"
    assert captured["embedding"] is None


@pytest.mark.asyncio
async def test_store_memory_propagates_backend_hook_exception():
    """backend_store errors should bubble up after being logged."""

    async def backend_store(payload):
        raise RuntimeError("boom")

    service = MemoryService(backend_store=backend_store)
    with pytest.raises(RuntimeError, match="boom"):
        await service.store_memory(
            content="x",
            tenant_id="t",
            user_id="u",
            agent_id="a",
            layer=MemoryLayer.AGENT,
            memory_type=MemoryType.SHORT_TERM,
        )


@pytest.mark.asyncio
async def test_store_memory_normalizes_backend_result_with_defaults():
    """When the backend returns only memory_id, other fields come from inputs."""

    async def backend_store(_payload):
        return {"memory_id": 99}

    service = MemoryService(backend_store=backend_store)
    result = await service.store_memory(
        content="hello",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        layer=MemoryLayer.AGENT,
        memory_type=MemoryType.SHORT_TERM,
    )

    assert result.memory_id == "99"
    assert result.event == "ADD"
    assert result.content == "hello"
    assert result.layer == MemoryLayer.AGENT
    assert result.memory_type == MemoryType.SHORT_TERM


@pytest.mark.asyncio
async def test_store_memory_uses_backend_returned_event_and_content():
    """Backend may override event and content."""

    async def backend_store(_payload):
        return {
            "memory_id": 5,
            "event": "UNCHANGED",
            "content": "backend-overridden",
        }

    service = MemoryService(backend_store=backend_store)
    result = await service.store_memory(
        content="input content",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        layer=MemoryLayer.AGENT,
        memory_type=MemoryType.SHORT_TERM,
    )

    assert result.event == "UNCHANGED"
    assert result.content == "backend-overridden"


@pytest.mark.asyncio
async def test_store_memory_handles_none_backend_result():
    """If backend returns None, defaults are used."""

    async def backend_store(_payload):
        return None

    service = MemoryService(backend_store=backend_store)
    result = await service.store_memory(
        content="hi",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        layer=MemoryLayer.AGENT,
        memory_type=MemoryType.SHORT_TERM,
    )
    assert result.event == "ADD"


# ---------------------------------------------------------------------------
# search_memory: layer handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_memory_returns_empty_when_agent_layer_not_requested():
    """Only the agent layer uses vector retrieval; full-context layers return []."""
    service = MemoryService()
    results = await service.search_memory(
        query="anything",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        layers=[MemoryLayer.USER, MemoryLayer.TENANT],
    )
    assert results == []


@pytest.mark.asyncio
async def test_search_memory_returns_empty_when_no_embedding_model():
    """Without an embedding model and no provided embedding, no search runs."""

    async def backend_search(_payload):
        raise AssertionError("backend_search should not be called")

    service = MemoryService(backend_search=backend_search)
    results = await service.search_memory(
        query="hi",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        layers=[MemoryLayer.AGENT],
    )
    assert results == []


@pytest.mark.asyncio
async def test_search_memory_uses_provided_embedding_without_calling_model():
    captured = {}

    async def backend_search(payload):
        captured.update(payload)
        return [
            {"memory_id": "1", "content": "c", "score": 0.5, "layer": "agent"},
        ]

    fake_emb = _FakeEmbedding()
    service = MemoryService(
        embedding_model=fake_emb,
        backend_search=backend_search,
        embedding_model_info=_embedding_model_info(),
    )

    results = await service.search_memory(
        query="what?",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        layers=[MemoryLayer.AGENT],
        embedding=[0.1, 0.2, 0.3],
    )

    assert fake_emb.calls == []
    assert captured["embedding"] == [0.1, 0.2, 0.3]
    assert isinstance(results[0], MemorySearchResult)


@pytest.mark.asyncio
async def test_search_memory_invokes_embedding_model_for_query(caplog):
    captured = {}

    async def backend_search(payload):
        captured.update(payload)
        return [
            {"memory_id": "1", "content": "c1", "score": 0.8, "layer": "agent"},
            {"memory_id": "2", "content": "c2", "score": 0.7, "layer": "agent"},
        ]

    fake_emb = _FakeEmbedding(vector=[0.5, 0.5, 0.5])
    service = MemoryService(
        embedding_model=fake_emb,
        backend_search=backend_search,
        embedding_model_info=_embedding_model_info(),
    )

    results = await service.search_memory(
        query="what time is it?",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        layers=[MemoryLayer.AGENT],
        top_k=10,
        threshold=0.3,
    )

    assert fake_emb.calls == ["what time is it?"]
    assert captured["query"] == "what time is it?"
    assert captured["top_k"] == 10
    assert captured["threshold"] == 0.3
    assert captured["embedding"] == [0.5, 0.5, 0.5]
    assert captured["layers"] == [MemoryLayer.AGENT]
    assert len(results) == 2


@pytest.mark.asyncio
async def test_search_memory_returns_empty_when_embedding_generation_fails(caplog):
    """Embedding failures are tolerated by returning an empty list."""

    async def backend_search(_payload):
        raise AssertionError("backend_search should not be called")

    fake_emb = _FakeEmbedding(error=RuntimeError("down"))
    service = MemoryService(
        embedding_model=fake_emb, backend_search=backend_search,
    )

    results = await service.search_memory(
        query="hi",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        layers=[MemoryLayer.AGENT],
    )
    assert results == []


@pytest.mark.asyncio
async def test_search_memory_no_backend_search_returns_empty():
    """Without backend_search hook, results are [] even with embedding."""
    service = MemoryService(
        embedding_model=_FakeEmbedding(),
        embedding_model_info=_embedding_model_info(),
    )
    results = await service.search_memory(
        query="hi",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        layers=[MemoryLayer.AGENT],
    )
    assert results == []


@pytest.mark.asyncio
async def test_search_memory_backend_exception_returns_empty(caplog):
    """A backend_search exception is logged and turned into an empty list."""

    async def backend_search(_payload):
        raise RuntimeError("backend down")

    service = MemoryService(
        embedding_model=_FakeEmbedding(),
        backend_search=backend_search,
        embedding_model_info=_embedding_model_info(),
    )
    results = await service.search_memory(
        query="hi",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        layers=[MemoryLayer.AGENT],
    )
    assert results == []


@pytest.mark.asyncio
async def test_search_memory_clamps_top_k_to_max():
    """top_k is validated against MemoryRetrievalPolicy rules."""
    captured = {}

    async def backend_search(payload):
        captured.update(payload)
        return []

    service = MemoryService(
        embedding_model=_FakeEmbedding(),
        backend_search=backend_search,
        embedding_model_info=_embedding_model_info(),
    )
    await service.search_memory(
        query="x",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        layers=[MemoryLayer.AGENT],
        top_k=1000,  # Should be clamped to MAX_TOP_K == 100
    )
    assert captured["top_k"] == 100


@pytest.mark.asyncio
async def test_search_memory_normalizes_hits():
    """Result normalization handles missing fields and an invalid layer value."""

    async def backend_search(_payload):
        return [
            # missing layer → falls back to AGENT; id field used as memory_id
            {"id": 11, "content": "c1", "score": 0.9},
            # invalid layer → falls back to AGENT
            {"memory_id": 22, "content": "c2", "score": 0.7, "layer": "bogus"},
            # external flag preserved
            {
                "memory_id": 33,
                "content": "c3",
                "score": 0.5,
                "layer": "agent",
                "is_external": True,
                "source": "mem0",
            },
            # missing score defaults to 0.0
            {"memory_id": 44, "content": "c4", "layer": "agent"},
        ]

    service = MemoryService(
        embedding_model=_FakeEmbedding(),
        backend_search=backend_search,
        embedding_model_info=_embedding_model_info(),
    )

    results = await service.search_memory(
        query="x",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        layers=[MemoryLayer.AGENT],
    )

    assert len(results) == 4
    assert results[0].memory_id == 11
    assert results[0].layer == MemoryLayer.AGENT  # defaulted
    assert results[1].memory_id == 22
    assert results[1].layer == MemoryLayer.AGENT  # invalid layer fell back to AGENT
    assert results[2].is_external is True
    assert results[2].source == "mem0"
    assert results[2].metadata.get("tenant_id") == "t"
    assert results[3].score == 0.0


@pytest.mark.asyncio
async def test_search_memory_includes_index_name_when_info_present():
    captured = {}

    async def backend_search(payload):
        captured.update(payload)
        return []

    service = MemoryService(
        embedding_model=_FakeEmbedding(),
        backend_search=backend_search,
        embedding_model_info=_embedding_model_info(name="text-emb", repo="vendor"),
    )
    await service.search_memory(
        query="x",
        tenant_id="t",
        user_id="u",
        agent_id="a",
        layers=[MemoryLayer.AGENT],
    )

    assert captured["index_name"].startswith("mem_vendor_text-emb_")


@pytest.mark.asyncio
async def test_search_memory_default_layers_when_none_provided():
    """If layers is None, the policy default is used."""
    captured = {}

    async def backend_search(payload):
        captured.update(payload)
        return []

    service = MemoryService(
        embedding_model=_FakeEmbedding(),
        backend_search=backend_search,
        embedding_model_info=_embedding_model_info(),
    )
    await service.search_memory(
        query="x",
        tenant_id="t",
        user_id="u",
        agent_id="a",
    )

    assert MemoryLayer.AGENT in captured["layers"]


# ---------------------------------------------------------------------------
# Helpers / static helpers
# ---------------------------------------------------------------------------


def test_get_index_name_returns_none_without_info():
    service = MemoryService()
    assert service._get_index_name() is None


def test_get_index_name_delegates_to_embedding_model_info():
    info = _embedding_model_info(name="text-emb", repo="vendor")
    service = MemoryService(embedding_model_info=info)
    assert service._get_index_name() == "mem_vendor_text-emb_3"


def test_build_backend_store_payload_translates_enums_to_values():
    """The static helper should serialize layer/memory_type enums."""
    from nexent.memory.models import MemoryRecord

    record_obj = MemoryRecord(
        tenant_id="t",
        user_id="u",
        agent_id="a",
        conversation_id="c",
        layer=MemoryLayer.AGENT,
        memory_type=MemoryType.SHORT_TERM,
        content="hi",
        idempotency_key="k",
    )

    payload = MemoryService._build_backend_store_payload(
        memory_record=record_obj,
        content="hi",
        embedding=[0.1, 0.2],
    )

    assert payload["layer"] == "agent"
    assert payload["memory_type"] == "short_term"
    assert payload["memory_id"] == record_obj.memory_id
    assert payload["embedding"] == [0.1, 0.2]
    assert payload["idempotency_key"] == "k"
    assert payload["conversation_id"] == "c"
    assert payload["user_id"] == "u"
    assert payload["tenant_id"] == "t"
    assert payload["agent_id"] == "a"
    assert payload["content"] == "hi"


def test_build_backend_store_payload_with_none_embedding():
    """The embedding slot is forwarded as None when omitted."""
    from nexent.memory.models import MemoryRecord

    record_obj = MemoryRecord(
        tenant_id="t",
        user_id="u",
        agent_id="a",
        layer=MemoryLayer.AGENT,
        memory_type=MemoryType.SHORT_TERM,
        content="hi",
        idempotency_key="k",
    )

    payload = MemoryService._build_backend_store_payload(
        memory_record=record_obj,
        content="hi",
        embedding=None,
    )
    assert payload["embedding"] is None


def test_build_backend_search_payload_attaches_index_name():
    request = MemorySearchRequest(
        query="q",
        tenant_id="t",
        user_id="u",
        layers=[MemoryLayer.AGENT],
    )
    payload = MemoryService._build_backend_search_payload(
        request=request,
        index_name="mem_openai_text-emb_3",
    )

    assert payload["index_name"] == "mem_openai_text-emb_3"
    assert payload["query"] == "q"
    assert payload["tenant_id"] == "t"


def test_to_search_result_with_minimal_fields_uses_defaults():
    result = MemoryService._to_search_result(
        item={"memory_id": 1, "content": "c", "score": 0.1},
        tenant_id="t",
    )
    assert result.layer == MemoryLayer.AGENT
    assert result.source == "internal"
    assert result.is_external is False
    assert result.metadata.get("tenant_id") == "t"


def test_to_search_result_uses_id_field_when_memory_id_missing():
    result = MemoryService._to_search_result(
        item={"id": 7, "content": "c", "score": 0.1},
        tenant_id="t",
    )
    assert result.memory_id == 7


def test_to_search_result_invalid_layer_falls_back_to_agent():
    result = MemoryService._to_search_result(
        item={
            "memory_id": "1",
            "content": "c",
            "score": 0.1,
            "layer": "not-a-layer",
        },
        tenant_id="t",
    )
    assert result.layer == MemoryLayer.AGENT


def test_to_search_result_preserves_metadata_when_provided():
    result = MemoryService._to_search_result(
        item={
            "memory_id": "1",
            "content": "c",
            "score": 0.1,
            "metadata": {"external": True},
        },
        tenant_id="t",
    )
    assert result.metadata == {"external": True}


# ---------------------------------------------------------------------------
# Module-level service accessors
# ---------------------------------------------------------------------------


def test_get_memory_service_returns_singleton_instance():
    reset_memory_service()
    a = get_memory_service()
    b = get_memory_service()
    assert isinstance(a, MemoryService)
    assert a is b


def test_reset_memory_service_clears_singleton(monkeypatch):
    reset_memory_service()
    first = get_memory_service()
    # Patch the singleton so we can detect re-creation.
    monkeypatch.setattr(first, "embedding_model", object())
    reset_memory_service()
    second = get_memory_service()
    assert isinstance(second, MemoryService)
    assert second is not first


def test_reset_memory_service_is_idempotent():
    reset_memory_service()
    reset_memory_service()
    assert get_memory_service() is not None


# ---------------------------------------------------------------------------
# EmbeddingModelInfo passed into _get_index_name
# ---------------------------------------------------------------------------


def test_get_index_name_handles_missing_model_repo():
    info = EmbeddingModelInfo(
        model_name="text-emb",
        dimension=64,
        base_url="http://x",
        api_key="k",
    )
    service = MemoryService(embedding_model_info=info)
    assert service._get_index_name() == "mem_text-emb_64"
