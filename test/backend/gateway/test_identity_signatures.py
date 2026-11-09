# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Request-bound internal identity envelopes are separate from external sessions."""

import time

import jwt
import pytest

from infrastructure.service_identity.gateway import (
    IdentityError, sign_identity, verify_identity, sign_lookup, verify_lookup,
)
from infrastructure.security.policy import is_public_request

KEY = "local-signature-fixture-which-is-not-a-deployment-secret"
IDENTITY = {"user_id": "u1", "tenant_id": "t1", "role": "USER", "kind": "session", "language": "zh"}


def test_identity_is_bound_to_service_method_path_query_and_scope():
    token = sign_identity(IDENTITY, "management", "POST", "/api/agent/run", b"q=1", key=KEY)
    assert verify_identity(token, "management", "POST", "/api/agent/run", b"q=1", key=KEY) == IDENTITY
    for audience, method, path, query in [
        ("runtime", "POST", "/api/agent/run", b"q=1"),
        ("management", "GET", "/api/agent/run", b"q=1"),
        ("management", "POST", "/api/agent/stop", b"q=1"),
        ("management", "POST", "/api/agent/run", b"q=2"),
    ]:
        with pytest.raises(IdentityError):
            verify_identity(token, audience, method, path, query, key=KEY)


@pytest.mark.parametrize("alteration", ["expired", "scope", "issuer", "missing", "future", "long", "wrong-key"])
def test_invalid_tokens_are_rejected(alteration):
    token = sign_identity(IDENTITY, "runtime", "GET", "/api/models", b"", key=KEY)
    claims = jwt.decode(token, options={"verify_signature": False})
    if alteration == "expired": claims["exp"] = int(time.time()) - 1
    if alteration == "scope": claims["scope"] = "identity:lookup"
    if alteration == "issuer": claims["iss"] = "external-session"
    if alteration == "missing": claims.pop("iat")
    if alteration == "future": claims["iat"] = int(time.time()) + 3600
    if alteration == "long": claims["exp"] = int(time.time()) + 3600
    token = jwt.encode(claims, KEY if alteration != "wrong-key" else KEY + "bad", algorithm="HS256")
    with pytest.raises(IdentityError):
        verify_identity(token, "runtime", "GET", "/api/models", b"", key=KEY)


def test_lookup_signature_binds_body_and_cannot_become_user_identity():
    token = sign_lookup(b'{"user_id":"u1"}', key=KEY)
    verify_lookup(token, b'{"user_id":"u1"}', key=KEY)
    with pytest.raises(IdentityError):
        verify_lookup(token, b'{"user_id":"other"}', key=KEY)
    with pytest.raises(IdentityError):
        verify_identity(token, "management", "POST", "/api/internal/identity/resolve", b"", key=KEY)


def test_anonymous_envelope_does_not_grant_protected_access():
    token = sign_identity(None, "management", "POST", "/api/user/signin", b"", key=KEY)
    assert verify_identity(token, "management", "POST", "/api/user/signin", b"", key=KEY) is None
    with pytest.raises(IdentityError):
        sign_identity(None, "management", "POST", "/api/users/list", b"", key=KEY)


@pytest.mark.parametrize("method,path,expected", [
    ("POST", "/api/user/signin", True), ("GET", "/api/user/signin", False),
    ("GET", "/api/user/oauth/accounts", False), ("GET", "/api/user/oauth/callback", True),
    ("GET", "/nb/a2a/x/.well-known/agent-card.json", True),
    ("POST", "/nb/a2a/x/message:send", False), ("GET", "/api/share/token", True),
    ("POST", "/api/share/conversation/1", False),
])
def test_public_policy_has_method_and_path_boundaries(method, path, expected):
    assert is_public_request(method, path) == expected


def test_signing_key_requires_configuration_and_separates_session_key(monkeypatch):
    from contracts.constants import environment
    from infrastructure.service_identity.gateway import signing_key

    monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", "")
    monkeypatch.setattr(environment, "JWT_SECRET", "")
    with pytest.raises(IdentityError):
        signing_key()
    monkeypatch.setattr(environment, "JWT_SECRET", KEY)
    assert signing_key() != KEY
    assert len(signing_key()) == 64
