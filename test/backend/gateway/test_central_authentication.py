# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Gateway validation and downstream context isolation with controlled upstreams."""

import asyncio
import json
import time

import httpx
import jwt
import pytest
from fastapi import FastAPI

from contracts.constants import environment
from gateway.edge import create_edge_app
from infrastructure.security.gateway_identity import (
    IDENTITY_HEADER, IdentityError, identity_context, sign_identity, verify_identity, verify_lookup,
)
from infrastructure.security.identity_middleware import GatewayIdentityMiddleware

KEY = "local-central-auth-fixture-not-for-deployment"


@pytest.fixture
def auth_config(monkeypatch):
    monkeypatch.setattr(environment, "JWT_SECRET", KEY)
    monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", KEY)
    monkeypatch.setattr(environment, "IS_SPEED_MODE", False)


def session(user="u1", key=KEY, **extra):
    now = int(time.time())
    return jwt.encode({"sub": user, "ver": 3, "iss": environment.JWT_ISSUER,
                       "aud": "authenticated", "iat": now, "exp": now + 60, **extra}, key, algorithm="HS256")


@pytest.mark.asyncio
async def test_gateway_overwrites_spoofed_identity_and_resolves_current_state(auth_config):
    requests = []

    async def upstream(request):
        requests.append(request)
        if request.url.path == "/api/internal/identity/resolve":
            body = await request.aread()
            verify_lookup(request.headers["x-nexent-service-token"], body)
            query = json.loads(body)
            return httpx.Response(200, json={"user_id": query.get("user_id", "key-user"), "tenant_id": "t1",
                                            "kind": query["kind"], "role": "USER", "language": "zh"})
        principal = verify_identity(request.headers[IDENTITY_HEADER], "management", request.method,
                                    request.url.path, request.url.query)
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(principal).encode()))

    app = create_edge_app(authentication=True, transport=httpx.MockTransport(upstream))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://edge") as client:
            response = await client.get("/api/users/list", headers={"Authorization": "bearer\t" + session(), IDENTITY_HEADER: "spoofed"})
            assert response.status_code == 200 and response.json()["user_id"] == "u1"
            response = await client.get("/nb/v1/agents", headers={"Authorization": "opaque-key"})
            assert response.status_code == 200 and response.json()["user_id"] == "key-user"
    assert len(requests) == 4
    assert requests[1].headers[IDENTITY_HEADER] != "spoofed"


@pytest.mark.asyncio
@pytest.mark.parametrize("credential", [None, "malformed", "wrong-signature", "pending", "wrong-audience"])
async def test_rejected_credentials_never_reach_lookup_or_business(auth_config, credential):
    calls = []

    async def upstream(request):
        calls.append(request)
        raise AssertionError("Rejected credential reached upstream")

    headers = {}
    if credential == "malformed": headers["Authorization"] = "Bearer a b"
    if credential == "wrong-signature": headers["Authorization"] = "Bearer " + session(key=KEY + "bad")
    if credential == "pending": headers["Authorization"] = "Bearer " + session(purpose="pending-oauth")
    if credential == "wrong-audience": headers["Authorization"] = "Bearer " + session(aud="runtime")
    app = create_edge_app(authentication=True, transport=httpx.MockTransport(upstream))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://edge") as client:
            response = await client.get("/api/users/list", headers=headers)
    assert response.status_code == 401
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(401, 401), (403, 401), (500, 503), (502, 503)])
async def test_identity_rejection_or_unavailability_never_reaches_business(auth_config, status, expected):
    calls = []

    async def upstream(request):
        calls.append(request.url.path)
        return httpx.Response(status, json={"secret": "must not be reflected"})

    app = create_edge_app(authentication=True, transport=httpx.MockTransport(upstream))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://edge") as client:
            response = await client.get("/api/users/list", headers={"Authorization": "Bearer " + session()})
    assert response.status_code == expected
    assert "secret" not in response.text
    assert calls == ["/api/internal/identity/resolve"]


@pytest.mark.asyncio
async def test_downstream_rejects_unsigned_and_cross_service_tokens_and_resets_context(auth_config):
    app = FastAPI()
    app.add_middleware(GatewayIdentityMiddleware, audience="management", required=True)

    @app.get("/private")
    async def principal():
        await asyncio.sleep(0.01)
        return identity_context.get()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://management") as client:
        for user in ("u1", "u2"):
            identity = {"user_id": user, "tenant_id": "t1", "kind": "session"}
            token = sign_identity(identity, "management", "GET", "/private", b"")
            response = await client.get("/private", headers={IDENTITY_HEADER: token})
            assert response.json()["user_id"] == user
            assert identity_context.get() is None
        response = await client.get("/private", headers={"Authorization": "Bearer " + session()})
        assert response.status_code == 401
        response = await client.get("/private", headers={IDENTITY_HEADER: sign_identity(identity, "runtime", "GET", "/private", b"")})
        assert response.status_code == 401
        responses = await asyncio.gather(*[
            client.get("/private", headers={IDENTITY_HEADER: sign_identity(
                {"user_id": user, "tenant_id": "t1", "kind": "session"}, "management", "GET", "/private", b"")})
            for user in ("u3", "u4")
        ])
        assert [response.json()["user_id"] for response in responses] == ["u3", "u4"]
        assert identity_context.get() is None


@pytest.mark.asyncio
async def test_login_and_cors_preflight_require_no_existing_user(auth_config):
    seen = []

    async def upstream(request):
        assert request.url.path == "/api/user/signin"
        assert verify_identity(request.headers[IDENTITY_HEADER], "management", "POST", request.url.path, b"") is None
        seen.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(b"login result"))

    app = create_edge_app(authentication=True, transport=httpx.MockTransport(upstream))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://edge") as client:
            response = await client.post("/api/user/signin")
            assert response.status_code == 200
            response = await client.options("/api/private", headers={"origin": "https://web.test", "access-control-request-method": "POST"})
            assert response.status_code == 200
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_enabled_gateway_fails_startup_without_signing_configuration(monkeypatch):
    monkeypatch.setattr(environment, "JWT_SECRET", "")
    monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", "")
    app = create_edge_app(authentication=True)
    with pytest.raises(IdentityError, match="not configured"):
        async with app.router.lifespan_context(app):
            pytest.fail("Gateway started without signing configuration")


def test_compatibility_identity_helpers_consume_context_without_credential_queries(monkeypatch):
    from contracts.authentication import CredentialKind
    from contracts.errors.exceptions import TokenExpiredError
    from gateway.authentication import auth

    def forbidden(*args, **kwargs):
        raise AssertionError("Business helper revalidated external credentials")

    monkeypatch.setattr(auth, "_decode_jwt_token", forbidden)
    monkeypatch.setattr(auth, "get_user_tenant_by_user_id", forbidden)
    token = identity_context.set({"user_id": "u1", "tenant_id": "t1", "role": "ADMIN",
                                  "language": "en", "email": "fixture@example.test", "kind": "session"})
    try:
        assert auth.get_current_user_id(None) == ("u1", "t1")
        assert auth.get_current_user_context(None) == ("u1", "t1", "ADMIN")
        assert auth.get_current_user_info(None) == ("u1", "t1", "en")
        valid, user = auth.validate_token(None)
        assert valid and user.id == "u1" and user.email == "fixture@example.test"
        with pytest.raises(TokenExpiredError):
            auth.authenticate_identity(None, kind=CredentialKind.API_KEY)
    finally:
        identity_context.reset(token)


@pytest.mark.asyncio
async def test_frontend_root_user_probe_and_cookie_transport_remain_compatible(auth_config):
    calls = []

    async def upstream(request):
        calls.append(request.url.path)
        if request.url.path == "/api/internal/identity/resolve":
            verify_lookup(request.headers["x-nexent-service-token"], await request.aread())
            return httpx.Response(200, json={"user_id": "u1", "tenant_id": "t1", "kind": "session"})
        assert request.url.path == "/user/current_user_info"
        principal = verify_identity(request.headers[IDENTITY_HEADER], "management", "GET", request.url.path, b"")
        if principal:
            assert request.headers["authorization"] == "Bearer " + cookie
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(principal).encode()))

    cookie = session()
    app = create_edge_app(authentication=True, transport=httpx.MockTransport(upstream))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://edge") as client:
            response = await client.get("/user/current_user_info")
            assert response.status_code == 200 and response.json() is None
            response = await client.get("/user/current_user_info", headers={"Cookie": "nexent_access_token=" + cookie})
            assert response.status_code == 200 and response.json()["user_id"] == "u1"
    assert calls == ["/user/current_user_info", "/api/internal/identity/resolve", "/user/current_user_info"]
