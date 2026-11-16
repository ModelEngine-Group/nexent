# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
from threading import Event
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import pytest_asyncio
import redis

from management.services.agent.preparation import compiler
from management.services.memory import access, context, embedding_health, provider, records, runtime_embedding, runtime_io
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.memory.embedding_model import EmbeddingModelInfo
from nexent.memory.models import MemoryLayer, MemorySearchContext, MemorySearchResult


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


@pytest.mark.parametrize(
    "tenant_value, user_settings, agent_setting, expected",
    [
        (None, {"MEMORY_SWITCH": "Y"}, None, True),
        ("N", {"MEMORY_SWITCH": "Y"}, True, False),
        ("Y", {"MEMORY_SWITCH": "N"}, True, False),
        ("Y", {"MEMORY_SWITCH": "Y", "DISABLE_AGENT_ID": ["12"]}, True, False),
        ("Y", {"MEMORY_SWITCH": "Y", "DISABLE_USERAGENT_ID": ["12"]}, True, False),
        ("Y", {"MEMORY_SWITCH": "Y"}, False, False),
    ],
)
def test_automatic_write_enforces_persisted_policy(monkeypatch, tenant_value, user_settings, agent_setting, expected):
    from_db = {"config_value": tenant_value} if tenant_value is not None else {}
    monkeypatch.setattr(access, "get_single_config_info", lambda *_: from_db)
    monkeypatch.setattr(access, "get_user_configs", lambda *_: user_settings)
    lookup = Mock(return_value={"enable_memory": agent_setting})
    monkeypatch.setattr(access, "search_agent_info_by_agent_id", lookup)
    assert access.can_write_automatic_memory("t", "u", "12", 3) is expected
    if lookup.called:
        lookup.assert_called_once_with(12, "t", 3)


def test_automatic_store_with_no_vector_does_not_persist(monkeypatch):
    db = Mock()
    monkeypatch.setattr(records, "memory_record_db", db)
    model = EmbeddingModelInfo("test", 2, "http://localhost", "test")
    index = Mock()
    service = records.MemoryRecordService(index_service=index)

    with pytest.raises(records.MemoryRecordError, match="embedding is unavailable"):
        service.create_memory(
            tenant_id="t", user_id="u", agent_id="1", content="preference",
            embedding_model_info=model, deadline=monotonic() + 5,
        )
    db.insert_memory_record.assert_not_called()
    index.index_record.assert_not_called()


def test_automatic_store_index_failure_can_be_retried_without_duplicate(monkeypatch):
    db = Mock()
    db.find_by_idempotency.side_effect = [None, {"content": "preference", "memory_id": 23}]
    db.insert_memory_record.return_value = 23
    monkeypatch.setattr(records, "memory_record_db", db)
    index = Mock()
    index.index_record.side_effect = [False, True]
    service = records.MemoryRecordService(index_service=index)
    args = dict(
        tenant_id="t", user_id="u", agent_id="1", content="preference", idempotency_key="same",
        embedding_model_info=EmbeddingModelInfo("test", 2, "http://localhost", "test"),
        embedding=[0.5, 0.5], deadline=monotonic() + 5, write_allowed=lambda: True,
    )

    with pytest.raises(records.MemoryRecordError, match="indexing is incomplete"):
        service.create_memory(**args)
    result = service.create_memory(**args)
    assert result["memory_id"] == 23
    assert result["indexed"]
    assert db.insert_memory_record.call_count == 1
    assert index.index_record.call_count == 2


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
async def test_automatic_store_rechecks_policy_after_embedding_before_persistence(monkeypatch):
    model = EmbeddingModelInfo("test", 2, "http://localhost", "test")
    allowed = Mock(return_value=True)

    async def embed(*args, **kwargs):
        allowed.return_value = False
        return [0.25, 0.75]

    service = records.MemoryRecordService(index_service=Mock())
    db = Mock()
    fanout = AsyncMock()
    monkeypatch.setattr(records, "memory_record_db", db)
    monkeypatch.setattr(provider, "get_memory_record_service", lambda: service)
    monkeypatch.setattr(provider, "_resolve_tenant_embedding_model_info", lambda _: model)
    monkeypatch.setattr(runtime_embedding, "compute_runtime_embedding", embed)
    monkeypatch.setattr(provider, "_fanout_external_ingest", fanout)

    with pytest.raises(PermissionError, match="Automatic memory was disabled"):
        await provider._backend_store_hook(
            {"tenant_id": "t", "user_id": "u", "agent_id": "1", "content": "preference"},
            deadline=monotonic() + 3,
            write_allowed=allowed,
        )
    db.insert_memory_record.assert_not_called()
    service.index_service.index_record.assert_not_called()
    fanout.assert_not_awaited()


@pytest.mark.asyncio
async def test_policy_change_after_store_blocks_external_forwarding(monkeypatch):
    model = EmbeddingModelInfo("test", 2, "http://localhost", "test")
    allowed = Mock(side_effect=[True, False])
    saved = {"memory_id": 5, "indexed": True}
    service = Mock(create_memory=Mock(return_value=saved))
    fanout = AsyncMock()
    monkeypatch.setattr(provider, "get_memory_record_service", lambda: service)
    monkeypatch.setattr(provider, "_resolve_tenant_embedding_model_info", lambda _: model)
    monkeypatch.setattr(provider, "_fanout_external_ingest", fanout)

    assert await provider._backend_store_hook(
        {"tenant_id": "t", "user_id": "u", "agent_id": "1", "content": "preference", "embedding": [0.25, 0.75]},
        deadline=monotonic() + 3,
        write_allowed=allowed,
    ) == saved
    assert service.create_memory.call_args.kwargs["write_allowed"] is allowed
    fanout.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_store_rejects_cross_agent_scope_before_io(monkeypatch):
    backend = AsyncMock()
    monkeypatch.setattr(provider, "_backend_store_hook", backend)
    store = provider._runtime_store("t", "u", "1", 3)

    with pytest.raises(PermissionError, match="scope"):
        await store({"tenant_id": "t", "user_id": "u", "agent_id": "other", "content": "preference"})
    backend.assert_not_awaited()


@pytest.mark.asyncio
async def test_external_memory_survives_missing_embedding_and_counts_no_local_hits(monkeypatch, memory_thread_manager):
    service = Mock(build_context=AsyncMock(return_value=MemorySearchContext()))
    provider_service = Mock(search_all_enabled=AsyncMock(return_value=[
        MemorySearchResult(layer=MemoryLayer.AGENT, external_id="external-1", content="external fact", score=0.9,
                           source="test-provider", is_external=True),
    ]))
    selected = MemorySearchResult(layer=MemoryLayer.AGENT, external_id="external-1", content="external fact", score=0.9,
                                  source="test-provider", is_external=True)
    service.pipeline.run.return_value.into_memory_search_context.return_value = MemorySearchContext(agent_short_term=[selected])
    formatter = Mock()
    formatter._format_context.return_value = "Found 1 relevant memory: external fact"
    monkeypatch.setattr(context, "get_memory_context_service", lambda: service)
    monkeypatch.setattr(records, "_resolve_tenant_embedding_model_info", lambda _: None)
    monkeypatch.setattr(compiler, "_get_external_provider_service_for_search", lambda: provider_service)
    monkeypatch.setattr(compiler, "_create_fixed_search_memory_tool", lambda: formatter)

    items, diagnostic = await compiler._prepare_runtime_memory(
        tenant_id="t", user_id="u", agent_id="1", conversation_id=None,
        query="question", external_top_k=3, deadline=monotonic() + 2,
    )
    assert items == []
    assert diagnostic == "Found 1 relevant memory: external fact"
    assert provider_service.search_all_enabled.await_args.kwargs["limit"] == 3
    assert service.pipeline.run.call_args.kwargs["external_results"][0].content == "external fact"
    service.retrieval_service._record_hits.assert_not_called()


@pytest.mark.asyncio
async def test_valid_runtime_store_uses_separate_write_lane_and_its_run_scope(monkeypatch):
    backend = AsyncMock(return_value={"memory_id": 1})
    permissions = Mock(return_value=True)

    async def run_in_lane(name, callback, *, deadline, lane):
        assert name == "memory-store"
        assert lane == "memory-write"
        assert deadline > monotonic()
        assert deadline < monotonic() + 3
        return await asyncio.to_thread(callback)

    monkeypatch.setattr(provider, "_backend_store_hook", backend)
    monkeypatch.setattr(access, "can_write_automatic_memory", permissions)
    monkeypatch.setattr(runtime_io, "MEMORY_WRITE_TIMEOUT_SECONDS", 2)
    monkeypatch.setattr(runtime_io, "run_memory_io", run_in_lane)
    store = provider._runtime_store("t", "u", "1", 3)
    payload = {"tenant_id": "t", "user_id": "u", "agent_id": "1", "content": "preference"}

    assert await store(payload) == {"memory_id": 1}
    assert backend.await_args.args == (payload,)
    assert backend.await_args.kwargs["write_allowed"]()
    permissions.assert_called_once_with("t", "u", "1", 3)


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
    formatter._format_context.return_value = "Found 1 relevant memory: included"
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


@pytest.mark.asyncio
async def test_automatic_write_rechecks_deadline_before_calling_store(monkeypatch):
    record_service = Mock()
    monkeypatch.setattr(provider, "get_memory_record_service", record_service)

    with pytest.raises(PermissionError, match="disabled or expired"):
        await provider._backend_store_hook(
            {"tenant_id": "t", "user_id": "u", "agent_id": "1", "content": "preference"},
            deadline=monotonic() - 1,
            write_allowed=lambda: True,
        )
    record_service.assert_not_called()


@pytest.mark.asyncio
async def test_external_write_timeout_keeps_local_result(monkeypatch):
    async def external_store(*args):
        await asyncio.Future()

    saved = {"memory_id": 2, "indexed": True}
    service = Mock(create_memory=Mock(return_value=saved))
    fanout = AsyncMock(side_effect=external_store)
    monkeypatch.setattr(provider, "get_memory_record_service", lambda: service)
    monkeypatch.setattr(provider, "_resolve_tenant_embedding_model_info", lambda _: object())
    monkeypatch.setattr(provider, "_fanout_external_ingest", fanout)
    payload = {"tenant_id": "t", "user_id": "u", "agent_id": "1", "content": "preference", "embedding": [0.25, 0.75]}

    assert await asyncio.wait_for(
        provider._backend_store_hook(payload, deadline=monotonic() + 0.25, write_allowed=lambda: True),
        timeout=1,
    ) == saved
    fanout.assert_awaited_once_with(payload, saved)


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


def test_source_agent_policy_uses_released_version_and_denies_missing_agent(monkeypatch):
    query_version = Mock(return_value=7)
    lookup = Mock(side_effect=[{"enable_memory": False}, access.AgentNotFoundError("missing")])
    monkeypatch.setattr(access, "query_current_version_no", query_version)
    monkeypatch.setattr(access, "search_agent_info_by_agent_id", lookup)
    assert access.source_agent_allows_memory("tenant", "1") is False
    lookup.assert_called_once_with(1, "tenant", 7)
    assert access.source_agent_allows_memory("tenant", 2, 99) is False
    assert access.source_agent_allows_memory("tenant", "unknown") is False
    query_version.assert_called_once_with(1, "tenant")


def test_automatic_write_fails_closed_when_policy_storage_fails(monkeypatch):
    monkeypatch.setattr(access, "get_user_configs", Mock(side_effect=TimeoutError))
    assert access.can_write_automatic_memory("tenant", "user", "1") is False


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


@pytest.mark.asyncio
async def test_automatic_store_handles_missing_vector_model_before_calling_database(monkeypatch):
    record_service = Mock()
    fanout = AsyncMock()
    monkeypatch.setattr(provider, "get_memory_record_service", lambda: record_service)
    monkeypatch.setattr(provider, "_resolve_tenant_embedding_model_info", lambda _: None)
    monkeypatch.setattr(provider, "_fanout_external_ingest", fanout)
    with pytest.raises(records.MemoryRecordError, match="not configured"):
        await provider._backend_store_hook(
            {"tenant_id": "t", "user_id": "u", "agent_id": "1", "content": "preference"},
            deadline=monotonic() + 3, write_allowed=lambda: True,
        )
    record_service.create_memory.assert_not_called()
    fanout.assert_not_awaited()


@pytest.mark.parametrize("consent_consumes_budget", [False, True])
def test_automatic_record_never_writes_after_deadline(monkeypatch, consent_consumes_budget):
    database = Mock()
    index = Mock()
    state = Mock(side_effect=[0.0, 2.0] if consent_consumes_budget else [2.0])
    allowed = Mock(return_value=True)
    monkeypatch.setattr(records, "time", SimpleNamespace(monotonic=state))
    monkeypatch.setattr(records, "memory_record_db", database)
    service = records.MemoryRecordService(index_service=index)

    with pytest.raises(records.MemoryRecordError, match="deadline expired"):
        service.create_memory(
            tenant_id="t", user_id="u", agent_id="1", content="preference", embedding=[0.25, 0.75],
            embedding_model_info=EmbeddingModelInfo("test", 2, "http://localhost", "test"),
            deadline=1.0, write_allowed=allowed,
        )
    assert allowed.called is consent_consumes_budget
    database.insert_memory_record.assert_not_called()
    database.upsert_memory_record_by_idempotency.assert_not_called()
    index.index_record.assert_not_called()


@pytest.mark.parametrize("content_unchanged", [False, True])
def test_automatic_record_retry_cannot_report_success_without_indexing(monkeypatch, content_unchanged):
    database = Mock()
    database.find_by_idempotency.return_value = {
        "memory_id": 4, "content": "new preference" if content_unchanged else "old preference",
    }
    database.upsert_memory_record_by_idempotency.return_value = 4
    index = Mock()
    index.index_record.return_value = False
    monkeypatch.setattr(records, "memory_record_db", database)
    service = records.MemoryRecordService(index_service=index)

    with pytest.raises(records.MemoryRecordError, match="indexing is incomplete"):
        service.create_memory(
            tenant_id="t", user_id="u", agent_id="1", content="new preference",
            idempotency_key="stable", embedding=[0.25, 0.75],
            embedding_model_info=EmbeddingModelInfo("test", 2, "http://localhost", "test"),
            deadline=monotonic() + 2, write_allowed=lambda: True,
        )
    database.insert_memory_record.assert_not_called()
    assert database.upsert_memory_record_by_idempotency.called is (not content_unchanged)
    index.index_record.assert_called_once()


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
