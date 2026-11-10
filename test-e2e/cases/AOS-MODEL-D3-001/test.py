# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify the signed model API and SDK dispatch to a controlled provider."""

import asyncio
import json
import socket
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from pydantic import BaseModel
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from contracts.agentos import ChatInvocation, ChatMessage, ChatOptions, EmbeddingInvocation, ModelAdministrationOperation
from contracts.constants import environment
from contracts.model_administration import ModelHealthcheck, ModelRegistration, ModelTenantDeactivation
from contracts.errors.exceptions import RuntimeUpstreamError
from gateway.downstream.middleware import GatewayIdentityMiddleware
from management.clients.agentos import AgentOSClient
from management.clients.model import embed_query_in_worker, invoke_chat_prompt_in_worker
from management.services.memory.extraction import AgentOSMemoryExtractionModel
from management.services.memory.embedding import embed_memory_text
from nexent.memory.embedding_model import EmbeddingModelInfo
from nexent.core.concurrency import (
    LanePolicy, ManagedTaskSpec, ThreadManager, clear_default_thread_manager, set_default_thread_manager,
    shutdown_fallback_thread_manager,
)
from infrastructure.model_adapter import get_adapter_from_config
from runtime.agentos.middleware import AgentOSMiddleware
from runtime.agentos.model import create_model_router
from runtime.agentos.model_administration import create_model_administration_router
from runtime.model import health, registry
from runtime.model.service import ModelService

@contextmanager
def serve(app):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="error"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not worker.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("AgentOS verification server did not start")
                time.sleep(0.02)
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            worker.join(timeout=10)
            assert not worker.is_alive(), "AgentOS verification leaked a server"


@pytest.fixture
async def managed_provider_threads():
    try:
        yield
    finally:
        await shutdown_fallback_thread_manager()


@pytest.mark.stage("D3")
@pytest.mark.case_id("AOS-MODEL-D3-001")
@pytest.mark.asyncio
async def test_agentos_model_over_http(monkeypatch, managed_provider_threads):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    key = "synthetic-agentos-model-fixture-secret"
    monkeypatch.setattr(environment, "JWT_SECRET", key)
    monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", key)
    provider = FastAPI()
    calls = []

    @provider.post("/v1/chat/completions")
    async def complete(request: Request):
        calls.append((request.headers["authorization"], await request.json()))
        chunk = {
            "id": "model-test",
            "created": 1,
            "object": "chat.completion.chunk",
            "model": "test-model",
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": "verified answer"},
                "finish_reason": "stop",
            }],
        }
        return StreamingResponse(
            iter([f"data: {json.dumps(chunk)}\n\n", "data: [DONE]\n\n"]),
            media_type="text/event-stream",
        )

    embed_calls = []

    @provider.post("/v1/embeddings")
    async def embed(request: Request):
        embed_calls.append((request.headers["authorization"], await request.json()))
        return {"data": [{"embedding": [0.1, 0.2]}]}

    with serve(provider) as provider_url:
        record = {
            "tenant_id": "tenant-a",
            "delete_flag": "N",
            "model_name": "test-model",
            "model_type": "llm",
            "model_factory": "openai",
            "base_url": f"{provider_url}/v1",
            "api_key": "provider-secret",
            "update_time": "2026-11-09T00:00:00",
        }

        def lookup(model_id, tenant_id):
            if tenant_id != "tenant-a":
                return None
            if model_id == 11:
                return record
            if model_id == 17:
                return {
                    **record, "model_name": "test-embedding", "model_type": "embedding",
                    "base_url": f"{provider_url}/v1/embeddings",
                }
            return None

        records = {}

        def insert(model, user_id, tenant_id):
            records[(tenant_id, model["display_name"])] = {**model, "model_id": 12, "created_by": user_id}
            return True

        def created_ids(names, tenant, model_type):
            return {records[(tenant, name)]["model_id"] for name in names}

        retired = set()
        records[("tenant-b", "other-model")] = {"model_id": 13}

        def retire_tenant(actor, tenant):
            assert actor == "user-a"
            pending = {key for key in records if key[0] == tenant} - retired
            retired.update(pending)
            return len(pending)

        def load_saved(name, tenant_id, model_type):
            return records.get((tenant_id, name))

        checked_keys = []

        async def probe_saved(*args, **kwargs):
            checked_keys.append(args[3])
            return True

        monkeypatch.setattr("runtime.agentos.model_administration.deactivate_tenant_models", retire_tenant)
        monkeypatch.setattr(registry, "create_model_record", insert)
        monkeypatch.setattr(registry, "get_created_model_ids", created_ids)
        monkeypatch.setattr(registry, "get_models_by_display_name", lambda *args: [])
        monkeypatch.setattr(health, "get_model_by_display_name", load_saved)
        monkeypatch.setattr(health, "update_model_record", lambda *args, **kwargs: True)
        monkeypatch.setattr(health, "_perform_connectivity_check", probe_saved)

        app = FastAPI(root_path="/api")
        app.add_middleware(GatewayIdentityMiddleware, audience="runtime", required=True)
        app.add_middleware(AgentOSMiddleware)
        app.include_router(create_model_router(ModelService(lookup, get_adapter_from_config)))
        app.include_router(create_model_administration_router())

        with serve(app) as runtime_url:
            agentos = AgentOSClient(runtime_url, lambda **kwargs: httpx.AsyncClient(trust_env=False, **kwargs))
            model = await agentos.get_model(11, "user-a", "tenant-a")
            assert model.revision == record["update_time"]
            assert "provider-secret" not in model.model_dump_json()
            assert "base_url" not in model.model_dump()

            request = ChatInvocation(
                model_id=11,
                input=[ChatMessage(role="user", content="verify model")],
                expected_revision=model.revision,
                options=ChatOptions(temperature=0.3, top_p=0.95, max_output_tokens=700),
            )
            result = await agentos.invoke_model(request, "user-a", "tenant-a")
            assert result.output == {"content": "verified answer"}
            assert result.revision == model.revision

            for invalid, tenant, status in (
                (request, "tenant-b", 404),
                (request.model_copy(update={"expected_revision": "stale"}), "tenant-a", 409),
                (EmbeddingInvocation(model_id=11, input=["test"]), "tenant-a", 422),
            ):
                with pytest.raises(RuntimeUpstreamError) as failure:
                    await agentos.invoke_model(invalid, "user-a", tenant)
                assert failure.value.status_code == status

            monkeypatch.setattr(environment, "RUNTIME_SERVICE_URL", runtime_url)
            output = await asyncio.to_thread(
                invoke_chat_prompt_in_worker,
                model_id=11,
                system_prompt="system",
                user_prompt="worker model request",
                user_id="worker-a",
                tenant_id="tenant-a",
            )
            assert output == "verified answer"

            extraction = AgentOSMemoryExtractionModel(model_id=11, user_id="worker-a", tenant_id="tenant-a")
            messages = [{"role": "user", "content": "extract memory"}]
            assert await extraction.chat(messages) == "verified answer"
            denied_extraction = AgentOSMemoryExtractionModel(model_id=11, user_id="worker-a", tenant_id="tenant-b")
            with pytest.raises(RuntimeUpstreamError) as failure:
                await denied_extraction.chat(messages)
            assert failure.value.status_code == 404

            assert await asyncio.to_thread(
                embed_query_in_worker, model_id=17, query="search", user_id="worker-a", tenant_id="tenant-a",
            ) == [0.1, 0.2]
            with pytest.raises(RuntimeUpstreamError) as failure:
                await agentos.invoke_model(
                    EmbeddingInvocation(model_id=17, input=["search"]), "worker-a", "tenant-b",
                )
            assert failure.value.status_code == 404

            memory_model = EmbeddingModelInfo(
                model_name="test-embedding", dimension=2, model_id=17, revision=record["update_time"] + "Z",
                base_url="http://unused-management.invalid", api_key="unused-management-key",
            )
            assert await embed_memory_text("recall", memory_model, "worker-a", "tenant-a") == [0.1, 0.2]
            assert await embed_memory_text("foreign recall", memory_model, "worker-a", "tenant-b") is None
            memory_model.revision = "stale"
            assert await embed_memory_text("stale recall", memory_model, "worker-a", "tenant-a") is None
            memory_model.revision = record["update_time"]
            with monkeypatch.context() as memory_patches:
                await _assert_memory_write_uses_signed_embedding(memory_patches, memory_model)

            registration = ModelRegistration(
                model_name="new-model", model_type="llm", base_url=record["base_url"], api_key="test-registration-key",
            )
            assert await agentos.model_command(
                ModelAdministrationOperation.REGISTER, registration, "user-a", "tenant-a",
            ) == [12]
            assert records[("tenant-a", "new-model")]["created_by"] == "user-a"
            request = ModelHealthcheck(display_name="new-model", model_type="llm")
            result = await agentos.model_command(
                ModelAdministrationOperation.HEALTHCHECK, request, "user-a", "tenant-a",
            )
            assert result == {"connectivity": True, "model_name": "new-model"}
            with pytest.raises(RuntimeUpstreamError) as failure:
                await agentos.model_command(ModelAdministrationOperation.HEALTHCHECK, request, "user-b", "tenant-b")
            assert failure.value.status_code == 404

            class ForgedRegistration(BaseModel):
                model_name: str = "forged"
                model_type: str = "llm"
                tenant_id: str = "tenant-a"

            with pytest.raises(RuntimeUpstreamError) as failure:
                await agentos.model_command(
                    ModelAdministrationOperation.REGISTER, ForgedRegistration(), "user-b", "tenant-b",
                )
            assert failure.value.status_code == 422

            cleanup = ModelTenantDeactivation()
            for expected in (1, 0):
                assert await agentos.model_command(
                    ModelAdministrationOperation.DEACTIVATE_TENANT, cleanup, "user-a", "tenant-a",
                ) == expected

    assert set(records) == {("tenant-a", "new-model"), ("tenant-b", "other-model")}
    assert retired == {("tenant-a", "new-model")}
    assert checked_keys == ["test-registration-key"]
    assert len(calls) == 3
    assert calls[2][1]["messages"][-1]["content"] == "extract memory"
    assert (calls[2][1]["temperature"], calls[2][1]["top_p"]) == (0.1, 0.9)
    assert calls[1][1]["messages"][-1]["content"] == "worker model request"
    authorization, provider_input = calls[0]
    assert authorization == "Bearer provider-secret"
    assert provider_input["model"] == "test-model"
    assert provider_input["temperature"] == 0.3
    assert provider_input["top_p"] == 0.95
    assert provider_input["messages"][-1]["content"] == "verify model"
    assert provider_input["max_tokens"] == 700
    assert embed_calls == [
        ("Bearer provider-secret", {"model": "test-embedding", "input": [query]})
        for query in ("search", "recall", "store memory", "updated memory")
    ]


async def _assert_memory_write_uses_signed_embedding(monkeypatch, model):
    from management.services.memory import provider as memory_provider, records as memory_records

    rows = {}
    index = Mock()
    index.index_record.side_effect = lambda *, embedding, **_: bool(embedding)

    def insert(values):
        memory_id = len(rows) + 1
        rows[memory_id] = {**values, "memory_id": memory_id}
        return memory_id

    def find(*, tenant_id, idempotency_key):
        return next((row for row in rows.values() if
                     (row["tenant_id"], row["idempotency_key"]) == (tenant_id, idempotency_key)), None)

    def load(memory_id, tenant_id):
        row = rows.get(memory_id)
        return dict(row) if row is not None and row["tenant_id"] == tenant_id else None

    def update(memory_id, tenant_id, values):
        assert load(memory_id, tenant_id) is not None
        rows[memory_id].update(values)
        return True

    database = SimpleNamespace(
        insert_memory_record=insert, find_by_idempotency=find, get_memory_record=load, update_memory_record=update,
    )
    service = memory_records.MemoryRecordService(index_service=index)
    monkeypatch.setattr(memory_records, "memory_record_db", database)
    monkeypatch.setattr(memory_records, "_resolve_tenant_embedding_model_info", lambda _tenant: model)
    monkeypatch.setattr(memory_provider, "_resolve_tenant_embedding_model_info", lambda _tenant: model)
    monkeypatch.setattr(memory_provider, "get_memory_record_service", lambda: service)
    monkeypatch.setattr(memory_provider, "_fanout_external_ingest", AsyncMock())

    manager = ThreadManager(service_name="model-memory-test", lane_policies={
        lane: LanePolicy(name=lane, max_workers=1, max_queue_size=0, queue_timeout_seconds=0)
        for lane in ("model-tool-io", "background-service", "control-io", "model-embedding")
    })
    payload = {
        "tenant_id": "tenant-a", "user_id": "worker-a", "agent_id": "7", "conversation_id": "42",
        "content": "store memory", "idempotency_key": "store-once",
    }

    def store(values):
        return asyncio.run(memory_provider._backend_store_hook(values))

    manager.start()
    set_default_thread_manager(manager)
    try:
        spec = ManagedTaskSpec(task_name="sdk-memory-tool", owner="test")
        # The sole tool worker waits on the Runtime HTTP response. AgentOS must
        # dispatch the provider call on a different lane.
        stored = await asyncio.wait_for(manager.run("model-tool-io", spec, store, payload), timeout=8)
        assert stored["event"] == "ADD" and stored["indexed"]
        repeated = await asyncio.wait_for(manager.run("model-tool-io", spec, store, payload), timeout=8)
        assert repeated["memory_id"] == stored["memory_id"] and repeated["event"] == "UNCHANGED"
        assert len(rows) == 1 and index.index_record.call_count == 1
        updated = await asyncio.wait_for(manager.run(
            "background-service", ManagedTaskSpec(task_name="api-memory-update", owner="test"),
            service.update_memory, stored["memory_id"], "tenant-a",
            {"content": "updated memory", "updated_by": "writer-a"},
        ), timeout=8)
        assert updated and rows[stored["memory_id"]]["content"] == "updated memory"
        assert index.index_record.call_args.kwargs["embedding"] == [0.1, 0.2]

        model.revision = "stale"
        degraded = await asyncio.wait_for(manager.run("model-tool-io", spec, store, {
            **payload, "content": "persist without vector", "idempotency_key": "degraded",
        }), timeout=8)
        assert degraded["event"] == "ADD" and not degraded["indexed"]
        assert rows[degraded["memory_id"]]["content"] == "persist without vector"
    finally:
        clear_default_thread_manager(manager)
        await manager.shutdown(timeout=3)
