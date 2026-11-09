# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real PostgreSQL and real signed Gateway HTTP/WS; no Management lookup hop."""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time

import asyncpg
import httpx
import jwt
import pytest
from psycopg2 import sql
from sqlalchemy import text
import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import StreamingResponse
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test-e2e/infra/automation"))
from gateway_database import isolated_identity_database
from contracts.constants import environment
from gateway.application import create_gateway_app
from gateway.configuration import load_settings
from infrastructure.security.identity import sign_delegation, verify_identity
from infrastructure.service_identity.gateway import identity_context
from infrastructure.service_identity.middleware import GatewayIdentityMiddleware


@contextmanager
def serve(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, lifespan="on", log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Gateway DB verification startup failed")
            time.sleep(.02)
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()


@pytest.mark.stage("D3")
@pytest.mark.case_id("GW-AUTH-D3-003")
@pytest.mark.asyncio
async def test_gateway_database_identity_protocol(monkeypatch):
    admin_dsn = os.environ.get("NEXENT_GATEWAY_TEST_ADMIN_DSN")
    if not admin_dsn:
        raise RuntimeError("Disposable local PostgreSQL admin DSN is required")
    secret = "gateway-db-fixture-not-a-deployment-secret"
    monkeypatch.setattr(environment, "JWT_SECRET", secret)
    monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", secret)
    management, runtime = FastAPI(), FastAPI()
    management.add_middleware(GatewayIdentityMiddleware, audience="management", required=True)
    runtime.add_middleware(GatewayIdentityMiddleware, audience="runtime", required=True)
    reached, lookup_calls, closed = [], [], []

    @management.post("/api/internal/identity/resolve")
    async def forbidden_lookup():
        lookup_calls.append(True)
        pytest.fail("Gateway silently fell back to Management lookup")

    @management.get("/api/user/current_user_info")
    @management.get("/nb/v1/agents")
    async def identity():
        principal = identity_context.get()
        reached.append(principal)
        return principal

    @runtime.post("/api/agent/run")
    async def execute():
        reached.append(identity_context.get())
        async def stream():
            try: yield b"data: first\n\n"
            finally: closed.append("sse")
        return StreamingResponse(stream(), media_type="text/event-stream")

    @runtime.websocket("/api/voice/stt/ws")
    async def voice(ws: WebSocket):
        principal = identity_context.get()
        reached.append(principal)
        await ws.accept(subprotocol="voice")
        await ws.send_json(principal)
        await ws.send_bytes(await ws.receive_bytes())
        await ws.close()
        closed.append("ws")

    def session(user="u1", **extra):
        now = int(time.time())
        return jwt.encode({"sub": user, "ver": 3, "iss": environment.JWT_ISSUER, "aud": "authenticated",
                           "iat": now, "exp": now + 120, **extra}, secret, algorithm="HS256")

    with isolated_identity_database(admin_dsn) as db:
        connection = await asyncpg.connect(**{k: db[k] for k in ("host", "port", "database", "user", "password")})
        try:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute("UPDATE nexent.user_account_t SET token_version=9")
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.fetch("SELECT password_hash FROM nexent.user_account_t")
        finally:
            await connection.close()
        with serve(management) as management_url, serve(runtime) as runtime_url:
            settings_env = {"JWT_SECRET": secret, "GATEWAY_SIGNING_SECRET": secret,
                "JWT_ISSUER": environment.JWT_ISSUER, "POSTGRES_HOST": db["host"], "POSTGRES_PORT": str(db["port"]),
                "POSTGRES_DB": db["database"], "POSTGRES_USER": db["user"], "NEXENT_POSTGRES_PASSWORD": db["password"]}
            edge = create_gateway_app(settings=load_settings(settings_env), upstreams={
                "management": management_url, "runtime": runtime_url, "northbound": management_url})
            with serve(edge) as gateway_url:
                async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
                    async def current(token):
                        return await client.get(gateway_url + "/api/user/current_user_info",
                                                headers={"Authorization": "Bearer " + token})
                    for user, tenant in [("u1", "t1"), ("u2", "t2"), ("su", "tenant_id"), ("owner", "asset_owner_tenant_id")]:
                        response = await current(session(user))
                        assert response.status_code == 200 and response.json()["tenant_id"] == tenant
                        assert response.json()["user_id"] == user
                    response = await client.get(gateway_url + "/nb/v1/agents", headers={"Authorization": "Bearer fixture-api-key"})
                    assert response.status_code == 200 and response.json()["kind"] == "api_key"
                    assert (await current(session(sid="active"))).status_code == 200
                    for token in ["invalid", session(sid="other-user"), session(sid="missing"), session(ver=2),
                                  session(exp=int(time.time()) - 1), session(sid={"bad": "type"})]:
                        baseline = len(reached)
                        assert (await current(token)).status_code == 401 and len(reached) == baseline
                    changes = [
                        ("UPDATE nexent.user_account_t SET token_version=4 WHERE user_id='u1'", "UPDATE nexent.user_account_t SET token_version=3 WHERE user_id='u1'", session()),
                        ("UPDATE nexent.user_account_t SET delete_flag='Y' WHERE user_id='u1'", "UPDATE nexent.user_account_t SET delete_flag='N' WHERE user_id='u1'", session()),
                        ("UPDATE nexent.user_tenant_t SET delete_flag='Y' WHERE user_id='u1'", "UPDATE nexent.user_tenant_t SET delete_flag='N' WHERE user_id='u1'", session()),
                        ("UPDATE nexent.user_cas_session_t SET status='revoked' WHERE session_id='active'", "UPDATE nexent.user_cas_session_t SET status='active' WHERE session_id='active'", session(sid="active")),
                        ("UPDATE nexent.user_cas_session_t SET expires_at=timestamp '2000-01-01' WHERE session_id='active'", "UPDATE nexent.user_cas_session_t SET expires_at=timestamp '2099-01-01' WHERE session_id='active'", session(sid="active")),
                    ]
                    for mutate, restore, token in changes:
                        with db["engine"].begin() as owner: owner.execute(text(mutate))
                        baseline = len(reached)
                        assert (await current(token)).status_code == 401 and len(reached) == baseline
                        with db["engine"].begin() as owner: owner.execute(text(restore))
                        assert (await current(token)).status_code == 200
                    with db["engine"].begin() as owner:
                        owner.execute(text("UPDATE nexent.user_token_info_t SET delete_flag='Y'"))
                    baseline = len(reached)
                    assert (await client.get(gateway_url + "/nb/v1/agents", headers={"Authorization": "Bearer fixture-api-key"})).status_code == 401
                    assert len(reached) == baseline
                    body = json.dumps({"authorization": "Bearer " + session(), "method": "GET", "path": "/mcp/t1/sse", "query": ""}).encode()
                    response = await client.post(gateway_url + "/internal/credentials/mcp", content=body,
                                                headers={"x-nexent-service-token": sign_delegation(body, key=secret)})
                    assert response.status_code == 200
                    assert verify_identity(response.json()["identity_token"], "mcp", "GET", "/mcp/t1/sse", b"", key=secret)["user_id"] == "u1"
                    response = await client.post(gateway_url + "/api/agent/run", headers={"Authorization": "Bearer " + session()})
                    assert response.content == b"data: first\n\n"
                    async with connect(gateway_url.replace("http:", "ws:") + "/api/voice/stt/ws", subprotocols=["voice"],
                                       additional_headers={"Cookie": "nexent_access_token=" + session("u2")}) as ws:
                        assert json.loads(await ws.recv())["user_id"] == "u2"
                        await ws.send(b"audio")
                        assert await ws.recv() == b"audio"
                        await ws.wait_closed()
                        assert ws.close_code == 1000 and ws.subprotocol == "voice"
                    with db["admin"].cursor() as owner:
                        owner.execute(sql.SQL("ALTER ROLE {} NOLOGIN").format(sql.Identifier(db["user"])))
                        owner.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename=%s AND datname=%s", (db["user"], db["database"]))
                    baseline = len(reached)
                    response = await current(session())
                    assert response.status_code == 503 and "password" not in response.text
                    assert len(reached) == baseline and lookup_calls == []
                    with db["admin"].cursor() as owner:
                        owner.execute(sql.SQL("ALTER ROLE {} LOGIN").format(sql.Identifier(db["user"])))
                    assert (await current(session())).status_code == 200
                assert closed == ["sse", "ws"] and lookup_calls == []
            with db["admin"].cursor() as owner:
                owner.execute("SELECT count(*) FROM pg_stat_activity WHERE usename=%s AND datname=%s", (db["user"], db["database"]))
                assert owner.fetchone()[0] == 0
