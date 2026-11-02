# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Authentication ownership, policy separation and request identity regressions."""

import ast
from pathlib import Path
import time

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from contracts.authentication import CredentialKind
from contracts.errors.exceptions import TokenExpiredError
from gateway.authentication import auth as identity, auth as internal, northbound_auth as northbound
from gateway.authentication.auth import extract_bearer_token
from gateway.authentication.auth import authenticate_identity


@pytest.mark.parametrize(
    "header, token",
    [
        (None, None),
        ("", None),
        ("  ", None),
        ("legacy-key", "legacy-key"),
        ("Bearer key", "key"),
        ("bearer\tkey", "key"),
        ("  BEARER key  ", "key"),
    ],
)
def test_shared_credential_extraction(header, token):
    assert extract_bearer_token(header) == token


@pytest.mark.parametrize("header", ["Bearer", "Bearer ", "Bearer a b", "Basic key", 42])
def test_invalid_authorization_syntax_is_rejected(header):
    with pytest.raises(TokenExpiredError):
        extract_bearer_token(header)


@pytest.fixture
def session_policy(monkeypatch):
    monkeypatch.setattr(identity, "IS_SPEED_MODE", False)
    monkeypatch.setattr(identity, "require_active_account", lambda uid: {"token_version": 0})
    monkeypatch.setattr(northbound, "require_active_account", lambda uid: {})
    monkeypatch.setattr(
        identity, "JWT_SECRET", "test-gateway-secret-32-bytes-long"
    )
    monkeypatch.setattr(
        identity,
        "get_user_tenant_by_user_id",
        lambda _: {
            "tenant_id": "db-tenant",
            "user_role": "USER",
        },
    )
    monkeypatch.setattr(
        identity, "ensure_cas_session_active_from_authorization", lambda _: None
    )


def signed_session(**claims):
    return jwt.encode(
        {"sub": "user", "iat": int(time.time()), "ver": 0, "iss": identity.JWT_ISSUER, "aud": "authenticated", "exp": int(time.time()) + 60, **claims},
        identity.JWT_SECRET,
        algorithm="HS256",
    )


def test_session_identity_uses_persisted_tenant_not_claims(session_policy):
    principal = authenticate_identity(
        "Bearer " + signed_session(tenant_id="untrusted"), require_role=True
    )
    assert (principal.user_id, principal.tenant_id, principal.role) == (
        "user",
        "db-tenant",
        "USER",
    )
    assert principal.kind == CredentialKind.SESSION


@pytest.mark.parametrize("claims", [{"exp": 1}, {"sub": ""}])
def test_expired_or_missing_session_identity_is_rejected(session_policy, claims):
    with pytest.raises(TokenExpiredError):
        authenticate_identity(signed_session(**claims))


def test_wrong_signature_is_rejected(session_policy):
    token = jwt.encode(
        {"sub": "user", "exp": int(time.time()) + 60},
        "different-key",
        algorithm="HS256",
    )
    with pytest.raises(TokenExpiredError):
        authenticate_identity(token)


def test_revoked_cas_session_is_rejected(session_policy, monkeypatch):
    def revoked(_):
        raise TokenExpiredError("CAS session has expired or been revoked")

    monkeypatch.setattr(
        identity, "ensure_cas_session_active_from_authorization", revoked
    )
    with pytest.raises(TokenExpiredError, match="CAS session"):
        authenticate_identity(signed_session(sid="revoked"))


def test_api_key_policy_uses_database_identity(monkeypatch):
    monkeypatch.setattr(northbound, "require_active_account", lambda uid: {})
    monkeypatch.setattr(
        northbound,
        "get_token_by_access_key",
        lambda key: (
            {
                "user_id": "key-owner",
                "token_id": 7,
                "delete_flag": "N",
            }
            if key == "key"
            else None
        ),
    )
    monkeypatch.setattr(
        northbound, "get_user_tenant_by_user_id", lambda _: {"tenant_id": "key-tenant"}
    )
    principal = authenticate_identity("Bearer key", CredentialKind.API_KEY)
    assert (principal.user_id, principal.tenant_id, principal.token_id) == (
        "key-owner",
        "key-tenant",
        7,
    )
    with pytest.raises(TokenExpiredError):
        authenticate_identity("Bearer unknown", CredentialKind.API_KEY)


def test_api_key_policy_rejects_inactive_keys(monkeypatch):
    monkeypatch.setattr(
        northbound, "get_token_by_access_key", lambda _: {"delete_flag": "Y"}
    )
    with pytest.raises(TokenExpiredError):
        authenticate_identity("Bearer revoked", CredentialKind.API_KEY)


def test_session_token_cannot_be_used_for_internal_runtime(session_policy, monkeypatch):
    monkeypatch.setattr(internal, "JWT_SECRET", identity.JWT_SECRET)
    with pytest.raises(TokenExpiredError):
        authenticate_identity(signed_session(), CredentialKind.INTERNAL)


def test_gateway_authentication_maps_an_invalid_api_key_to_401(monkeypatch):
    from gateway.authentication.northbound_auth import get_northbound_context
    from fastapi import Depends

    monkeypatch.setattr(northbound, "require_active_account", lambda uid: {})
    monkeypatch.setattr(northbound, "get_token_by_access_key", lambda _: None)
    app = FastAPI()

    @app.get("/protected")
    async def protected(principal=Depends(get_northbound_context)):
        return {"user_id": principal.user_id}

    response = TestClient(app).get(
        "/protected", headers={"Authorization": "Bearer invalid"}
    )
    assert response.status_code == 401


def test_api_and_services_do_not_implement_credential_parsers():
    root = Path(__file__).resolve().parents[3] / "backend"
    folders = (
        "management/api",
        "runtime/api",
        "gateway/api",
        "data_process/api",
        "management/services",
        "services",
    )
    for folder in folders:
        for path in (root / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
                if not isinstance(node, ast.Call):
                    continue
                call = ast.unparse(node.func)
                assert call != "jwt.decode", path
                if isinstance(node.func, ast.Attribute) and node.func.attr in {
                    "replace",
                    "split",
                    "startswith",
                }:
                    assert not any(
                        isinstance(arg, ast.Constant) and arg.value == "Bearer "
                        for arg in node.args
                    ), path
                if folder.endswith("services"):
                    assert call.rsplit(".", 1)[-1] not in {
                        "get_current_user_id",
                        "get_current_user_info",
                        "_decode_jwt_token",
                        "parse_pending_oauth_token",
                    }, path


def test_internal_runtime_identity_retains_its_scoped_tenant(
    session_policy, monkeypatch
):
    monkeypatch.setattr(internal, "JWT_SECRET", identity.JWT_SECRET)
    token = signed_session(
        iss=internal.INTERNAL_RUNTIME_JWT_ISSUER,
        aud=internal.INTERNAL_RUNTIME_JWT_AUDIENCE,
        scope=internal.INTERNAL_RUNTIME_JWT_SCOPE,
        tenant_id="runtime-tenant",
    )
    principal = authenticate_identity(token, CredentialKind.INTERNAL)
    assert (principal.user_id, principal.tenant_id, principal.kind) == (
        "user",
        "runtime-tenant",
        CredentialKind.INTERNAL,
    )


def test_internal_runtime_token_cannot_be_used_as_a_browser_session(session_policy):
    token = signed_session(
        iss=internal.INTERNAL_RUNTIME_JWT_ISSUER,
        aud=internal.INTERNAL_RUNTIME_JWT_AUDIENCE,
        scope=internal.INTERNAL_RUNTIME_JWT_SCOPE,
    )
    with pytest.raises(TokenExpiredError):
        authenticate_identity(token)


def test_pending_account_token_cannot_be_used_as_a_browser_session(session_policy):
    from contracts.constants.constants import OAUTH_PENDING_PURPOSE

    with pytest.raises(TokenExpiredError):
        authenticate_identity(signed_session(purpose=OAUTH_PENDING_PURPOSE))


def test_pending_oauth_identity_requires_signed_purpose_and_provider(
    session_policy, monkeypatch
):
    from gateway.authentication import auth as oauth
    from contracts.constants.constants import OAUTH_PENDING_PURPOSE
    from contracts.errors.exceptions import OAuthLinkError

    monkeypatch.setattr(oauth, "JWT_SECRET", identity.JWT_SECRET)
    token = signed_session(
        purpose=OAUTH_PENDING_PURPOSE,
        provider="github",
        provider_user_id="provider-user",
    )
    pending = oauth.parse_pending_oauth_token(token)
    assert pending["provider"] == "github"
    assert pending["provider_user_id"] == "provider-user"
    with pytest.raises(OAuthLinkError):
        oauth.parse_pending_oauth_token(
            signed_session(
                purpose="session", provider="github", provider_user_id="provider-user"
            )
        )
    with pytest.raises(OAuthLinkError):
        oauth.parse_pending_oauth_token(
            signed_session(purpose=OAUTH_PENDING_PURPOSE, provider="github")
        )
    with pytest.raises(OAuthLinkError):
        oauth.parse_pending_oauth_token(
            signed_session(
                purpose=OAUTH_PENDING_PURPOSE,
                provider="github",
                provider_user_id="provider-user",
                exp=1,
            )
        )


@pytest.mark.parametrize("claims", [{"ver": 1}, {"iss": "other"}, {"aud": "other"}])
def test_native_session_rejects_wrong_revision_or_credential_scope(session_policy, claims):
    with pytest.raises(TokenExpiredError):
        authenticate_identity(signed_session(**claims))


def test_api_key_rejects_disabled_account(monkeypatch):
    monkeypatch.setattr(northbound, "get_token_by_access_key", lambda _: {"user_id": "disabled", "delete_flag": "N"})

    def disabled(_):
        raise TokenExpiredError("Account is disabled")

    monkeypatch.setattr(northbound, "require_active_account", disabled)
    with pytest.raises(TokenExpiredError):
        authenticate_identity("Bearer key", CredentialKind.API_KEY)
