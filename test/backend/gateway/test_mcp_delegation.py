# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Credential delegation is private, request-bound and tenant-scoped."""

import json
import time
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest

from test.backend.gateway.http_identity_fixture import create_gateway_app
from gateway.configuration import GatewaySettings
from gateway.security.identity import IdentityError, sign_delegation, sign_identity, sign_lookup, verify_identity
from gateway.mcp import identity_router as mcp
from gateway.security.context import identity_context
from gateway.mcp.credential_client import resolve_mcp_identity

KEY = "local-mcp-delegation-fixture-only"
PRINCIPAL = {"user_id": "u1", "tenant_id": "t1", "kind": "session"}
SCOPE = {"type": "http", "method": "GET", "path": "/mcp/t1/sse", "query_string": b"q=1"}


def body(**extra):
    return json.dumps({"authorization": "Bearer user-token", "method": "GET", "path": SCOPE["path"],
                       "query": "713d31", **extra}).encode()


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["missing", "tampered", "lookup-token", "valid", "invalid-session",
                                         "invalid-json", "invalid-path", "invalid-method", "huge", "unavailable",
                                         "expired-signature", "wrong-key", "unicode-header", "duplicate-signature"])
async def test_gateway_delegation_never_skips_service_or_session_authentication(variant):
    now = int(time.time())
    session = jwt.encode({"sub": "u1", "ver": 1, "aud": "authenticated", "iss": "nexent",
                          "iat": now, "exp": now + 60}, KEY, algorithm="HS256")
    data = body(authorization="Bearer " + session)
    if variant == "invalid-session": data = body()
    if variant == "invalid-json": data = b"[]"
    if variant == "invalid-path": data = body(path="/user/signin")
    if variant == "invalid-method": data = body(method="get")
    if variant == "unicode-header": data = body(authorization="Bearer \u4e2d")
    if variant == "huge": data = b" " * 16385
    signed = data if variant != "tampered" else body(path="/mcp/other/sse")
    headers = {"x-nexent-service-token": (sign_lookup if variant == "lookup-token" else sign_delegation)(signed, key=KEY)}
    if variant == "missing": headers = {}
    if variant == "wrong-key": headers = {"x-nexent-service-token": sign_delegation(data, key=KEY + "bad")}
    if variant == "expired-signature":
        claims = jwt.decode(headers["x-nexent-service-token"], options={"verify_signature": False})
        claims.update(iat=now - 60, exp=now - 30)
        headers = {"x-nexent-service-token": jwt.encode(claims, KEY, algorithm="HS256")}
    if variant == "duplicate-signature": headers = list(headers.items()) * 2
    calls = []

    async def upstream(request):
        calls.append(request.url.path)
        return httpx.Response(503 if variant == "unavailable" else 200, json=PRINCIPAL)

    app = create_gateway_app(settings=GatewaySettings(jwt_secret=KEY, signing_secret=KEY),
                             authentication=False, transport=httpx.MockTransport(upstream))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
            response = await client.post("/internal/credentials/mcp", content=data, headers=headers)
    assert response.status_code == (200 if variant == "valid" else 503 if variant == "unavailable" else 401)
    assert calls == (["/api/internal/identity/resolve"] if variant in {"valid", "unavailable"} else [])
    if variant == "valid":
        assert verify_identity(response.json()["identity_token"], "mcp", "GET", SCOPE["path"], b"q=1", key=KEY) == PRINCIPAL


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["valid", "audience", "method", "path", "query", "missing", "down", "bad-json"])
async def test_mcp_client_verifies_response_binding_and_closes_client(variant):
    audience = "management" if variant == "audience" else "mcp"
    token = sign_identity(PRINCIPAL, audience, "POST" if variant == "method" else "GET",
                          "/mcp/other/sse" if variant == "path" else SCOPE["path"],
                          b"q=2" if variant == "query" else b"q=1", key=KEY)
    closed = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"bad" if variant == "bad-json" else json.dumps({} if variant == "missing" else {"identity_token": token}).encode()

        async def aclose(self):
            closed.append(True)

    def transport(request):
        from gateway.security.identity import verify_delegation

        verify_delegation(request.headers["x-nexent-service-token"], request.content, key=KEY)
        assert json.loads(request.content)["path"] == SCOPE["path"]
        return httpx.Response(503 if variant == "down" else 200, stream=Stream())

    if variant == "valid":
        assert await resolve_mcp_identity(SCOPE, "Bearer test", gateway_url="http://gateway", key=KEY,
                                          transport=httpx.MockTransport(transport)) == PRINCIPAL
    else:
        with pytest.raises(IdentityError):
            await resolve_mcp_identity(SCOPE, "Bearer test", gateway_url="http://gateway", key=KEY,
                                       transport=httpx.MockTransport(transport))
    assert closed == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["valid", "tenant", "error", "duplicate", "app-error"])
async def test_mcp_router_uses_delegated_identity_and_restores_context(monkeypatch, variant):
    principal = {**PRINCIPAL, "tenant_id": "t2" if variant == "tenant" else "t1"}
    resolver = AsyncMock(return_value=principal, side_effect=IdentityError() if variant == "error" else None)
    reached, sent = [], []

    async def sink(scope, receive, send):
        reached.append((identity_context.get(), scope["path"]))
        if variant == "app-error": raise RuntimeError("sink failed")
        await send({"type": "http.response.start", "status": 200})

    router = mcp.TenantMCPRouter(get_app=lambda tenant: sink, refresh=lambda tenant: None,
                                internal_token="internal", gateway_required=True, resolve_identity=resolver,
                                legacy_identity=lambda value: pytest.fail("Local external auth was called"))
    scope = {**SCOPE, "headers": [(b"authorization", b"Bearer test")] * (2 if variant == "duplicate" else 1)}
    parent = identity_context.set({"parent": True})
    try:
        if variant == "app-error":
            with pytest.raises(RuntimeError, match="sink failed"):
                await router(scope, None, AsyncMock(side_effect=sent.append))
        else:
            await router(scope, None, AsyncMock(side_effect=sent.append))
            assert sent[0]["status"] == (200 if variant == "valid" else 403)
        assert reached == ([(principal, "/sse")] if variant in {"valid", "app-error"} else [])
        assert identity_context.get() == {"parent": True}
        assert resolver.await_count == (0 if variant == "duplicate" else 1)
    finally:
        identity_context.reset(parent)
