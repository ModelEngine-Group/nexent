# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Stream only authorized prepared Memory events and persist their tool metadata."""

import asyncio
import json
from threading import Event
from time import monotonic
from unittest.mock import AsyncMock, Mock

import httpx
import pytest_asyncio
import redis
from types import SimpleNamespace

import pytest

from management.services.agent.preparation import compiler
from management.services.memory import context, records
from runtime.model import memory_embedding as runtime_embedding
from infrastructure import memory_embedding_health as embedding_health, memory_io as runtime_io
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.memory.embedding_model import EmbeddingModelInfo
from nexent.memory.models import MemoryLayer, MemorySearchContext, MemorySearchResult
from contracts.agentos import AgentResource, PreparedMemorySearch, ToolBinding
from infrastructure.agentos_identity import ServicePrincipal
from runtime.agentos import prepared_memory, prepared_run
from .test_agent_run_final_answers import stream_capture


@pytest.fixture
def run_events(mocker):
    async def model(_info, **_kwargs):
        yield '{"type":"final_answer","content":"Done"}'

    mocker.patch.object(prepared_run, "agent_run", side_effect=model)

    async def collect(search=None):
        resource = AgentResource(
            agent_id=7, version_no=1, name="memory", description="", prompt_templates={},
            memory_search=search, tools=[ToolBinding(tool_id="store_memory", version="1")],
        )
        tools, events = prepared_memory.materialize_memory(resource, ServicePrincipal("user", "tenant"), 42)
        assert set(tools) == {"store_memory"}
        info = SimpleNamespace(agent_config=SimpleNamespace(pre_run_tool_events=events))
        return [json.loads(chunk) async for chunk in prepared_run._snapshot_chunks(info)]

    return collect


@pytest.mark.asyncio
async def test_enabled_memory_without_a_search_binding_emits_no_presearch_events(run_events, stream_capture):
    source = await run_events()

    published, batch = await stream_capture(source)

    assert published == [{"type": "final_answer", "content": "Done"}]
    assert [unit["type"] for unit in batch["message_units"]] == ["final_answer"]


@pytest.mark.asyncio
async def test_fixed_search_is_streamed_and_saved_as_a_structured_tool(run_events, stream_capture):
    search = PreparedMemorySearch(query="question", result="No relevant memories found.")
    source = await run_events(search)

    published, batch = await stream_capture(source)

    assert published[:-1] == search.observer_events()
    assert [unit["type"] for unit in batch["message_units"]] == ["tool", "execution_logs", "final_answer"]
    tool, logs, _ = batch["message_units"]
    assert tool["unit_index"] == 0
    assert json.loads(tool["unit_content"]) == {
        "content": "", "tool_name": "search_memory",
        "tool_arguments": {"query": "question", "top_k": 5},
    }
    assert logs["unit_content"] == "No relevant memories found."


@pytest.fixture
def cache(monkeypatch):
    data = {}
    client = Mock()

    def set_value(key, value, *, ex, nx=False):
        if nx and key in data:
            return False
        data[key] = value
        return True

    def finish_probe(_, numkeys, key, probe_key, token):
        if data.get(probe_key) == token:
            data.pop(key, None)
            data.pop(probe_key, None)

    client.get.side_effect = data.get
    client.set.side_effect = set_value
    client.eval.side_effect = finish_probe
    monkeypatch.setattr(embedding_health, "_client", lambda: client)
    monkeypatch.setattr(embedding_health, "MEMORY_EMBEDDING_COOLDOWN_SECONDS", 300)
    embedding_health._local.clear()
    yield client, data
    embedding_health._local.clear()

@pytest.mark.parametrize("invalid", [None, [], [[0.5]], [[0.5, float("nan")]]])
@pytest.mark.asyncio
async def test_invalid_embedding_opens_shared_circuit_and_recovery_is_probed(cache, monkeypatch, invalid):
    redis_client, data = cache
    model = EmbeddingModelInfo("test", 2, "http://localhost", "test")
    client = Mock(get_embeddings_with_deadline=AsyncMock(return_value=invalid))

    assert await runtime_embedding.compute_runtime_embedding("first", model, tenant_id="t", client=client, deadline=monotonic() + 2) is None
    key = embedding_health.embedding_circuit_key("t", model)
    assert redis_client.set.call_args.kwargs["ex"] >= 300

    # Simulate a separate worker with a cold local cache.
    embedding_health._local.clear()
    assert await runtime_embedding.compute_runtime_embedding("second", model, tenant_id="t", client=client, deadline=monotonic() + 2) is None
    client.get_embeddings_with_deadline.assert_awaited_once()
    assert embedding_health.admit_embedding(embedding_health.embedding_circuit_key("other", model)) == ""

    data[key] = "0"
    token = embedding_health.admit_embedding(key)
    assert token
    assert embedding_health.admit_embedding(key) is None
    embedding_health.record_embedding_success(key, token)
    assert embedding_health.admit_embedding(key) == ""

@pytest_asyncio.fixture
async def memory_thread_manager(monkeypatch):
    manager = ThreadManager(
        "test-memory",
        {"memory-read": LanePolicy(
            name="memory-read", max_workers=4, max_queue_size=0, queue_timeout_seconds=0,
            cancel_grace_seconds=0, shutdown_grace_seconds=1,
        )},
    )
    manager.start()
    monkeypatch.setattr(runtime_io, "get_default_thread_manager", lambda: manager)
    try:
        yield manager
    finally:
        await manager.shutdown(timeout=1)

@pytest.mark.asyncio
async def test_presearch_returns_long_term_without_waiting_for_slow_vector(monkeypatch, memory_thread_manager):
    entered = Event()
    release = Event()
    exited = Event()

    async def block_embedding(*args, **kwargs):
        entered.set()
        try:
            release.wait(3)
            return [0.5, 0.5]
        finally:
            exited.set()

    long_term = MemorySearchContext(
        user_long_term=[MemorySearchResult(layer=MemoryLayer.USER, content="retained", score=1.0)],
    )
    service = Mock(build_context=AsyncMock(return_value=long_term))
    service.retrieval_service.search = AsyncMock()
    monkeypatch.setattr(context, "get_memory_context_service", lambda: service)
    monkeypatch.setattr(records, "_resolve_tenant_embedding_model_info", lambda tenant: object())
    monkeypatch.setattr(__import__("management.services.memory.runtime_embedding", fromlist=["_"]), "compute_runtime_embedding", block_embedding)
    monkeypatch.setattr(compiler, "_get_external_provider_service_for_search", lambda: None)

    started = monotonic()
    try:
        items, _ = await compiler._prepare_runtime_memory(
            tenant_id="t", user_id="u", agent_id="1", conversation_id=None,
            query="sample", external_top_k=5, deadline=started + 0.25,
        )
        assert entered.is_set()
        assert monotonic() - started < 0.9
        assert items[0]["memory"] == "retained"
        service.retrieval_service._record_hits.assert_not_called()
    finally:
        release.set()
        for _ in range(100):
            if exited.is_set():
                break
            await asyncio.sleep(0.005)
    assert exited.is_set()

def test_embedding_circuit_retains_local_cooldown_during_redis_outage(cache, monkeypatch):
    shared, _ = cache
    shared.get.side_effect = redis.ConnectionError("connection refused")
    shared.set.side_effect = redis.ConnectionError("connection refused")
    local_time = Mock(return_value=100.0)
    monkeypatch.setattr(embedding_health, "time", SimpleNamespace(monotonic=local_time, time=local_time))

    assert embedding_health.admit_embedding("library") == ""
    embedding_health.record_embedding_failure("library")
    local_time.return_value += 299
    assert embedding_health.admit_embedding("library") is None

    local_time.return_value += 1
    assert embedding_health.admit_embedding("library") == "local"
    assert embedding_health.admit_embedding("library") is None
    embedding_health.record_embedding_success("library", "local")
    assert embedding_health.admit_embedding("library") == ""

@pytest.mark.parametrize(("status", "opens_circuit"), [(503, True), (401, False)])
@pytest.mark.asyncio
async def test_only_transient_http_failures_open_embedding_circuit(cache, monkeypatch, status, opens_circuit):
    model = EmbeddingModelInfo("test", 2, "http://localhost", "test")
    request = httpx.Request("POST", "http://localhost/embeddings")
    failure = httpx.HTTPStatusError("model request failed", request=request, response=httpx.Response(status))
    client = Mock(get_embeddings_with_deadline=AsyncMock(side_effect=[failure, [[0.25, 0.75]]]))


    assert await runtime_embedding.compute_runtime_embedding("first", model, tenant_id="t", client=client, deadline=monotonic() + 2) is None
    second = await runtime_embedding.compute_runtime_embedding("second", model, tenant_id="t", client=client, deadline=monotonic() + 2)
    assert second == (None if opens_circuit else [0.25, 0.75])
    assert client.get_embeddings_with_deadline.await_count == (1 if opens_circuit else 2)

@pytest.mark.parametrize("long_term_failed", [False, True])
@pytest.mark.asyncio
async def test_external_memory_survives_other_sources(monkeypatch, memory_thread_manager, long_term_failed):
    long_term = AsyncMock(
        return_value=MemorySearchContext(),
        side_effect=RuntimeError("database read failed") if long_term_failed else None,
    )
    service = Mock(build_context=long_term)
    provider_service = Mock(search_all_enabled=AsyncMock(return_value=[
        MemorySearchResult(layer=MemoryLayer.AGENT, external_id="external-1", content="external fact", score=0.9,
                           source="test-provider", is_external=True),
    ]))
    # The global top-K selection can omit an item already selected by the provider.
    service.pipeline.run.return_value.into_memory_search_context.return_value = MemorySearchContext()
    monkeypatch.setattr(context, "get_memory_context_service", lambda: service)
    monkeypatch.setattr(records, "_resolve_tenant_embedding_model_info", lambda _: None)
    monkeypatch.setattr(compiler, "_get_external_provider_service_for_search", lambda: provider_service)

    items, diagnostic = await compiler._prepare_runtime_memory(
        tenant_id="t", user_id="u", agent_id="1", conversation_id=None,
        query="question", external_top_k=3, deadline=monotonic() + 2,
    )
    assert items == []
    assert diagnostic.startswith("Found 1 relevant memories:")
    assert "#### External Memory" in diagnostic
    assert "external fact" in diagnostic
    assert provider_service.search_all_enabled.await_args.kwargs["limit"] == 3
    assert service.pipeline.run.call_args.kwargs["external_results"][0].content == "external fact"
    service.retrieval_service._record_hits.assert_not_called()
    long_term.assert_awaited_once()

@pytest.mark.parametrize("writer_unavailable", [False, True])
@pytest.mark.asyncio
async def test_local_hit_accounting_records_only_items_in_prompt(monkeypatch, memory_thread_manager, writer_unavailable):
    model = EmbeddingModelInfo("test", 2, "http://localhost", "test")
    selected = MemorySearchResult(layer=MemoryLayer.AGENT, memory_id=1, content="included", score=0.9)
    excluded = MemorySearchResult(layer=MemoryLayer.AGENT, memory_id=2, content="excluded", score=0.7)
    service = Mock(build_context=AsyncMock(return_value=MemorySearchContext()))
    service.retrieval_service.search = AsyncMock(return_value=[selected, excluded])
    service.pipeline.run.return_value.into_memory_search_context.return_value = MemorySearchContext(agent_short_term=[selected])
    submit = Mock(side_effect=RuntimeError("write lane unavailable") if writer_unavailable else None)
    formatter = Mock()
    formatter.format_search_context.return_value = "Found 1 relevant memory: included"
    monkeypatch.setattr(context, "get_memory_context_service", lambda: service)
    monkeypatch.setattr(records, "_resolve_tenant_embedding_model_info", lambda _: model)
    monkeypatch.setattr(__import__("management.services.memory.runtime_embedding", fromlist=["_"]), "compute_runtime_embedding", AsyncMock(return_value=[0.25, 0.75]))
    monkeypatch.setattr(compiler, "_get_external_provider_service_for_search", lambda: None)
    monkeypatch.setattr(compiler, "_create_fixed_search_memory_tool", lambda: formatter)
    monkeypatch.setattr(compiler, "get_default_thread_manager", lambda: SimpleNamespace(submit=submit))

    _, diagnostic = await compiler._prepare_runtime_memory(
        tenant_id="t", user_id="u", agent_id="1", conversation_id="2",
        query="question", external_top_k=3, deadline=monotonic() + 2,
    )
    assert diagnostic == "Found 1 relevant memory: included"
    assert service.retrieval_service.search.await_args.kwargs["write_hits"] is False
    assert submit.call_args.args[0] == "memory-write"
    assert submit.call_args.args[2] is service.retrieval_service._record_hits
    assert submit.call_args.kwargs["results"] == [selected]

def test_embedding_circuit_configures_bounded_redis_client(monkeypatch):
    make_client = Mock(return_value=object())
    monkeypatch.setattr(embedding_health.redis.Redis, "from_url", make_client)
    monkeypatch.setattr(embedding_health, "REDIS_BACKEND_URL", "")
    monkeypatch.setattr(embedding_health, "RUNTIME_STATE_REDIS_URL", "")
    embedding_health._client.cache_clear()
    try:
        assert embedding_health._client() is None
        monkeypatch.setattr(embedding_health, "RUNTIME_STATE_REDIS_URL", "redis://test/0")
        embedding_health._client.cache_clear()
        assert embedding_health._client() is embedding_health._client()
        make_client.assert_called_once_with(
            "redis://test/0", socket_connect_timeout=0.15, socket_timeout=0.15,
            max_connections=16, retry_on_timeout=False,
        )
    finally:
        embedding_health._client.cache_clear()

def test_disabling_cooldown_bypasses_redis(cache, monkeypatch):
    shared, _ = cache
    monkeypatch.setattr(embedding_health, "MEMORY_EMBEDDING_COOLDOWN_SECONDS", 0)
    embedding_health.record_embedding_failure("model")
    assert embedding_health.admit_embedding("model") == ""
    embedding_health.record_embedding_success("model", "")
    shared.get.assert_not_called()
    shared.set.assert_not_called()

def test_local_circuit_is_bounded_without_redis(cache, monkeypatch):
    monkeypatch.setattr(embedding_health, "_client", lambda: None)
    monkeypatch.setattr(embedding_health, "_MAX_LOCAL_CIRCUITS", 1)
    embedding_health.record_embedding_failure("previous")
    embedding_health.record_embedding_failure("current")
    assert embedding_health.admit_embedding("previous") == ""
    assert embedding_health.admit_embedding("current") is None

def test_shared_probe_release_error_leaves_local_state_recoverable(cache, monkeypatch):
    shared, data = cache
    shared.eval.side_effect = redis.TimeoutError("shared state unavailable")
    clock = Mock(return_value=100.0)
    monkeypatch.setattr(embedding_health, "time", SimpleNamespace(monotonic=clock, time=clock))
    embedding_health.record_embedding_failure("model")
    clock.return_value = 400.0
    token = embedding_health.admit_embedding("model")
    assert token and data["model:probe"] == token
    embedding_health.record_embedding_success("model", token)
    assert "model" not in embedding_health._local
    shared.eval.assert_called_once()

@pytest.mark.parametrize("seconds", [-1.0, 0.02])
@pytest.mark.asyncio
async def test_embedding_skips_when_deadline_has_no_transport_headroom(cache, monkeypatch, seconds):
    resolve_client = Mock()

    model = EmbeddingModelInfo("test", 2, "http://localhost", "test")
    assert await runtime_embedding.compute_runtime_embedding(
        "query", model, tenant_id="tenant", client=resolve_client, deadline=monotonic() + seconds
    ) is None
    resolve_client.assert_not_called()

@pytest.mark.asyncio
async def test_completed_embedding_after_deadline_cannot_reenter_context(cache, monkeypatch):
    model = EmbeddingModelInfo("test", 2, "http://localhost", "test")
    remaining = Mock(side_effect=[1.0, 1.0, 0.0])
    client = Mock(get_embeddings_with_deadline=AsyncMock(return_value=[[0.25, 0.75]]))
    monkeypatch.setattr(runtime_embedding, "remaining_time", remaining)

    assert await runtime_embedding.compute_runtime_embedding("sample", model, tenant_id="t", client=client, deadline=0) is None
    client.get_embeddings_with_deadline.assert_awaited_once_with("sample", timeout=0.95)

@pytest.mark.parametrize("pipeline_failure", [False, True])
@pytest.mark.asyncio
async def test_retrieval_diagnostics_keep_healthy_sql_memory(monkeypatch, memory_thread_manager, pipeline_failure):
    retained = MemorySearchResult(layer=MemoryLayer.USER, content="existing fact", score=1.0)
    external = MemorySearchResult(layer=MemoryLayer.AGENT, content="external fact", score=1.0, is_external=True)
    service = Mock(build_context=AsyncMock(return_value=MemorySearchContext(user_long_term=[retained])))
    if pipeline_failure:
        service.pipeline.run.side_effect = RuntimeError("ranking unavailable")
    out = Mock(search_all_enabled=AsyncMock(return_value=[external]))
    monkeypatch.setattr(context, "get_memory_context_service", lambda: service)
    model_lookup = Mock()
    monkeypatch.setattr(records, "_resolve_tenant_embedding_model_info", model_lookup)
    monkeypatch.setattr(compiler, "_get_external_provider_service_for_search", lambda: out)
    if pipeline_failure:
        model_lookup.return_value = None

    items, diagnostic = await compiler._prepare_runtime_memory(
        tenant_id="t", user_id="u", agent_id="1", conversation_id=None,
        query="useful lookup" if pipeline_failure else "", external_top_k=3, deadline=monotonic() + 2,
    )
    assert items[0]["memory"] == "existing fact"
    assert diagnostic == (None if pipeline_failure else "No relevant memories found.")
    assert model_lookup.called is pipeline_failure
    assert out.search_all_enabled.called is pipeline_failure


@pytest.mark.asyncio
async def test_management_passes_remaining_budget_over_signed_model_interface(monkeypatch):
    from management.services.memory import runtime_embedding as rpc

    client = Mock(invoke_model=AsyncMock(return_value=SimpleNamespace(output=[[0.25, 0.75]])))
    model = EmbeddingModelInfo("test", 2, "", "", model_id=7, revision="r1")
    monkeypatch.setattr(rpc, "_model_client", lambda: client)
    deadline = monotonic() + 0.5
    assert await rpc.compute_runtime_embedding("query", model, tenant_id="t", user_id="u", deadline=deadline) == [0.25, 0.75]
    invocation, user, tenant = client.invoke_model.await_args.args
    assert (invocation.model_id, invocation.expected_revision, user, tenant) == (7, "r1", "u", "t")
    assert 0 < invocation.memory_timeout_seconds <= 0.5
    assert "api_key" not in invocation.model_dump()


@pytest.mark.asyncio
async def test_management_model_rpc_is_cancelled_at_memory_deadline(monkeypatch):
    from management.services.memory import runtime_embedding as rpc

    cancelled = asyncio.Event()

    async def unavailable(*args):
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    client = Mock(invoke_model=AsyncMock(side_effect=unavailable))
    monkeypatch.setattr(rpc, "_model_client", lambda: client)
    model = EmbeddingModelInfo("test", 2, "", "", model_id=7)
    start = monotonic()
    assert await rpc.compute_runtime_embedding("query", model, tenant_id="t", user_id="u", deadline=start + 0.15) is None
    assert monotonic() - start < 0.5
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_non_openai_adapter_uses_one_attempt_and_shares_cooldown(cache):
    client = SimpleNamespace(invoke=AsyncMock(return_value=None))
    model = EmbeddingModelInfo("test", 2, "", "", model_id=7)
    for _ in range(2):
        assert await runtime_embedding.compute_runtime_embedding(
            "query", model, tenant_id="t", client=client, deadline=monotonic() + 1,
        ) is None
    client.invoke.assert_awaited_once()
    request = client.invoke.await_args.args[0]
    assert request.retries == 0
    assert request.worker_lane == "model-embedding"
    assert 0 < request.timeout <= 1
