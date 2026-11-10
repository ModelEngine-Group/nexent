# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from contracts.agentos import AgentMemoryStore
from infrastructure.agentos_identity import ServicePrincipal
from nexent.memory.embedding_model import EmbeddingModelInfo
from runtime.agentos import memory


@pytest.fixture
def store(monkeypatch):
    model = EmbeddingModelInfo(
        model_name="embed", model_repo="provider", dimension=2, base_url="", api_key="",
        model_id=11, revision="r1",
    )
    runtime_model = AsyncMock()
    runtime_model.invoke.return_value = SimpleNamespace(output=[[0.1, 0.2]])
    index = Mock()
    index.index_record.return_value = True
    lookup = Mock(return_value=None)
    write = Mock(return_value=(17, "ADD"))
    mirror = Mock(side_effect=lambda *args: args[-1]({"memory_id": 17}))

    async def inline(_label, fn, *args, **_options):
        return fn(*args)

    monkeypatch.setattr(memory, "_control", inline)
    monkeypatch.setattr(memory, "run_blocking", inline)
    monkeypatch.setattr(memory, "_load_embedding", Mock(return_value=model))
    monkeypatch.setattr(memory, "find_existing_memory", lookup)
    monkeypatch.setattr(memory, "write_agent_memory", write)
    monkeypatch.setattr(memory, "mirror_current_memory", mirror)
    return SimpleNamespace(
        service=memory.AgentMemoryStoreService(runtime_model, index), model=runtime_model, index=index,
        lookup=lookup, write=write, mirror=mirror,
        actor=ServicePrincipal("user-a", "tenant-a"),
        request=AgentMemoryStore(agent_id=7, conversation_id=42, content="remember", idempotency_key="one"),
    )


@pytest.mark.asyncio
async def test_signed_scope_selects_model_and_persists_index(store):
    result = await store.service.store(store.request, store.actor)

    assert (result.memory_id, result.event, result.indexed) == (17, "ADD", True)
    store.lookup.assert_called_once_with("tenant-a", "user-a", 7, 42, "one", "remember")
    invocation, actor = store.model.invoke.await_args.args
    assert (invocation.model_id, invocation.expected_revision, invocation.input) == (11, "r1", ["remember"])
    assert actor == store.actor
    store.write.assert_called_once_with("tenant-a", "user-a", 7, 42, "one", "remember", "mem_provider_embed_2")
    assert store.index.index_record.call_args.kwargs["embedding"] == [0.1, 0.2]


@pytest.mark.asyncio
async def test_replay_and_scope_collision_do_not_invoke_or_write(store):
    store.lookup.return_value = 17
    replay = await store.service.store(store.request, store.actor)
    assert (replay.memory_id, replay.event) == (17, "UNCHANGED")
    store.lookup.side_effect = memory.MemoryStoreConflictError
    with pytest.raises(memory.MemoryStoreConflictError):
        await store.service.store(store.request, store.actor)
    store.model.invoke.assert_not_awaited()
    store.write.assert_not_called()
    store.mirror.assert_not_called()


@pytest.mark.asyncio
async def test_precomputed_embedding_requires_exact_dimension(store):
    values = store.request.model_dump()
    with pytest.raises(memory.MemoryStoreModelError, match="MEMORY_EMBEDDING_DIMENSION_MISMATCH"):
        await store.service.store(AgentMemoryStore(**{**values, "embedding": [1.0]}), store.actor)
    store.write.assert_not_called()

    valid = AgentMemoryStore(**{**values, "embedding": [1.0, 2.0]})
    assert (await store.service.store(valid, store.actor)).indexed
    store.model.invoke.assert_not_awaited()
    assert store.index.index_record.call_args.kwargs["embedding"] == [1.0, 2.0]


@pytest.mark.asyncio
async def test_embedding_and_index_errors_preserve_database_receipt(store):
    store.model.invoke.side_effect = RuntimeError
    store.mirror.side_effect = RuntimeError

    result = await store.service.store(store.request, store.actor)

    assert (result.memory_id, result.event, result.indexed) == (17, "ADD", False)
    store.write.assert_called_once()
    assert store.mirror.call_args.args[-1].keywords["embedding"] is None


@pytest.mark.parametrize("extra", [{"tenant_id": "tenant-b"}, {"user_id": "user-b"}, {"embedding": [float("inf")]}])
def test_request_rejects_unsigned_scope_and_nonfinite_vectors(extra):
    with pytest.raises(ValidationError):
        AgentMemoryStore(agent_id=7, content="remember", idempotency_key="one", **extra)
