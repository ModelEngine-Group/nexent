# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from management.services.memory import access, provider, records, runtime_embedding, runtime_io
from nexent.memory.embedding_model import EmbeddingModelInfo


def test_create_memory_exact_idempotency_match_is_unchanged(monkeypatch):
    fake_db = MagicMock()
    fake_db.find_by_idempotency.return_value = {
        "memory_id": 7,
        "content": "existing preference",
    }
    monkeypatch.setattr(records, "memory_record_db", fake_db)
    monkeypatch.setattr(
        records,
        "_resolve_tenant_embedding_model_info",
        lambda _tenant_id: None,
    )

    service = records.MemoryRecordService()
    service.index_service = MagicMock()

    fake_embedding_model_info = MagicMock()
    fake_embedding_model_info.get_index_name = MagicMock(
        return_value="test_index"
    )

    result = service.create_memory(
        tenant_id="t1",
        user_id="u1",
        content="existing preference",
        layer="agent",
        memory_type="short_term",
        agent_id="a1",
        idempotency_key="same-key",
        embedding_model_info=fake_embedding_model_info,
    )

    assert result["event"] == "UNCHANGED"
    assert result["memory_id"] == 7
    fake_db.upsert_memory_record_by_idempotency.assert_not_called()
    service.index_service.index_record.assert_not_called()


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({"MEMORY_SWITCH": "Y"}, True),
        ({"MEMORY_SWITCH": "N"}, False),
        ({"MEMORY_SWITCH": "Y", "DISABLE_AGENT_ID": ["12"]}, False),
        ({"MEMORY_SWITCH": "Y", "DISABLE_USERAGENT_ID": ["12"]}, False),
    ],
)
def test_automatic_write_enforces_personal_policy(monkeypatch, settings, expected):
    monkeypatch.setattr(access, "get_user_configs", lambda _: settings)
    assert access.can_write_automatic_memory("t", "u", "12", 3) is expected

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

def test_automatic_write_fails_closed_when_policy_storage_fails(monkeypatch):
    monkeypatch.setattr(access, "get_user_configs", Mock(side_effect=TimeoutError))
    assert access.can_write_automatic_memory("tenant", "user", "1") is False

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
