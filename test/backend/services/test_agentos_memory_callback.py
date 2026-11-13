# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from contracts.agentos import AgentMemoryReceipt, AgentMemoryStored, AgentResource, ToolBinding
from infrastructure.agentos_identity import ServicePrincipal
from management.services.memory import agentos_callback
from runtime.agentos import prepared_memory

ACTOR = ServicePrincipal("user-a", "tenant-a")
NOTICE = AgentMemoryStored(memory_id=17, agent_id=7, conversation_id=42)


@pytest.fixture
def callback(monkeypatch):
    record = {
        "tenant_id": "tenant-a", "user_id": "user-a", "agent_id": "7", "conversation_id": "41",
        "layer": "agent", "memory_type": "short_term", "status": "active", "content": "committed",
    }
    owns = Mock(return_value=True)
    read = Mock(return_value=record)
    ingest = AsyncMock()

    async def inline(_name, fn, *args, **_options):
        return fn(*args)

    monkeypatch.setattr(agentos_callback, "run_blocking", inline)
    monkeypatch.setattr(agentos_callback, "conversation_belongs_to", owns)
    monkeypatch.setattr(agentos_callback, "get_memory_record", read)
    monkeypatch.setattr(agentos_callback, "_fanout_external_ingest", ingest)
    return SimpleNamespace(record=record, owns=owns, read=read, ingest=ingest)


@pytest.mark.asyncio
async def test_ingest_uses_committed_content_with_current_owned_conversation(callback):
    assert await agentos_callback.ingest_stored_agent_memory(NOTICE, ACTOR)
    callback.owns.assert_called_once_with(42, user_id="user-a", tenant_id="tenant-a")
    callback.read.assert_called_once_with(17, "tenant-a")
    callback.ingest.assert_awaited_once_with({**callback.record, "conversation_id": "42"}, {"memory_id": 17})


@pytest.mark.asyncio
async def test_foreign_conversation_does_not_read_record(callback):
    callback.owns.return_value = False
    assert not await agentos_callback.ingest_stored_agent_memory(NOTICE, ACTOR)
    callback.read.assert_not_called()
    callback.ingest.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("updates", [
    {"tenant_id": "tenant-b"}, {"user_id": "user-b"}, {"agent_id": "8"}, {"layer": "user"},
    {"memory_type": "long_term"}, {"status": "archived"},
])
async def test_invalid_record_does_not_ingest(callback, updates):
    callback.record.update(updates)
    assert not await agentos_callback.ingest_stored_agent_memory(NOTICE, ACTOR)
    callback.ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_callback_transport_failure_preserves_committed_tool_receipt(monkeypatch):
    store = AsyncMock(return_value=AgentMemoryReceipt(memory_id=17, event="ADD"))
    post = AsyncMock(side_effect=httpx.ConnectError("offline"))
    client = AsyncMock()
    client.__aenter__.return_value = SimpleNamespace(post=post)
    monkeypatch.setattr(prepared_memory, "get_memory_store_service", lambda: SimpleNamespace(store=store))
    monkeypatch.setattr(prepared_memory, "sign_call", Mock(return_value="signature"))
    monkeypatch.setattr(prepared_memory.httpx, "AsyncClient", Mock(return_value=client))
    resource = AgentResource(
        agent_id=7, version_no=1, name="agent", description="", prompt_templates={},
        tools=[ToolBinding(tool_id="store_memory", version="1")],
    )
    tools, _ = prepared_memory.materialize_memory(resource, ACTOR, 42)

    result = await tools["store_memory"].metadata["memory_service"].backend_store({
        "content": "memo", "idempotency_key": "once",
    })

    assert result["event"] == "ADD" and result["memory_id"] == 17
    post.assert_awaited_once()
    assert AgentMemoryStored.model_validate_json(post.await_args.kwargs["content"]) == NOTICE
