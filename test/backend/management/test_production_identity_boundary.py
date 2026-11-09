# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Enabled downstream services never fall back to external credential checks."""

import pytest

from contracts.constants import environment
from contracts.errors.exceptions import TokenExpiredError
from gateway.security.context import identity_context
from management.services.permission.identity import northbound as api_key, session as session


@pytest.mark.parametrize("kind", ["session", "api_key"])
def test_enabled_downstream_requires_gateway_principal_before_credential_lookup(monkeypatch, kind):
    calls = []
    monkeypatch.setattr(environment, "GATEWAY_AUTH_ENABLED", True)
    monkeypatch.setattr(session, "IS_SPEED_MODE", False)

    def forbidden(*args):
        calls.append(args)
        raise TokenExpiredError("Legacy external verification was invoked")

    monkeypatch.setattr(session, "_decode_jwt_token", forbidden)
    monkeypatch.setattr(api_key, "get_user_and_tenant_by_access_key", forbidden)
    token = identity_context.set(None)
    try:
        with pytest.raises(TokenExpiredError):
            if kind == "session":
                session.get_current_user_id("Bearer untrusted-external-token")
            else:
                api_key.authenticate_api_key("Bearer untrusted-api-key")
    finally:
        identity_context.reset(token)
    assert calls == []


@pytest.mark.parametrize("kind", ["session", "api_key"])
def test_enabled_downstream_consumes_verified_principal_without_external_checks(monkeypatch, kind):
    monkeypatch.setattr(environment, "GATEWAY_AUTH_ENABLED", True)

    def forbidden(*args):
        pytest.fail("Verified request attempted external credential validation")

    monkeypatch.setattr(session, "_decode_jwt_token", forbidden)
    monkeypatch.setattr(api_key, "get_user_and_tenant_by_access_key", forbidden)
    token = identity_context.set({"user_id": "u1", "tenant_id": "t1", "kind": kind,
                                  "role": "USER", "language": "zh", "token_id": 7})
    try:
        if kind == "session":
            assert session.get_current_user_context("untrusted-input") == ("u1", "t1", "USER")
        else:
            principal = api_key.authenticate_api_key("untrusted-input")
            assert (principal.user_id, principal.tenant_id, principal.role) == ("u1", "t1", "USER")
    finally:
        identity_context.reset(token)
