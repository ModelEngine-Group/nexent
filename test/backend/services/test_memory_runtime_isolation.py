# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
from threading import Event
from time import monotonic
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio

from management.services.agent.preparation import compiler
from management.services.memory import access, context, embedding_health, records, runtime_embedding, runtime_io
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
