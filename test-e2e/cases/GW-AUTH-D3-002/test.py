# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Actual Gateway and two upstream listeners; business execution is recorded."""

import asyncio
from contextlib import contextmanager
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import StreamingResponse
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from gateway.application import create_gateway_app


@contextmanager
def serve(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, lifespan="on", log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Local exposure server startup failed")
            time.sleep(0.02)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive(), "Exposure verification leaked a server thread"


@pytest.mark.stage("D3")
@pytest.mark.case_id("GW-AUTH-D3-002")
@pytest.mark.asyncio
async def test_gateway_exposure_network_boundary():
    management, runtime = FastAPI(), FastAPI()
    reached, closed = [], []

    @management.get("/api/model/list")
    async def models(request: Request):
        reached.append(("management", request.url.path, request.scope["query_string"]))
        return {"service": "management"}

    async def web_operation(request: Request):
        service = "management"
        reached.append((service, request.url.path, request.scope["query_string"]))
        return {"service": service, "method": request.method, "body": (await request.body()).decode()}

    management.add_api_route("/api/users/{user_id}/assignable_roles", web_operation, methods=["GET"])
    management.add_api_route("/api/conversation/creator_histories", web_operation, methods=["GET"])
    management.add_api_route("/api/conversation/{conversation_id}/creation_mode_responses", web_operation, methods=["POST"])
    management.add_api_route("/api/conversation/{conversation_id}/target", web_operation, methods=["PATCH"])
    management.add_api_route("/api/conversation/branch", web_operation, methods=["POST"])
    management.add_api_route("/api/conversation/{conversation_id}/model_preferences", web_operation, methods=["GET", "PATCH"])
    management.add_api_route("/api/conversation/{conversation_id}/model_preferences/{model_id}", web_operation, methods=["GET", "PATCH"])

    @management.get("/nb/v1/agents")
    async def northbound():
        reached.append(("northbound", "/nb/v1/agents", b""))
        return {"service": "northbound"}

    @management.post("/api/agent/run")
    async def execute(request: Request):
        assert await request.body() == b'{"input":"fixture"}'
        reached.append(("management", request.url.path, request.scope["query_string"]))

        async def stream():
            try:
                yield b"data: first\n\n"
                await asyncio.Event().wait()
            finally:
                closed.append("sse")

        return StreamingResponse(stream(), media_type="text/event-stream")

    @runtime.websocket("/api/voice/stt/ws")
    async def voice(ws: WebSocket):
        reached.append(("runtime", "/api/voice/stt/ws", b""))
        await ws.accept(subprotocol="voice")
        try:
            await ws.send_bytes(await ws.receive_bytes())
            await ws.close()
        finally:
            closed.append("ws")

    with serve(management) as management_url, serve(runtime) as runtime_url:
        edge = create_gateway_app(authentication=False, upstreams={
            "management": management_url, "runtime": runtime_url, "northbound": management_url})
        with serve(edge) as gateway_url:
            async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
                response = await client.get(gateway_url + "/api/model/list?q=a%2Fb&q=2")
                assert response.status_code == 200 and response.json() == {"service": "management"}
                operations = [
                    ("GET", "/api/users/member/assignable_roles", "management", b""),
                    ("POST", "/api/conversation/42/creation_mode_responses", "management", b'{"mode":"agent_create"}'),
                    ("GET", "/api/conversation/creator_histories", "management", b""),
                    ("PATCH", "/api/conversation/42/target", "management", b'{"kind":"agent","id":7}'),
                    ("POST", "/api/conversation/branch", "management", b'{"source_conversation_id":42}'),
                    ("GET", "/api/conversation/42/model_preferences", "management", b""),
                    ("PATCH", "/api/conversation/42/model_preferences", "management", b'{"model_id":7}'),
                    ("GET", "/api/conversation/42/model_preferences/7", "management", b""),
                    ("PATCH", "/api/conversation/42/model_preferences/7", "management", b'{"temperature":0.5}'),
                ]
                for method, path, target, body in operations:
                    response = await client.request(method, gateway_url + path + "?check=a%2Fb&check=2", content=body)
                    assert response.status_code == 200
                    assert response.json() == {"service": target, "method": method, "body": body.decode()}
                    assert reached[-1] == (target, path, b"check=a%2Fb&check=2")
                response = await client.get(gateway_url + "/nb/v1/agents")
                assert response.status_code == 200 and response.json() == {"service": "northbound"}
                async with client.stream("POST", gateway_url + "/api/agent/run?q=x%2Fy&q=2",
                                         content=b'{"input":"fixture"}') as response:
                    assert response.status_code == 200
                    assert await anext(response.aiter_bytes()) == b"data: first\n\n"
                baseline = list(reached)
                for method, path in [("GET", "/api/newly-added-backend-route"),
                                     ("POST", "/api/model/list"), ("GET", "/nb/v1/chat/run"),
                                     ("POST", "/api/agent/internal/northbound/run"),
                                     ("GET", "/api/internal/thread-capacity"), ("GET", "/api/voice/stt/ws")]:
                    assert (await client.request(method, gateway_url + path)).status_code == 404
                    assert reached == baseline
            with pytest.raises(InvalidStatus):
                async with connect(gateway_url.replace("http:", "ws:") + "/api/model/list"):
                    pytest.fail("An HTTP route implicitly authorized WebSocket")
            assert reached == baseline
            async with connect(gateway_url.replace("http:", "ws:") + "/api/voice/stt/ws",
                               subprotocols=["voice"]) as ws:
                assert ws.subprotocol == "voice"
                await ws.send(b"audio")
                assert await ws.recv() == b"audio"
                await ws.wait_closed()
                assert ws.close_code == 1000
            for _ in range(100):
                if sorted(closed) == ["sse", "ws"]:
                    break
                await asyncio.sleep(0.02)
            assert sorted(closed) == ["sse", "ws"]
    assert reached == [("management", "/api/model/list", b"q=a%2Fb&q=2"),
                       *((target, path, b"check=a%2Fb&check=2") for _, path, target, _ in operations),
                       ("northbound", "/nb/v1/agents", b""),
                       ("management", "/api/agent/run", b"q=x%2Fy&q=2"),
                       ("runtime", "/api/voice/stt/ws", b"")]
