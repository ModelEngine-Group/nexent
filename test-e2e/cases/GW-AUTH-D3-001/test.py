# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real Gateway/Management/Runtime protocol path with synthetic persistence.

JWT, lookup service authentication, account policy, middleware and WS forwarding
execute unchanged. Persistence uses synthetic adapters; business/voice execution
uses recording sinks. Full Agent/model execution is intentionally excluded.
"""

import asyncio
from contextlib import asynccontextmanager, contextmanager
import json
import socket
import sys
import threading
import time
from types import SimpleNamespace

import httpx
import jwt
import pytest
import uvicorn
from fastapi import FastAPI, WebSocket
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from contracts.constants import environment
from gateway.application import create_gateway_app
from gateway.security.management_client import lookup_identity
from gateway.configuration import GatewaySettings
from infrastructure.service_identity.gateway import IDENTITY_HEADER, identity_context, sign_identity, sign_lookup
from infrastructure.service_identity.middleware import GatewayIdentityMiddleware
from infrastructure.service_identity.mcp import TenantMCPRouter
from infrastructure.security.identity import sign_delegation
from management.api.identity import gateway_identity as lookup_routes
from nexent.core.concurrency import LanePolicy, ThreadManager


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
                raise RuntimeError("Local auth server startup failed")
            time.sleep(0.02)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive(), "Verification leaked a server thread"


@pytest.mark.stage("D3")
@pytest.mark.case_id("GW-AUTH-D3-001")
@pytest.mark.asyncio
async def test_gateway_authoritative_identity_and_signed_protocol_boundary(monkeypatch):
    secret = "local-gateway-auth-d3-fixture-not-a-deployment-secret"
    monkeypatch.setattr(environment, "JWT_SECRET", secret)
    monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", secret)
    monkeypatch.setattr(environment, "IS_SPEED_MODE", False)
    accounts = {user: {"delete_flag": "N", "token_version": 3, "email": "fixture@example.test"}
                for user in ("u1", "u2", "su")}
    key_record = {"user_id": "u1", "token_id": 7, "delete_flag": "N"}
    membership_queries = []
    empty_tenant_users = set()

    def membership(user):
        membership_queries.append(user)
        if user == "su":
            return {"tenant_id": "", "user_role": "SU", "delete_flag": "N"}
        if user in empty_tenant_users:
            return {"tenant_id": "", "user_role": "USER", "delete_flag": "N"}
        return {"tenant_id": "t1" if user == "u1" else "t2", "user_role": "USER"}

    for name, values in {
        "account": {"get_account": accounts.get},
        "token": {"get_token_by_access_key": lambda key: key_record if key == "fixture-api-key" else None},
        "user_tenant": {"get_user_tenant_by_user_id": membership},
        "cas_session": {"is_cas_session_active": lambda sid: sid == "active-session"},
    }.items():
        monkeypatch.setitem(sys.modules, "management.db.identity." + name, SimpleNamespace(**values))
    manager = ThreadManager(service_name="management-auth-test", lane_policies={
        "control-io": LanePolicy(name="control-io", max_workers=2, max_queue_size=4,
                                 queue_timeout_seconds=1, cancel_grace_seconds=1, shutdown_grace_seconds=2)})
    monkeypatch.setattr(lookup_routes, "config_thread_manager", manager)

    @asynccontextmanager
    async def management_lifespan(app):
        manager.start()
        try:
            yield
        finally:
            result = await manager.shutdown(timeout=2)
            assert result.stuck_execution_ids == ()

    management = FastAPI(root_path="/api", lifespan=management_lifespan)
    management.add_middleware(GatewayIdentityMiddleware, audience="management", required=True)
    management.include_router(lookup_routes.router)
    runtime = FastAPI(root_path="/api")
    runtime.add_middleware(GatewayIdentityMiddleware, audience="runtime", required=True)
    reached = []
    context_checks = []

    class ObserveContext:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            before = identity_context.get()
            try:
                await self.app(scope, receive, send)
            finally:
                if scope["type"] in {"http", "websocket"}:
                    context_checks.append(identity_context.get() is before)

    # Observe the actual server request task after the inner boundary returns.
    management.add_middleware(ObserveContext)
    runtime.add_middleware(ObserveContext)

    @runtime.post("/agent/run")
    async def execute():
        identity = identity_context.get()
        reached.append(("runtime", identity["user_id"]))
        return identity

    @management.get("/nb/v1/agents")
    async def agents():
        identity = identity_context.get()
        reached.append(("northbound", identity["user_id"]))
        return identity

    @management.post("/user/signin")
    async def bootstrap():
        assert identity_context.get() is None
        return {"bootstrap": "reachable"}

    @management.get("/user/current_user_info")
    async def current_user():
        identity = identity_context.get()
        reached.append(("current-user", identity["user_id"]))
        return identity

    @runtime.post("/agent/internal/northbound/run")
    async def dispatch():
        identity = identity_context.get()
        reached.append(("dispatch", identity["user_id"]))
        return identity

    @runtime.websocket("/voice/stt/ws")
    async def voice(ws: WebSocket):
        identity = identity_context.get()
        reached.append(("voice", identity["user_id"]))
        await ws.accept(subprotocol="voice")
        await ws.send_json({"user_id": identity["user_id"]})
        await ws.send_bytes(await ws.receive_bytes())
        await ws.close()

    def credential(user="u1", **overrides):
        now = int(time.time())
        return jwt.encode({"sub": user, "ver": 3, "aud": "authenticated", "iss": environment.JWT_ISSUER,
                           "iat": now, "exp": now + 60, **overrides}, secret, algorithm="HS256")

    with serve(management) as management_url, serve(runtime) as runtime_url:
        # Explicit compatibility provider keeps this existing HTTP protocol Case;
        # GW-AUTH-D3-003 proves the production database provider.
        async def legacy_lookup(query):
            return await lookup_identity(query, edge.state.client, management_url, key=secret)
        edge = create_gateway_app(authentication=True, settings=GatewaySettings(jwt_secret=secret, jwt_issuer=environment.JWT_ISSUER, signing_secret=secret), upstreams={
            "management": management_url, "northbound": management_url, "runtime": runtime_url}, identity_lookup=legacy_lookup)
        with serve(edge) as gateway_url:
            monkeypatch.setattr(environment, "GATEWAY_SERVICE_URL", gateway_url)
            mcp_reached = []

            async def mcp_sink(scope, receive, send):
                principal = identity_context.get()
                mcp_reached.append((principal["user_id"], principal["tenant_id"], scope["path"]))
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": json.dumps(principal).encode()})

            mcp_app = FastAPI()
            mcp_app.mount("/", TenantMCPRouter(get_app=lambda tenant: mcp_sink, refresh=lambda tenant: None,
                                               internal_token="fixture-internal", gateway_required=True))
            mcp_app.add_middleware(ObserveContext)
            with serve(mcp_app) as mcp_url:
                async with httpx.AsyncClient(trust_env=False, timeout=10) as mcp_client:
                    for user, tenant in (("u1", "t1"), ("u2", "t2")):
                        response = await mcp_client.get(mcp_url + f"/mcp/{tenant}/sse?q=1", headers={
                            "Authorization": "Bearer " + credential(user)})
                        assert response.status_code == 200 and response.json()["user_id"] == user
                    baseline_mcp = list(mcp_reached)
                    for tenant, token in (("t2", credential()), ("t1", "invalid"),
                                          ("t1", credential(exp=int(time.time()) - 1))):
                        response = await mcp_client.get(mcp_url + f"/mcp/{tenant}/sse?q=1", headers={
                            "Authorization": "Bearer " + token})
                        assert response.status_code == 403 and mcp_reached == baseline_mcp
                    body = json.dumps({"authorization": "Bearer " + credential(), "method": "GET",
                                       "path": "/mcp/t1/sse", "query": ""}).encode()
                    for headers in ({}, {"x-nexent-service-token": sign_delegation(b"{}", key=secret)}):
                        response = await mcp_client.post(gateway_url + "/internal/credentials/mcp", content=body,
                                                         headers=headers)
                        assert response.status_code == 401 and mcp_reached == baseline_mcp
                    assert mcp_reached == [("u1", "t1", "/sse"), ("u2", "t2", "/sse")]
            membership_queries.clear()
            async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
                # Distinct users traverse actual lookup and audience-specific verification.
                for user in ("u1", "u2"):
                    response = await client.post(gateway_url + "/api/agent/run", headers={
                        "Authorization": "Bearer " + credential(user), IDENTITY_HEADER: "forged"})
                    assert response.status_code == 200 and response.json()["user_id"] == user
                assert membership_queries == ["u1", "u2"]
                from contracts.constants.constants import DEFAULT_TENANT_ID

                response = await client.get(gateway_url + "/api/user/current_user_info", headers={
                    "Authorization": "Bearer " + credential("su")})
                assert response.status_code == 200
                assert (response.json()["user_id"], response.json()["tenant_id"], response.json()["role"]) == (
                    "su", DEFAULT_TENANT_ID, "SU")
                protected_baseline = list(reached)
                empty_tenant_users.add("u2")
                response = await client.get(gateway_url + "/api/user/current_user_info", headers={
                    "Authorization": "Bearer " + credential("u2")})
                assert response.status_code == 401 and reached == protected_baseline
                empty_tenant_users.clear()
                key_record["user_id"] = "su"
                response = await client.get(gateway_url + "/nb/v1/agents", headers={
                    "Authorization": "Bearer fixture-api-key"})
                assert response.status_code == 401 and reached == protected_baseline
                key_record["user_id"] = "u1"
                baseline = list(reached)
                for headers in ({}, {IDENTITY_HEADER: "forged"}):
                    response = await client.post(gateway_url + "/api/agent/run", headers=headers)
                    assert response.status_code == 401
                response = await client.post(runtime_url + "/api/agent/run", headers={"Authorization": "Bearer " + credential()})
                assert response.status_code == 401
                principal = {"user_id": "u1", "tenant_id": "t1", "kind": "session"}
                wrong_service = sign_identity(principal, "management", "POST", "/api/agent/run", b"")
                response = await client.post(runtime_url + "/api/agent/run", headers={IDENTITY_HEADER: wrong_service})
                assert response.status_code == 401 and reached == baseline
                accounts["u1"]["token_version"] = 4
                response = await client.post(gateway_url + "/api/agent/run", headers={"Authorization": "Bearer " + credential()})
                assert response.status_code == 401 and reached == baseline
                accounts["u1"]["token_version"] = 3
                response = await client.post(gateway_url + "/api/agent/run", headers={"Authorization": "Bearer " + credential(sid="revoked")})
                assert response.status_code == 401
                response = await client.get(gateway_url + "/nb/v1/agents", headers={"Authorization": "Bearer fixture-api-key"})
                assert response.status_code == 200 and response.json()["token_id"] == 7
                baseline = list(reached)
                key_record["delete_flag"] = "Y"
                response = await client.get(gateway_url + "/nb/v1/agents", headers={"Authorization": "Bearer fixture-api-key"})
                assert response.status_code == 401 and reached == baseline
                from infrastructure.service_identity import internal_tokens

                monkeypatch.setattr(internal_tokens, "JWT_SECRET", secret)
                response = await client.post(runtime_url + "/api/agent/internal/northbound/run", headers={
                    "Authorization": "Bearer " + internal_tokens.generate_internal_runtime_jwt("u1", "t1")})
                assert response.status_code == 200 and response.json()["kind"] == "internal"
                response = await client.post(runtime_url + "/api/agent/internal/northbound/run", headers={
                    "Authorization": "Bearer " + credential()})
                assert response.status_code == 401
                response = await client.post(gateway_url + "/api/user/signin")
                assert response.status_code == 200
                original_body = b'{"kind":"session","user_id":"u1","token_version":3}'
                response = await client.post(management_url + "/api/internal/identity/resolve", content=b"{}",
                                             headers={"x-nexent-service-token": sign_lookup(original_body)})
                assert response.status_code == 401
                response = await client.post(gateway_url + "/api/internal/identity/resolve", content=original_body)
                assert response.status_code == 404
            ws_url = gateway_url.replace("http:", "ws:") + "/api/voice/stt/ws"
            with pytest.raises(InvalidStatus):
                async with connect(ws_url):
                    pytest.fail("Unsigned WebSocket was accepted")
            async with connect(ws_url, subprotocols=["voice"], additional_headers={
                "Cookie": "nexent_access_token=" + credential("u2")}) as ws:
                assert ws.subprotocol == "voice"
                assert json.loads(await ws.recv()) == {"user_id": "u2"}
                await ws.send(b"audio")
                assert await ws.recv() == b"audio"
                await ws.wait_closed()
                assert ws.close_code == 1000
    assert identity_context.get() is None
    assert context_checks and all(context_checks)
    assert reached == [("runtime", "u1"), ("runtime", "u2"), ("current-user", "su"), ("northbound", "u1"), ("dispatch", "u1"), ("voice", "u2")]
