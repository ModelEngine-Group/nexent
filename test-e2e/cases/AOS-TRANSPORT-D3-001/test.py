# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise real AgentOS HTTP boundaries with a recording execution adapter."""

import asyncio
import json
import socket
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from starlette.responses import StreamingResponse

from contracts.agentos import (
    AgentRunningState, BackgroundAgentResult, CompatibilityOperation, CompatibilityRun, EvaluationAgentResult, EvaluationAgentRun,
)
from contracts.constants import environment
from gateway.downstream.middleware import GatewayIdentityMiddleware
from gateway.security.context import trusted_identity
from infrastructure import agentos_identity
from infrastructure.agentos_identity import ServicePrincipal, sign_call
from management.clients.agentos import AgentOSClient
from runtime.agentos.compatibility import create_background_router, create_compatibility_router
from runtime.agentos.evaluation import create_evaluation_router
from runtime.agentos.middleware import AgentOSMiddleware

_EVENTS = b"id: 1\ndata: first\n\nid: 2\ndata: done\n\n"


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


@pytest.mark.stage("D3")
@pytest.mark.case_id("AOS-TRANSPORT-D3-001")
@pytest.mark.asyncio
async def test_signed_agentos_transport(monkeypatch):
    key = "synthetic-agentos-transport-fixture-secret"
    monkeypatch.setattr(environment, "JWT_SECRET", key)
    monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", key)
    principal = ServicePrincipal("user-a", "tenant-a")
    calls = []

    async def run(payload, actor):
        async def events():
            assert trusted_identity("internal") == {
                "user_id": actor.user_id, "tenant_id": actor.tenant_id, "kind": "internal",
            }
            yield _EVENTS

        calls.append(("run", payload, actor))
        return StreamingResponse(events(), media_type="text/event-stream")

    async def stop(conversation_id, actor):
        calls.append(("stop", conversation_id, actor))
        return {"message": "stopped"}

    case_events = [{"type": "thought", "content": "step"}, {"type": "final_answer", "content": "answer"}]

    async def evaluate(payload, actor):
        calls.append(("evaluate", payload.conversation_id, actor))
        return EvaluationAgentResult(answer="answer", events=case_events)

    started = threading.Event()
    canceled = threading.Event()

    async def background(payload, actor):
        calls.append(("background", payload["conversation_id"], actor))
        if payload["conversation_id"] == 43:
            started.set()
            try:
                await asyncio.sleep(30)
            finally:
                canceled.set()
        return BackgroundAgentResult(conversation_id=42, assistant_message_id=17, chunks=3)

    async def inspect(conversation_id, actor):
        calls.append(("inspect", conversation_id, actor))
        return AgentRunningState(running=True)

    runtime = FastAPI(root_path="/api")
    runtime.add_middleware(GatewayIdentityMiddleware, audience="runtime", required=True)
    runtime.add_middleware(AgentOSMiddleware)
    runtime.include_router(create_compatibility_router(run, stop))
    runtime.include_router(create_evaluation_router(evaluate))
    runtime.include_router(create_background_router(background, inspect))

    with serve(runtime) as runtime_url:
        def client_factory(**kwargs):
            return httpx.AsyncClient(trust_env=False, **kwargs)

        agentos = AgentOSClient(runtime_url, client_factory)
        management = FastAPI()

        @management.post("/run")
        async def management_run():
            return await agentos.run({"conversation_id": 42}, principal.user_id, principal.tenant_id)

        @management.post("/stop")
        async def management_stop():
            return await agentos.stop(42, principal.user_id, principal.tenant_id)

        async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
            with serve(management) as management_url:
                response = await client.post(f"{management_url}/run")
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                assert response.content == _EVENTS
                response = await client.post(f"{management_url}/stop")
                assert response.status_code == 200
                assert response.json() == {"message": "stopped"}

            run_url = f"{runtime_url}/api{CompatibilityOperation.RUN.value}"
            stop_url = f"{runtime_url}/api{CompatibilityOperation.STOP.value}"
            body = CompatibilityRun(request={"conversation_id": 42}).model_dump_json().encode()
            token = sign_call(CompatibilityOperation.RUN, body, principal)
            with monkeypatch.context() as expired_time:
                expired_time.setattr(agentos_identity, "time", SimpleNamespace(time=lambda: time.time() - 120))
                expired = sign_call(CompatibilityOperation.RUN, body, principal)

            for url, payload, credential, status in (
                (run_url, body, None, 401),
                (run_url, body.replace(b"42", b"43"), token, 401),
                (stop_url, body, token, 401),
                (run_url, body, expired, 401),
                (run_url.replace("/v1/", "/v2/"), body, token, 404),
            ):
                headers = {"Authorization": f"Bearer {credential}"} if credential else {}
                result = await client.post(url, content=payload, headers=headers)
                assert result.status_code == status
                assert "conversation_id" not in result.text

            case = EvaluationAgentRun(agent_id=7, version_no=3, query="question", conversation_id=-12)
            result = await agentos.run_evaluation_case(case, principal.user_id, principal.tenant_id)
            assert result.answer == "answer"
            assert result.events == case_events
            invalid = json.dumps(case.model_dump() | {"conversation_id": 42}).encode()
            signed = sign_call(CompatibilityOperation.EVALUATION_CASE, invalid, principal)
            response = await client.post(
                f"{runtime_url}/api{CompatibilityOperation.EVALUATION_CASE.value}",
                content=invalid,
                headers={"Authorization": f"Bearer {signed}"},
            )
            assert response.status_code == 422

            background_result = await agentos.run_background({"conversation_id": 42}, principal.user_id, principal.tenant_id)
            assert background_result.model_dump() == {"conversation_id": 42, "assistant_message_id": 17, "chunks": 3}
            state = await agentos.inspect(42, principal.user_id, principal.tenant_id)
            assert state.running is True
            pending = asyncio.create_task(agentos.run_background(
                {"conversation_id": 43}, principal.user_id, principal.tenant_id,
            ))
            try:
                assert await asyncio.to_thread(started.wait, 5)
            finally:
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            assert await asyncio.to_thread(canceled.wait, 5)

    assert calls == [
        ("run", {"conversation_id": 42}, principal),
        ("stop", 42, principal),
        ("evaluate", -12, principal),
        ("background", 42, principal),
        ("inspect", 42, principal),
        ("background", 43, principal),
    ]
