# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""The actual application factory installs the enforced service boundary."""

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from contracts.constants import environment
from contracts.errors.exceptions import TokenExpiredError
from gateway.downstream import internal_tokens
from gateway.downstream.identity import IDENTITY_HEADER, identity_context, sign_identity
from backend.http.server.app_factory import create_app


def test_application_factory_enforces_gateway_identity_and_preserves_health(monkeypatch):
    key = "local-app-boundary-fixture-not-for-deployment"
    monkeypatch.setattr(environment, "GATEWAY_AUTH_ENABLED", True)
    monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", key)
    app = create_app(enable_monitoring=False, gateway_identity_audience="management")

    @app.get("/private")
    async def principal():
        return identity_context.get()

    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 200
        assert client.get("/api/private").status_code == 401
        token = sign_identity({"user_id": "u1", "tenant_id": "t1", "kind": "session"},
                              "management", "GET", "/api/private", b"")
        response = client.get("/api/private", headers={IDENTITY_HEADER: token})
        assert response.status_code == 200 and response.json()["user_id"] == "u1"
        assert identity_context.get() is None


@pytest.mark.parametrize("claim", ["exp", "iat", "scope", "iss", "aud"])
def test_runtime_service_token_requires_explicit_policy_and_time_claims(monkeypatch, claim):
    key = "local-runtime-service-fixture-not-for-deployment"
    monkeypatch.setattr(internal_tokens, "JWT_SECRET", key)
    now = int(time.time())
    claims = {"sub": "u1", "tenant_id": "t1", "iat": now, "exp": now + 60,
              "iss": internal_tokens.INTERNAL_RUNTIME_JWT_ISSUER,
              "aud": internal_tokens.INTERNAL_RUNTIME_JWT_AUDIENCE,
              "scope": internal_tokens.INTERNAL_RUNTIME_JWT_SCOPE}
    claims.pop(claim)
    token = jwt.encode(claims, key, algorithm="HS256")
    with pytest.raises(TokenExpiredError):
        internal_tokens.verify_internal_runtime_jwt("Bearer " + token)


def test_runtime_factory_allows_scoped_service_calls_without_opening_public_routes(monkeypatch):
    from runtime.api.identity_routes import is_runtime_service_request

    key = "runtime-factory-fixture-not-for-deployment"
    monkeypatch.setattr(environment, "GATEWAY_AUTH_ENABLED", True)
    monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", key)
    monkeypatch.setattr(internal_tokens, "JWT_SECRET", key)
    app = create_app(enable_monitoring=False, gateway_identity_audience="runtime",
                     internal_runtime_request=is_runtime_service_request)

    @app.post("/agent-evaluations/internal/run")
    @app.post("/agent/run")
    async def principal():
        return identity_context.get()

    valid = internal_tokens.generate_internal_runtime_jwt("u1", "t1")
    now = int(time.time())
    invalid = jwt.encode({"sub": "u1", "tenant_id": "t1", "iat": now, "exp": now + 60}, key, algorithm="HS256")
    with TestClient(app) as client:
        for credential in (None, invalid):
            headers = {"Authorization": "Bearer " + credential} if credential else {}
            assert client.post("/api/agent-evaluations/internal/run", headers=headers).status_code == 401
        response = client.post("/api/agent-evaluations/internal/run", headers={"Authorization": "Bearer " + valid})
        assert response.status_code == 200
        assert response.json() == {"user_id": "u1", "tenant_id": "t1", "kind": "internal"}
        assert client.post("/api/agent/run", headers={"Authorization": "Bearer " + valid}).status_code == 401
        signed = sign_identity({"user_id": "u1", "tenant_id": "t1", "kind": "session"},
                               "runtime", "POST", "/api/agent/run", b"")
        assert client.post("/api/agent/run", headers={IDENTITY_HEADER: signed}).status_code == 200
        assert identity_context.get() is None
