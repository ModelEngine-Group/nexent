# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, Mock

import pytest
from pydantic import ValidationError

from contracts.agentos import (
    AgentMemoryReceipt, AgentMemoryStore, AgentMemoryStored, AgentResource, PreparedMemorySearch, ToolBinding,
)
from infrastructure.agentos_identity import ServicePrincipal
from nexent.memory.embedding_model import EmbeddingModelInfo
from runtime.agentos import memory, prepared_memory


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
    mirror = Mock(side_effect=lambda *args, **kwargs: args[-1]({"memory_id": 17}))

    async def inline(_label, fn, *args, **_options):
        return fn(*args)

    monkeypatch.setattr(memory, "run_memory_io", inline)
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
    store.write.assert_called_once_with("tenant-a", "user-a", 7, 42, "one", "remember", "mem_provider_embed_2", deadline=ANY)
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


@pytest.mark.parametrize("record", [
    None,
    {"model_type": "llm", "model_name": "wrong-kind", "max_tokens": 2},
    {"model_type": "embedding", "model_name": "", "max_tokens": 2},
    {"model_type": "embedding", "model_name": "embed"},
    {"model_type": "embedding", "model_name": "embed", "max_tokens": "unknown"},
    {"model_type": "embedding", "model_name": "embed", "max_tokens": 0},
])
def test_embedding_binding_rejects_unusable_tenant_model(mocker, record):
    mocker.patch.object(memory, "read_memory_embedding_model_id", return_value=11)
    read = mocker.patch.object(memory, "get_model_by_model_id", return_value=record)
    assert memory._load_embedding("tenant-a") is None
    read.assert_called_once_with(11, "tenant-a")


def test_embedding_binding_uses_current_model_revision_and_dimension(mocker):
    definition = {"model_type": "multi_embedding", "model_name": "embed", "max_tokens": "768",
                  "model_repo": "provider"}
    mocker.patch.object(memory, "read_memory_embedding_model_id", return_value=11)
    mocker.patch.object(memory, "get_model_by_model_id", return_value=definition)
    revision = mocker.patch.object(memory, "model_record_revision", return_value="frozen-revision")
    binding = memory._load_embedding("tenant-a")
    assert (binding.model_id, binding.revision, binding.dimension, binding.model_name) == (
        11, "frozen-revision", 768, "embed",
    )
    revision.assert_called_once_with(definition)


async def test_missing_model_fails_before_writing_memory(store, mocker):
    mocker.patch.object(memory, "_load_embedding", return_value=None)
    with pytest.raises(memory.MemoryStoreModelError, match="MEMORY_EMBEDDING_NOT_CONFIGURED"):
        await store.service.store(store.request, store.actor)
    store.model.invoke.assert_not_awaited()
    store.write.assert_not_called()
    store.mirror.assert_not_called()


@pytest.mark.parametrize("output", [[], [[0.1]], [[True, 0.2]], [[float("inf"), 0.2]]])
async def test_invalid_provider_vector_does_not_mark_memory_indexed(store, output):
    store.model.invoke.return_value = SimpleNamespace(output=output)
    receipt = await store.service.store(store.request, store.actor)
    assert (receipt.memory_id, receipt.event, receipt.indexed) == (17, "ADD", False)
    assert store.index.index_record.call_args.kwargs["embedding"] is None


@pytest.mark.parametrize("extra", [{"tenant_id": "tenant-b"}, {"user_id": "user-b"}, {"embedding": [float("inf")]}])
def test_request_rejects_unsigned_scope_and_nonfinite_vectors(extra):
    with pytest.raises(ValidationError):
        AgentMemoryStore(agent_id=7, content="remember", idempotency_key="one", **extra)


@pytest.mark.asyncio
async def test_prepared_store_ignores_identity_in_sdk_payload(monkeypatch):
    local = AsyncMock(return_value=AgentMemoryReceipt(memory_id=17, event="ADD"))
    monkeypatch.setattr(prepared_memory, "get_memory_store_service", lambda: SimpleNamespace(store=local))
    notify = AsyncMock()
    monkeypatch.setattr(prepared_memory, "notify_memory_stored", notify)
    actor = ServicePrincipal("user-a", "tenant-a")
    search = PreparedMemorySearch(query="question", result="Found 1 memory")
    resource = AgentResource(
        agent_id=8, version_no=1, name="child", description="", prompt_templates={},
        memory_search=search, tools=[ToolBinding(tool_id="store_memory", version="1")],
    )

    tools, events = prepared_memory.materialize_memory(resource, actor, 42)
    bound = tools["store_memory"]
    result = await bound.metadata["memory_service"].backend_store({
        "agent_id": "7", "conversation_id": "99", "user_id": "foreign", "tenant_id": "foreign",
        "content": "remember", "idempotency_key": "one",
    })

    assert events == search.observer_events()
    assert result["memory_id"] == 17
    assert local.await_args.args == (
        AgentMemoryStore(agent_id=8, conversation_id=42, content="remember", idempotency_key="one"), actor,
    )
    notify.assert_awaited_once_with(AgentMemoryStored(memory_id=17, agent_id=8, conversation_id=42), actor)


@pytest.mark.parametrize("conversation_id, credentials, params, error", [
    (None, None, {}, "persistent conversation"),
    (42, "not-allowed", {}, "store binding"),
    (42, None, {"agent_id": 7}, "store binding"),
])
def test_prepared_memory_rejects_ephemeral_and_tool_overrides(conversation_id, credentials, params, error):
    resource = AgentResource(
        agent_id=8, version_no=1, name="child", description="", prompt_templates={},
        tools=[ToolBinding(tool_id="store_memory", version="1", credential_ref=credentials, parameters=params)],
    )
    with pytest.raises(ValueError, match=error):
        prepared_memory.materialize_memory(resource, ServicePrincipal("user-a", "tenant-a"), conversation_id)


def test_long_term_memory_survives_presearch_failure_in_a_persistent_snapshot():
    from management.services.agent.preparation import evaluation_snapshot
    from nexent.core.agents.contracts.config import AgentConfig

    item = {"id": "tenant-memory", "type": "memory", "content": {
        "memory": "Authorized tenant context", "scope": "tenant", "memory_level": "tenant",
    }}
    config = AgentConfig(
        agent_id=8, version_no=1, name="child", description="", model_name="model",
        context_items=[item], pre_run_tool_events=[], tools=[],
    )
    resource = evaluation_snapshot._export_resource(
        config, {}, "tenant-a", "en", None, {}, allow_memory=True,
    )
    assert resource.memory_search is None
    assert resource.evaluation_options.context_items[0]["content"] == item["content"]
    actor = ServicePrincipal("user-a", "tenant-a")
    assert prepared_memory.materialize_memory(resource, actor, 42) == ({}, [])
    with pytest.raises(ValueError, match="persistent conversation"):
        prepared_memory.materialize_memory(resource, actor, None)
    with pytest.raises(ValueError, match="Unsupported evaluation context"):
        evaluation_snapshot._export_resource(config, {}, "tenant-a", "en", None, {})


def test_short_term_memory_still_requires_search_binding():
    from contracts.agentos import EvaluationAgentOptions

    resource = AgentResource(
        agent_id=8, version_no=1, name="child", description="", prompt_templates={},
        evaluation_options=EvaluationAgentOptions(context_items=[{"type": "memory"}]),
    )
    with pytest.raises(ValueError, match="requires a search binding"):
        prepared_memory.materialize_memory(resource, ServicePrincipal("user-a", "tenant-a"), 42)


@pytest.mark.asyncio
async def test_store_deadline_cancels_model_and_prevents_late_database_write(store, monkeypatch):
    import asyncio
    from time import monotonic

    async def blocked(*args):
        await asyncio.Future()

    monkeypatch.setattr(memory, "memory_write_deadline", lambda: monotonic() + 0.1)
    store.model.invoke.side_effect = blocked
    start = monotonic()
    with pytest.raises(TimeoutError):
        await store.service.store(store.request, store.actor)
    assert monotonic() - start < 0.5
    store.write.assert_not_called()
    store.mirror.assert_not_called()


@pytest.mark.parametrize("config", [
    [("MEMORY_SWITCH", "N")],
    [("MEMORY_SWITCH", "Y"), ("DISABLE_AGENT_ID", "7")],
    [("DISABLE_USERAGENT_ID", "7")],
])
def test_runtime_storage_honors_existing_personal_memory_policy(config):
    from infrastructure.rdb import memory_store

    session = Mock()
    session.execute.return_value.all.return_value = config
    with pytest.raises(memory_store.MemoryStoreScopeError):
        memory_store._require_automatic_memory(session, "user", 7)


def test_expired_storage_worker_cannot_modify_database(monkeypatch):
    from contextlib import contextmanager
    from infrastructure.rdb import memory_store

    session = Mock()

    @contextmanager
    def connection():
        yield session

    monkeypatch.setattr(memory_store, "get_db_session", connection)
    monkeypatch.setattr(memory_store, "_lock", Mock())
    monkeypatch.setattr(memory_store, "_require_scope", Mock())
    monkeypatch.setattr(memory_store, "_require_automatic_memory", Mock())
    with pytest.raises(TimeoutError):
        memory_store.write_agent_memory("t", "u", 7, 42, "one", "remember", "index", deadline=0)
    session.add.assert_not_called()
    session.flush.assert_not_called()
