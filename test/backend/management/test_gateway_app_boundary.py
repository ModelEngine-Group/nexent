# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""The actual application factory installs the enforced service boundary."""

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from contracts.constants import environment
from contracts.errors.exceptions import TokenExpiredError
from infrastructure.security import internal_tokens
from infrastructure.security.gateway_identity import IDENTITY_HEADER, identity_context, sign_identity
from management.utils.app_factory import create_app


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
