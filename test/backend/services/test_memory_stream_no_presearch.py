# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import json
from threading import Event
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import httpx
import pytest
import pytest_asyncio
import redis

from contracts.agent import AgentRequest
from management.services.agent import execution as agent_execution
from management.services.agent import run as agent_run
from management.services.agent.preparation import compiler
from management.services.memory import context, embedding_health, records, runtime_embedding, runtime_io
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.memory.embedding_model import EmbeddingModelInfo
from nexent.memory.models import MemoryLayer, MemorySearchContext, MemorySearchResult


@pytest.mark.asyncio
async def test_memory_enabled_stream_does_not_emit_presearch_events(monkeypatch):
    request = AgentRequest(
        agent_id=7,
        conversation_id=777,
        query="question",
        history=[],
        minio_files=[],
        is_debug=False,
    )
    channel = AsyncMock()
    monkeypatch.setattr(
        agent_run.streaming_channel_manager,
        "get_or_create_channel",
        AsyncMock(return_value=channel),
    )
    monkeypatch.setattr(
        agent_run,
        "build_memory_context",
        MagicMock(
            return_value=MagicMock(
                user_config=MagicMock(memory_switch=True)
            )
        ),
    )
    prepare = AsyncMock(return_value=(MagicMock(), MagicMock()))
    monkeypatch.setattr(agent_run, "prepare_agent_run", prepare)

    async def chunks(**_kwargs):
        yield "data: body\n\n"

    monkeypatch.setattr(agent_run, "_stream_agent_chunks", chunks)

    output = [
        chunk
        async for chunk in agent_run.generate_stream(
            request,
            user_id="user-1",
            tenant_id="tenant-1",
            enable_memory=True,
        )
    ]

    assert output == ["data: body\n\n"]
    assert not any("memory_search" in chunk for chunk in output)
    assert not any(
        "memory_search" in str(call.args)
        for call in channel.publish.await_args_list
    )
    prepare.assert_awaited_once_with(
        agent_request=request,
        user_id="user-1",
        tenant_id="tenant-1",
        language=agent_run.LANGUAGE["ZH"],
        allow_memory_search=True,
    )


@pytest.mark.asyncio
async def test_fixed_search_is_streamed_and_persisted_as_structured_tool(monkeypatch):
    request = AgentRequest(
        agent_id=7,
        conversation_id=777,
        query="question",
        history=[],
        minio_files=[],
        is_debug=False,
    )
    pre_run_events = [
        {
            "type": "tool",
            "content": "",
            "tool_name": "search_memory",
            "tool_arguments": {"query": "question", "top_k": 5},
        },
        {
            "type": "execution_logs",
            "content": "No relevant memories found.",
        },
    ]
    run_info = MagicMock()
    run_info.agent_config.pre_run_tool_events = pre_run_events
    run_info.stop_event.is_set.return_value = False

    async def fake_agent_run(_run_info, **_kwargs):
        yield json.dumps({"type": "final_answer", "content": "Done"})

    async def run_inline(_lane, _spec, func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(agent_execution, "agent_run", fake_agent_run)
    monkeypatch.setattr(agent_execution.runtime_thread_manager, "run", run_inline)
    monkeypatch.setattr(agent_execution, "save_message", lambda *args, **kwargs: 42)
    monkeypatch.setattr(
        agent_execution.agent_run_manager,
        "unregister_agent_run",
        lambda *args, **kwargs: None,
    )
    persisted_batches = []
    monkeypatch.setattr(
        agent_execution,
        "persist_assistant_run_batch",
        lambda **kwargs: persisted_batches.append(kwargs),
    )
    monkeypatch.setattr(
        agent_execution.streaming_channel_manager,
        "complete_channel",
        AsyncMock(),
    )
    monkeypatch.setattr(agent_execution, "_cleanup_channel_later", AsyncMock())
    channel = AsyncMock()

    chunks = [
        chunk
        async for chunk in agent_execution._stream_agent_chunks(
            request,
            "user-1",
            "tenant-1",
            run_info,
            MagicMock(),
            channel=channel,
        )
    ]

    streamed_tool = json.loads(chunks[0].removeprefix("data: ").strip())
    assert streamed_tool == {
        **pre_run_events[0],
        "unit_index": 0,
    }

    assert len(persisted_batches) == 1
    saved_units = persisted_batches[0]["message_units"]
    tool_unit = next(unit for unit in saved_units if unit["unit_type"] == "tool")
    persisted_tool = json.loads(tool_unit["unit_content"])
    assert persisted_tool == {
        "content": "",
        "tool_name": "search_memory",
        "tool_arguments": {"query": "question", "top_k": 5},
    }


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
    monkeypatch.setattr(runtime_embedding, "get_embedding_client", Mock(return_value=client))

    assert await runtime_embedding.compute_runtime_embedding("first", model, tenant_id="t", deadline=monotonic() + 2) is None
    key = embedding_health.embedding_circuit_key("t", model)
    assert redis_client.set.call_args.kwargs["ex"] >= 300

    # Simulate a separate worker with a cold local cache.
    embedding_health._local.clear()
    assert await runtime_embedding.compute_runtime_embedding("second", model, tenant_id="t", deadline=monotonic() + 2) is None
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
    monkeypatch.setattr(runtime_io, "runtime_thread_manager", manager)
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
    monkeypatch.setattr(runtime_embedding, "compute_runtime_embedding", block_embedding)
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
    monkeypatch.setattr(runtime_embedding, "get_embedding_client", lambda **_: client)

    assert await runtime_embedding.compute_runtime_embedding("first", model, tenant_id="t", deadline=monotonic() + 2) is None
    second = await runtime_embedding.compute_runtime_embedding("second", model, tenant_id="t", deadline=monotonic() + 2)
    assert second == (None if opens_circuit else [0.25, 0.75])
    assert client.get_embeddings_with_deadline.await_count == (1 if opens_circuit else 2)

@pytest.mark.asyncio
async def test_external_memory_survives_missing_embedding_and_counts_no_local_hits(monkeypatch, memory_thread_manager):
    service = Mock(build_context=AsyncMock(return_value=MemorySearchContext()))
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
    monkeypatch.setattr(runtime_embedding, "compute_runtime_embedding", AsyncMock(return_value=[0.25, 0.75]))
    monkeypatch.setattr(compiler, "_get_external_provider_service_for_search", lambda: None)
    monkeypatch.setattr(compiler, "_create_fixed_search_memory_tool", lambda: formatter)
    monkeypatch.setattr(compiler, "runtime_thread_manager", SimpleNamespace(submit=submit))

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
    monkeypatch.setattr(runtime_embedding, "get_embedding_client", resolve_client)
    model = EmbeddingModelInfo("test", 2, "http://localhost", "test")
    assert await runtime_embedding.compute_runtime_embedding(
        "query", model, tenant_id="tenant", deadline=monotonic() + seconds
    ) is None
    resolve_client.assert_not_called()

@pytest.mark.asyncio
async def test_completed_embedding_after_deadline_cannot_reenter_context(cache, monkeypatch):
    model = EmbeddingModelInfo("test", 2, "http://localhost", "test")
    remaining = Mock(side_effect=[1.0, 1.0, 0.0])
    client = Mock(get_embeddings_with_deadline=AsyncMock(return_value=[[0.25, 0.75]]))
    monkeypatch.setattr(runtime_embedding, "remaining_time", remaining)
    monkeypatch.setattr(runtime_embedding, "get_embedding_client", lambda **_: client)
    assert await runtime_embedding.compute_runtime_embedding("sample", model, tenant_id="t", deadline=0) is None
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
