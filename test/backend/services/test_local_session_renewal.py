# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit tests for local session credentials and renewal boundaries."""

import hashlib
import time
from contextlib import nullcontext
from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock

import jwt
import pytest

from contracts.errors.exceptions import TokenExpiredError, UnauthorizedError
from gateway.identity.protocol import IdentityError
from management.db.identity import local_session as session_db
from management.services.permission.identity import authentication, gateway_lookup, local_session, session


USER_ID = "native-user"
TENANT_ID = "native-tenant"
SID = "local:existing-session"
SECRET = "synthetic-local-renewal-signing-key-32-bytes"
ISSUER = "synthetic-local-renewal"
VERSION = 3
REFRESH = "r" * 43
REQUEST_ID = "original-request-id"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def utc_at(epoch_seconds):
    return datetime.fromtimestamp(epoch_seconds, UTC).replace(tzinfo=None)


@pytest.fixture
def clock(monkeypatch):
    now = int(time.time())
    monkeypatch.setattr(local_session, "_utc_now", lambda: utc_at(now))
    for module in (local_session, session):
        monkeypatch.setattr(module, "JWT_SECRET", SECRET)
        monkeypatch.setattr(module, "JWT_ISSUER", ISSUER)
    monkeypatch.setattr(local_session, "JWT_EXPIRY_SECONDS", 3600)
    monkeypatch.setattr(session, "DEBUG_JWT_EXPIRE_SECONDS", 0)
    return now


def access_at(now, *, sid=SID, lifetime=3600, **extra):
    return jwt.encode({
        "sub": USER_ID, "sid": sid, "ver": VERSION, "iat": now,
        "exp": now + lifetime, "aud": "authenticated", "iss": ISSUER, **extra,
    }, SECRET, algorithm="HS256")


def read_access(token):
    return jwt.decode(token, SECRET, algorithms=["HS256"], audience="authenticated", issuer=ISSUER)


@pytest.fixture
def row(clock):
    return {
        "refresh_digest": digest(REFRESH),
        "idle_expires_at": utc_at(clock + 300),
        "absolute_expires_at": utc_at(clock + 7200),
        "revoked_at": None,
        "retry_until": None,
    }


def renewal_database(monkeypatch, row, *, version=VERSION, membership=USER_ID):
    db = MagicMock()
    db.execute.side_effect = [
        Mock(scalar_one_or_none=Mock(return_value=version)),
        Mock(scalar=Mock(return_value=membership)),
        Mock(mappings=Mock(return_value=Mock(one_or_none=Mock(return_value=row)))),
        Mock(),
    ]
    monkeypatch.setattr(local_session, "get_db_session", lambda: nullcontext(db))
    return db


@pytest.mark.parametrize("version", [None, VERSION])
def test_issue_signs_token_and_persists_only_refresh_digest(monkeypatch, clock, version):
    account = Mock(return_value={"token_version": VERSION})
    db = Mock()
    monkeypatch.setattr(local_session, "require_active_account", account)
    monkeypatch.setattr(local_session, "get_db_session", lambda: nullcontext(db))

    result = authentication.build_token_response(USER_ID, version)

    claims = read_access(result["access_token"])
    assert (claims["sub"], claims["ver"], claims["iat"], claims["exp"]) == (
        USER_ID, VERSION, clock, clock + 3600,
    )
    assert claims["sid"].startswith("local:")
    assert result["expires_at"] == claims["exp"]
    assert result["expires_in_seconds"] == 3600
    assert result["refresh_expires_at"] == clock + local_session.IDLE_SECONDS
    cleanup, insert = db.execute.call_args_list
    assert "LIMIT 32 FOR UPDATE SKIP LOCKED" in str(cleanup.args[0])
    assert cleanup.args[1] == {"now": utc_at(clock)}
    insert_sql = str(insert.args[0])
    assert "created_by, create_time, updated_by, update_time" in insert_sql
    assert "created_at" not in insert_sql and "last_refreshed_at" not in insert_sql
    assert insert.args[1] == {
        "sid": claims["sid"], "uid": USER_ID, "digest": digest(result["refresh_token"]),
        "now": utc_at(clock), "idle": utc_at(result["refresh_expires_at"]),
        "absolute": utc_at(clock + local_session.ABSOLUTE_SECONDS),
    }
    assert result["refresh_token"] not in insert.args[1].values()
    if version is None:
        account.assert_called_once_with(USER_ID)
    else:
        account.assert_not_called()


def test_rotate_persists_one_successor_and_retry_returns_identical_tokens(monkeypatch, clock, row):
    access = access_at(clock - 60, lifetime=300)
    row["absolute_expires_at"] = utc_at(clock + 600)
    db = renewal_database(monkeypatch, row)

    result = local_session.rotate_local_session(access, REFRESH, REQUEST_ID)

    assert result["refresh_token"] != REFRESH
    assert result["expires_at"] == result["refresh_expires_at"] == clock + 600
    assert result["expires_in_seconds"] == 600
    claims = read_access(result["access_token"])
    assert (claims["sid"], claims["ver"], claims["iat"], claims["exp"]) == (SID, VERSION, clock, clock + 600)
    assert "FOR UPDATE" in str(db.execute.call_args_list[0].args[0])
    assert "FOR UPDATE" in str(db.execute.call_args_list[2].args[0])
    sql, update = db.execute.call_args.args
    assert "updated_by = :uid" in str(sql)
    assert update["uid"] == USER_ID and update["sid"] == SID
    assert update["replacement"] == digest(result["refresh_token"])
    assert update["previous_refresh"] == digest(REFRESH)
    assert update["previous_access"] == digest(access)
    assert update["retry_until"] == utc_at(clock + local_session.RETRY_SECONDS)
    assert update["request_id"] == REQUEST_ID

    rotated = {
        **row, "refresh_digest": update["replacement"], "previous_refresh_digest": update["previous_refresh"],
        "previous_access_digest": update["previous_access"], "retry_until": update["retry_until"],
        "request_id": update["request_id"], "rotation_nonce": update["nonce"],
        "idle_expires_at": update["idle"], "access_issued_at": update["now"], "access_expires_at": update["access_exp"],
    }
    db = renewal_database(monkeypatch, rotated)
    assert local_session.rotate_local_session(access, REFRESH, REQUEST_ID) == result
    assert db.execute.call_count == 3

    for supplied_access, request_id, changes in (
        (access, None, {}),
        (access, "different-request-id", {}),
        (access_at(clock - 120), REQUEST_ID, {}),
        (access, REQUEST_ID, {"access_expires_at": utc_at(clock)}),
        (access, REQUEST_ID, {"rotation_nonce": "invalidated-nonce"}),
    ):
        db = renewal_database(monkeypatch, {**rotated, **changes})
        with pytest.raises(local_session.RefreshConflict, match="already processed"):
            local_session.rotate_local_session(supplied_access, REFRESH, request_id)
        assert db.execute.call_count == 3

    db = renewal_database(monkeypatch, {**rotated, "retry_until": utc_at(clock)})
    with pytest.raises(UnauthorizedError, match="Invalid refresh token"):
        local_session.rotate_local_session(access, REFRESH, REQUEST_ID)
    assert db.execute.call_count == 3

    for seconds_later in (30, 60, 90):
        monkeypatch.setattr(local_session, "_utc_now", lambda now=clock + seconds_later: utc_at(now))
        db = renewal_database(monkeypatch, rotated)
        assert local_session.rotate_local_session(
            result["access_token"], result["refresh_token"], f"activity-request-{seconds_later}",
        ) is None
        assert db.execute.call_count == 3

    db = renewal_database(monkeypatch, rotated)
    with pytest.raises(UnauthorizedError, match="Invalid refresh token"):
        local_session.rotate_local_session(result["access_token"], "x" * 43, REQUEST_ID)
    assert db.execute.call_count == 3


@pytest.mark.parametrize("refresh", [None, "x" * 31, "x" * 129])
def test_rejects_invalid_refresh_lengths_before_database(monkeypatch, refresh):
    connect = Mock()
    monkeypatch.setattr(local_session, "get_db_session", connect)
    with pytest.raises(UnauthorizedError, match="Invalid refresh token"):
        local_session.rotate_local_session("unused-token", refresh, None)
    connect.assert_not_called()


@pytest.mark.parametrize("request_id", ["short", "?" * 16, "x" * 65])
def test_rejects_invalid_request_identifier_before_database(monkeypatch, request_id):
    connect = Mock()
    monkeypatch.setattr(local_session, "get_db_session", connect)
    with pytest.raises(local_session.InvalidRefreshRequestId):
        local_session.rotate_local_session("unused-token", REFRESH, request_id)
    connect.assert_not_called()


@pytest.mark.parametrize("kind", ["malformed", "expired", "cas", "purpose", "scope", "subject", "version", "expiry"])
def test_rejects_invalid_or_ineligible_access_tokens(monkeypatch, clock, kind):
    connect = Mock()
    monkeypatch.setattr(local_session, "get_db_session", connect)
    access = {
        "malformed": "bad-token",
        "expired": access_at(clock - 120, lifetime=60),
        "cas": access_at(clock - 60, sid="cas-session"),
        "purpose": access_at(clock - 60, purpose="other"),
        "scope": access_at(clock - 60, scope="other"),
        "subject": access_at(clock - 60, sub=""),
        "version": access_at(clock - 60, ver=True),
        "expiry": access_at(clock - 60, exp=str(clock + 600)),
    }[kind]
    with pytest.raises(UnauthorizedError, match="Invalid"):
        local_session.rotate_local_session(access, REFRESH, REQUEST_ID)
    connect.assert_not_called()


def test_requires_configured_signing_secret(monkeypatch):
    monkeypatch.setattr(local_session, "JWT_SECRET", "")
    with pytest.raises(RuntimeError, match="JWT verification is not configured"):
        local_session.rotate_local_session("unused-token", REFRESH, None)


@pytest.mark.parametrize("version,membership", [(None, USER_ID), (VERSION + 1, USER_ID), (VERSION, None)])
def test_rejects_inactive_owner_or_revised_credentials(monkeypatch, clock, row, version, membership):
    db = renewal_database(monkeypatch, row, version=version, membership=membership)
    with pytest.raises(UnauthorizedError, match="no longer active"):
        local_session.rotate_local_session(access_at(clock - 60), REFRESH, REQUEST_ID)
    assert db.execute.call_count == 2


@pytest.mark.parametrize("state", ["missing", "revoked", "idle", "absolute", "expired-during-lock", "mismatch"])
def test_rejects_inactive_or_unmatched_session_without_writing(monkeypatch, clock, row, state):
    access = access_at(clock - 60)
    if state == "expired-during-lock":
        monkeypatch.setattr(local_session, "_utc_now", lambda: utc_at(clock + 3540))
    elif state != "missing":
        row.update({
            "revoked": {"revoked_at": utc_at(clock)},
            "idle": {"idle_expires_at": utc_at(clock)},
            "absolute": {"absolute_expires_at": utc_at(clock)},
            "mismatch": {"refresh_digest": digest("elsewhere")},
        }[state])
    db = renewal_database(monkeypatch, None if state == "missing" else row)
    message = "Invalid refresh token" if state == "mismatch" else "expired or been revoked"
    with pytest.raises(UnauthorizedError, match=message):
        local_session.rotate_local_session(access, REFRESH, REQUEST_ID)
    assert db.execute.call_count == 3


@pytest.mark.asyncio
async def test_refresh_service_passes_credentials_and_request_id_to_worker(monkeypatch):
    worker = Mock(return_value={"expires_in_seconds": 60})
    monkeypatch.setattr(authentication, "rotate_local_session", worker)
    result = await authentication.refresh_user_token("access", REFRESH, REQUEST_ID)
    assert result == {"expires_in_seconds": 60}
    worker.assert_called_once_with("access", REFRESH, REQUEST_ID)


@pytest.mark.parametrize(("sid", "active"), [(SID, True), (SID, False), ("cas-session", True)])
def test_management_session_validation_uses_correct_session_store(monkeypatch, sid, active):
    monkeypatch.setattr(session, "_gateway_identity", lambda kind=None: None)
    monkeypatch.setattr(session, "_decode_jwt_token", lambda _: {"sid": sid, "sub": USER_ID})
    lookup = Mock(return_value=active)
    cas = Mock()
    monkeypatch.setattr(session, "is_local_session_active", lookup)
    monkeypatch.setattr(session, "ensure_cas_session_active_from_authorization", cas)
    monkeypatch.setattr(session, "get_user_tenant_by_user_id", lambda _: {"tenant_id": TENANT_ID, "roles": ["USER"]})

    if active:
        assert session.get_current_user_id("Bearer access") == (USER_ID, TENANT_ID)
    else:
        with pytest.raises(TokenExpiredError):
            session.get_current_user_id("Bearer access")
    if sid == SID:
        lookup.assert_called_once_with(SID, USER_ID)
        cas.assert_not_called()
    else:
        lookup.assert_not_called()
        cas.assert_called_once_with("Bearer access")


@pytest.mark.parametrize(
    ("sid", "active"),
    [(SID, True), (SID, False), ("cas-session", True), ("cas-session", False), (None, True)],
)
def test_management_gateway_lookup_selects_the_session_store(mocker, sid, active):
    mocker.patch("management.db.identity.account.get_account", return_value={
        "delete_flag": "N", "token_version": VERSION, "user_roles": ["USER"],
    })
    membership = mocker.patch("management.db.identity.user_tenant.get_user_tenant_by_user_id",
                              return_value={"tenant_id": TENANT_ID})
    local = mocker.patch("management.db.identity.local_session.is_local_session_active", return_value=active)
    cas = mocker.patch("management.db.identity.cas_session.is_cas_session_active", return_value=active)
    query = {"kind": "session", "user_id": USER_ID, "token_version": VERSION, "session_id": sid}

    if active:
        identity = gateway_lookup.resolve_gateway_identity(query)
        assert (identity["user_id"], identity["tenant_id"], identity["session_id"]) == (USER_ID, TENANT_ID, sid)
    else:
        with pytest.raises(IdentityError, match="Session is unavailable"):
            gateway_lookup.resolve_gateway_identity(query)
        membership.assert_not_called()
    if sid == SID:
        local.assert_called_once_with(SID, USER_ID)
        cas.assert_not_called()
    else:
        local.assert_not_called()
        if sid:
            cas.assert_called_once_with(sid)
        else:
            cas.assert_not_called()


@pytest.mark.parametrize("database_value", [1, None])
def test_session_repository_reads_active_owner_and_revokes_only_that_session(monkeypatch, clock, database_value):
    db = Mock()
    db.execute.return_value.scalar.return_value = database_value
    now = Mock(return_value=datetime.fromtimestamp(clock, UTC))
    monkeypatch.setattr(session_db, "datetime", Mock(now=now))
    monkeypatch.setattr(session_db, "get_db_session", lambda: nullcontext(db))

    assert session_db.is_local_session_active(SID, USER_ID) is bool(database_value)
    session_db.revoke_local_session(SID, USER_ID)

    select_call, revoke_call = db.execute.call_args_list
    for call in (select_call, revoke_call):
        sql, params = call.args
        assert "session_id = :sid AND user_id = :uid" in str(sql)
        assert "revoked_at IS NULL AND delete_flag = 'N'" in str(sql)
        assert params == {"sid": SID, "uid": USER_ID, "now": utc_at(clock)}
    assert now.call_count == 2
    now.assert_called_with(UTC)
    assert "idle_expires_at > :now AND absolute_expires_at > :now" in str(select_call.args[0])
    assert "revoked_at = :now, updated_by = :uid" in str(revoke_call.args[0])
    assert "update_time = :now" in str(revoke_call.args[0])
