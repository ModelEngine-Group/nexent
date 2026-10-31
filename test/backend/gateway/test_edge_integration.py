# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real local HTTP/SSE/WS verification, separate from isolated unit proof."""

import asyncio
import socket
import threading
import time
from contextlib import contextmanager

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import StreamingResponse
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosedError

from gateway.edge import create_edge_app


@contextmanager
def serve(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Local verification server did not start")
            time.sleep(0.02)
        yield port
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()


@pytest.mark.local_only
@pytest.mark.asyncio
async def test_real_http_sse_and_websocket():
    upstream = FastAPI()

    @upstream.post("/api/agent/run")
    async def events():
        async def stream():
            yield b"id: 1\ndata: first\n\n"
            await asyncio.sleep(0.1)
            yield b"id: 2\ndata: last\n\n"
        return StreamingResponse(stream(), media_type="text/event-stream")

    @upstream.websocket("/api/voice/stt/ws")
    async def echo(ws: WebSocket):
        await ws.accept(subprotocol="voice")
        await ws.send_text(await ws.receive_text())
        await ws.send_bytes(await ws.receive_bytes())
        await ws.close(code=1000)

    with serve(upstream) as upstream_port:
        origin = f"http://127.0.0.1:{upstream_port}"
        edge = create_edge_app(upstreams=dict.fromkeys(["runtime", "management", "northbound"], origin))
        with serve(edge) as edge_port:
            async with httpx.AsyncClient(trust_env=False) as client:
                async with client.stream("POST", f"http://127.0.0.1:{edge_port}/api/agent/run") as response:
                    chunks = response.aiter_bytes()
                    assert await anext(chunks) == b"id: 1\ndata: first\n\n"
                    assert await anext(chunks) == b"id: 2\ndata: last\n\n"
            async with connect(f"ws://127.0.0.1:{edge_port}/api/voice/stt/ws", subprotocols=["voice"]) as ws:
                assert ws.subprotocol == "voice"
                await ws.send("hello")
                assert await ws.recv() == "hello"
                await ws.send(b"audio")
                assert await ws.recv() == b"audio"
                await ws.wait_closed()
                assert ws.close_code == 1000


async def wait_closed(event):
    deadline = time.monotonic() + 3
    while not event.is_set() and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    assert event.is_set(), "Upstream connection was not reclaimed"


@pytest.mark.local_only
@pytest.mark.asyncio
async def test_sse_client_disconnect_closes_upstream():
    upstream = FastAPI()
    closed = threading.Event()

    @upstream.post("/api/agent/run")
    async def events():
        async def stream():
            try:
                yield b"data: first\n\n"
                await asyncio.Event().wait()
            finally:
                closed.set()
        return StreamingResponse(stream(), media_type="text/event-stream")

    with serve(upstream) as upstream_port:
        origin = f"http://127.0.0.1:{upstream_port}"
        edge = create_edge_app(authentication=False, upstreams=dict.fromkeys(["runtime", "management", "northbound"], origin))
        with serve(edge) as edge_port:
            async with httpx.AsyncClient(trust_env=False) as client:
                async with client.stream("POST", f"http://127.0.0.1:{edge_port}/api/agent/run") as response:
                    assert await anext(response.aiter_bytes()) == b"data: first\n\n"
                await wait_closed(closed)


@pytest.mark.local_only
@pytest.mark.asyncio
@pytest.mark.parametrize("disconnect_side", ["client", "upstream"])
async def test_websocket_abrupt_disconnect_reclaims_peer(disconnect_side):
    upstream = FastAPI()
    closed = threading.Event()

    @upstream.websocket("/api/voice/stt/ws")
    async def voice(ws: WebSocket):
        await ws.accept()
        try:
            await ws.send_text("ready")
            if disconnect_side == "upstream":
                await ws.close(code=1011)
            else:
                message = await ws.receive()
                assert message["type"] == "websocket.disconnect"
        finally:
            closed.set()

    with serve(upstream) as upstream_port:
        origin = f"http://127.0.0.1:{upstream_port}"
        edge = create_edge_app(authentication=False, upstreams=dict.fromkeys(["runtime", "management", "northbound"], origin))
        with serve(edge) as edge_port:
            async with connect(f"ws://127.0.0.1:{edge_port}/api/voice/stt/ws") as ws:
                assert await ws.recv() == "ready"
                if disconnect_side == "client":
                    ws.transport.abort()
                    await asyncio.wait_for(ws.wait_closed(), timeout=3)
                else:
                    with pytest.raises(ConnectionClosedError):
                        await asyncio.wait_for(ws.recv(), timeout=3)
                    assert ws.close_code == 1011
            await wait_closed(closed)
