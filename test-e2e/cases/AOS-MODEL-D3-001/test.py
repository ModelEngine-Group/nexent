# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify the signed model API and SDK dispatch to a controlled provider."""

import json
import socket
import threading
import time
from contextlib import contextmanager

import httpx
import pytest
from pydantic import BaseModel
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from contracts.agentos import ChatInvocation, ChatMessage, EmbeddingInvocation, ModelAdministrationOperation
from contracts.constants import environment
from contracts.model_administration import ModelHealthcheck, ModelRegistration
from contracts.errors.exceptions import RuntimeUpstreamError
from gateway.downstream.middleware import GatewayIdentityMiddleware
from management.clients.agentos import AgentOSClient
from nexent.core.concurrency import shutdown_fallback_thread_manager
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
            return record if (model_id, tenant_id) == (11, "tenant-a") else None

        records = {}

        def insert(model, user_id, tenant_id):
            records[(tenant_id, model["display_name"])] = {**model, "model_id": 12, "created_by": user_id}
            return True

        def created_ids(names, tenant, model_type):
            return {records[(tenant, name)]["model_id"] for name in names}

        def load_saved(name, tenant_id, model_type):
            return records.get((tenant_id, name))

        checked_keys = []

        async def probe_saved(*args, **kwargs):
            checked_keys.append(args[3])
            return True

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

    assert set(records) == {("tenant-a", "new-model")}
    assert checked_keys == ["test-registration-key"]
    assert len(calls) == 1
    authorization, provider_input = calls[0]
    assert authorization == "Bearer provider-secret"
    assert provider_input["model"] == "test-model"
    assert provider_input["messages"][-1]["content"] == "verify model"
