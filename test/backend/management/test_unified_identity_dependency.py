# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Branch coverage for the unified identity dependency and API-key auth.

Covers the path-based credential policy, the incomplete-principal guard,
usage accounting (exclusions and fail-open), the API-key record failure
paths, and the AK/SK validation branches. Collaborators are mocked at their
lookup sites inside the owning modules.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from contracts.authentication import AuthenticatedIdentity, CredentialKind
from contracts.errors.exceptions import (
    SignatureValidationError,
    TokenExpiredError,
    UnauthorizedError,
)
from management.services.permission.identity import dependency as dep
from backend.http.server import northbound as shared_nb
from management.services.permission.identity import northbound as nb


def make_request(path="/nb/v1/automations", method="GET", headers=None):
    # Starlette headers are case-insensitive; normalize the fake the same way
    # so request-id lookups behave like the real request.
    return SimpleNamespace(
        scope={"path": path},
        url=SimpleNamespace(path=path),
        method=method,
        headers={str(k).lower(): v for k, v in (headers or {}).items()},
        state=SimpleNamespace(),
    )


# ---------------------------------------------------------------------------
# credential_kind_for_path / is_northbound_path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/nb/v1/automations", CredentialKind.API_KEY),
        ("/nb", CredentialKind.API_KEY),
        ("/api/agent/run", CredentialKind.SESSION),
        ("/nbx/v1", CredentialKind.SESSION),
        ("", CredentialKind.SESSION),
    ],
)
def test_credential_kind_follows_path(path, expected):
    assert dep.credential_kind_for_path(path) is expected


def test_request_path_falls_back_to_url():
    request = SimpleNamespace(scope={}, url=SimpleNamespace(path="/nb/v1/x"))
    assert dep._request_path(request) == "/nb/v1/x"
    assert dep._request_path(None) == ""


# ---------------------------------------------------------------------------
# unified_identity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unified_identity_accounts_api_key_calls(monkeypatch):
    principal = AuthenticatedIdentity("u1", "t1", kind=CredentialKind.API_KEY, token_id=7)
    monkeypatch.setattr(
        "management.services.permission.identity.session.authenticate_identity",
        lambda authorization, kind, request: principal,
    )
    accounted = []
    monkeypatch.setattr(nb, "submit_api_key_usage", lambda p, request=None: accounted.append(p))
    request = make_request()
    resolved = await dep.unified_identity(request, authorization="Bearer k")
    assert resolved is principal
    assert accounted == [principal]
    assert request.state.authenticated_identity is principal


@pytest.mark.asyncio
async def test_unified_identity_skips_accounting_for_sessions(monkeypatch):
    principal = AuthenticatedIdentity("u1", "t1", kind=CredentialKind.SESSION)
    monkeypatch.setattr(
        "management.services.permission.identity.session.authenticate_identity",
        lambda authorization, kind, request: principal,
    )
    accounted = []
    monkeypatch.setattr(nb, "submit_api_key_usage", lambda p, request=None: accounted.append(p))
    resolved = await dep.unified_identity(make_request(path="/api/agent/run"), authorization=None)
    assert resolved is principal
    assert accounted == []


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id,tenant_id", [("", "t1"), ("u1", "")])
async def test_unified_identity_rejects_incomplete_principal(monkeypatch, user_id, tenant_id):
    principal = AuthenticatedIdentity(user_id, tenant_id, kind=CredentialKind.API_KEY)
    monkeypatch.setattr(
        "management.services.permission.identity.session.authenticate_identity",
        lambda authorization, kind, request: principal,
    )
    with pytest.raises(UnauthorizedError):
        await dep.unified_identity(make_request(), authorization="Bearer k")


# ---------------------------------------------------------------------------
# _require_api_key_record failure paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "record,reason",
    [
        (None, "missing"),
        ({"delete_flag": "Y", "user_id": "u1"}, "revoked"),
        ({"delete_flag": "N"}, "no-user"),
    ],
)
def test_api_key_record_failure_paths(monkeypatch, record, reason):
    monkeypatch.setattr(nb, "get_token_by_access_key", lambda key: record)
    monkeypatch.setattr(nb, "require_active_account", lambda user: None)
    with pytest.raises(TokenExpiredError):
        nb._require_api_key_record("fixture-key")


def test_empty_access_key_rejected():
    with pytest.raises(TokenExpiredError):
        nb._require_api_key_record("")


def test_validate_bearer_token_returns_false_on_failure(monkeypatch):
    monkeypatch.setattr(nb, "get_token_by_access_key", lambda key: None)
    ok, record = nb.validate_bearer_token("Bearer fixture-key")
    assert ok is False and record is None


def test_get_user_and_tenant_requires_membership(monkeypatch):
    monkeypatch.setattr(
        nb, "get_token_by_access_key", lambda key: {"user_id": "u1", "token_id": 7, "delete_flag": "N"}
    )
    monkeypatch.setattr(nb, "require_active_account", lambda user: None)
    monkeypatch.setattr(nb, "get_user_tenant_by_user_id", lambda user: None)
    with pytest.raises(TokenExpiredError):
        nb.get_user_and_tenant_by_access_key("fixture-key")


# ---------------------------------------------------------------------------
# record_api_key_usage: exclusions and fail-open accounting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/nb/v1/chat/run", "/nb/v1/chat/stop/42", "/nb/v1/conversations/42/title"],
)
def test_usage_accounting_excludes_hot_paths(monkeypatch, path):
    logged = []
    monkeypatch.setattr(shared_nb, "log_token_usage", lambda **kw: logged.append(kw))
    principal = AuthenticatedIdentity("u1", "t1", kind=CredentialKind.API_KEY, token_id=7)
    nb.record_api_key_usage(principal, make_request(path=path))
    assert logged == []


def test_usage_accounting_skips_without_token_id(monkeypatch):
    logged = []
    monkeypatch.setattr(shared_nb, "log_token_usage", lambda **kw: logged.append(kw))
    principal = AuthenticatedIdentity("u1", "t1", kind=CredentialKind.API_KEY, token_id=0)
    nb.record_api_key_usage(principal, make_request())
    assert logged == []


def test_usage_accounting_is_fail_open(monkeypatch):
    def boom(**kw):
        raise RuntimeError("ledger down")

    monkeypatch.setattr(shared_nb, "log_token_usage", boom)
    principal = AuthenticatedIdentity("u1", "t1", kind=CredentialKind.API_KEY, token_id=7)
    # Must not raise: accounting never blocks an authenticated request.
    nb.record_api_key_usage(principal, make_request(headers={"X-Request-Id": "req-1"}))


def test_usage_accounting_records_request_id(monkeypatch):
    logged = []
    monkeypatch.setattr(shared_nb, "log_token_usage", lambda **kw: logged.append(kw))
    principal = AuthenticatedIdentity("u1", "t1", kind=CredentialKind.API_KEY, token_id=7)
    nb.record_api_key_usage(principal, make_request(headers={"X-Request-Id": "req-9"}))
    assert logged[0]["metadata"]["request_id"] == "req-9"
    assert logged[0]["call_function_name"] == "/nb/v1/automations"


def test_usage_accounting_stores_route_template_not_long_object_path(monkeypatch):
    """P2 regression: call_function_name is VARCHAR(100); a long object path
    must be stored as the stable route template, with the raw path in JSONB."""
    logged = []
    monkeypatch.setattr(shared_nb, "log_token_usage", lambda **kw: logged.append(kw))
    principal = AuthenticatedIdentity("u1", "t1", kind=CredentialKind.API_KEY, token_id=7)
    long_path = "/nb/v1/file/download/" + "segment/" * 40 + "file.bin"
    request = make_request(path=long_path)
    request.scope["route"] = SimpleNamespace(path="/nb/v1/file/download/{object_name:path}")
    nb.record_api_key_usage(principal, request)
    assert logged[0]["call_function_name"] == "/nb/v1/file/download/{object_name:path}"
    assert logged[0]["metadata"]["path"] == long_path


def test_usage_accounting_truncates_when_no_route_template(monkeypatch):
    logged = []
    monkeypatch.setattr(shared_nb, "log_token_usage", lambda **kw: logged.append(kw))
    principal = AuthenticatedIdentity("u1", "t1", kind=CredentialKind.API_KEY, token_id=7)
    long_path = "/nb/v1/file/download/" + "x" * 200
    nb.record_api_key_usage(principal, make_request(path=long_path))
    assert len(logged[0]["call_function_name"]) == 100


# ---------------------------------------------------------------------------
# submit_api_key_usage: managed-lane accounting off the event loop
# ---------------------------------------------------------------------------


def test_submit_api_key_usage_uses_managed_control_io_lane(monkeypatch):
    """P1 regression: the synchronous ledger write must be submitted to a
    managed lane, never executed inside the async identity dependency."""
    from management.thread_management import config_thread_manager

    submissions = []
    monkeypatch.setattr(
        config_thread_manager, "submit",
        lambda lane, spec, fn, *a, **k: submissions.append((lane, spec, fn, a, k)),
    )
    principal = AuthenticatedIdentity("u1", "t1", kind=CredentialKind.API_KEY, token_id=7)
    request = make_request()
    nb.submit_api_key_usage(principal, request)
    assert len(submissions) == 1
    lane, spec, fn, args, _ = submissions[0]
    assert lane == "control-io"
    assert spec.task_name == "record-api-key-usage"
    assert spec.owner == "config"
    assert fn is nb.record_api_key_usage
    assert args == (principal, request)


@pytest.mark.parametrize("error_name", ["ThreadCapacityExceeded", "ThreadManagerNotRunning", "ThreadManagerDraining"])
def test_submit_api_key_usage_drops_on_admission_failure(monkeypatch, error_name):
    from management.thread_management import config_thread_manager
    from nexent.core.concurrency import (
        ThreadCapacityExceeded,
        ThreadManagerDraining,
        ThreadManagerNotRunning,
    )

    errors = {
        "ThreadCapacityExceeded": ThreadCapacityExceeded("control-io", 16, 32),
        "ThreadManagerNotRunning": ThreadManagerNotRunning("not started"),
        "ThreadManagerDraining": ThreadManagerDraining("draining"),
    }
    error = errors[error_name]

    def reject(*a, **k):
        raise error

    monkeypatch.setattr(config_thread_manager, "submit", reject)
    principal = AuthenticatedIdentity("u1", "t1", kind=CredentialKind.API_KEY, token_id=7)
    # Must not raise: accounting never blocks an authenticated request.
    nb.submit_api_key_usage(principal, make_request())


def test_submit_api_key_usage_end_to_end_records_through_lane(monkeypatch):
    """The submitted function is the real accounting unit: running it writes
    the ledger entry with the route template and request id."""
    from management.thread_management import config_thread_manager

    logged = []
    monkeypatch.setattr(shared_nb, "log_token_usage", lambda **kw: logged.append(kw))
    monkeypatch.setattr(
        config_thread_manager, "submit",
        lambda lane, spec, fn, *a, **k: fn(*a, **k),
    )
    principal = AuthenticatedIdentity("u1", "t1", kind=CredentialKind.API_KEY, token_id=7)
    nb.submit_api_key_usage(principal, make_request(headers={"X-Request-Id": "req-7"}))
    assert logged[0]["metadata"]["request_id"] == "req-7"
    assert logged[0]["token_id"] == 7


# ---------------------------------------------------------------------------
# AK/SK branches
# ---------------------------------------------------------------------------


def test_extract_aksk_headers_requires_all_three():
    with pytest.raises(TokenExpiredError):
        nb.extract_aksk_headers({"X-Access-Key": "ak"})
    ak, ts, sig = nb.extract_aksk_headers(
        {"X-Access-Key": "ak", "X-Timestamp": "123", "X-Signature": "sig"}
    )
    assert (ak, ts, sig) == ("ak", "123", "sig")


def test_verify_aksk_signature_rejects_wrong_key(monkeypatch):
    monkeypatch.setattr(nb, "get_aksk_config", lambda tenant: ("expected-ak", "secret"))
    assert nb.verify_aksk_signature("other-ak", "123", "sig", "body") is False


def test_verify_aksk_signature_unconfigured_returns_false():
    # get_aksk_config raises by default: verification must degrade to False.
    assert nb.verify_aksk_signature("ak", "123", "sig", "body") is False


def test_validate_aksk_rejects_bad_timestamp(monkeypatch):
    monkeypatch.setattr(nb, "validate_timestamp", lambda ts: False)
    headers = {"X-Access-Key": "ak", "X-Timestamp": "0", "X-Signature": "sig"}
    with pytest.raises(TokenExpiredError):
        nb.validate_aksk_authentication(headers, "body")


def test_validate_aksk_rejects_bad_signature(monkeypatch):
    monkeypatch.setattr(nb, "validate_timestamp", lambda ts: True)
    monkeypatch.setattr(nb, "verify_aksk_signature", lambda *a: False)
    headers = {"X-Access-Key": "ak", "X-Timestamp": "123", "X-Signature": "sig"}
    with pytest.raises(SignatureValidationError):
        nb.validate_aksk_authentication(headers, "body")


def test_validate_aksk_accepts_valid_signature(monkeypatch):
    monkeypatch.setattr(nb, "validate_timestamp", lambda ts: True)
    monkeypatch.setattr(nb, "verify_aksk_signature", lambda *a: True)
    headers = {"X-Access-Key": "ak", "X-Timestamp": "123", "X-Signature": "sig"}
    assert nb.validate_aksk_authentication(headers, "body") is True


def test_authenticate_api_key_wraps_failures(monkeypatch):
    monkeypatch.setattr(nb, "get_user_and_tenant_by_access_key", lambda key: None)
    with pytest.raises(TokenExpiredError):
        nb.authenticate_api_key("Bearer fixture-key")