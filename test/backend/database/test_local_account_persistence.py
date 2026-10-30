# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Account persistence contracts with only the database connection isolated."""

from contextlib import nullcontext
from uuid import UUID
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from contracts.errors.exceptions import AccountConflictError
from infrastructure.security.passwords import hash_password
from management.db.identity import account
from management.db.models import UserAccount


@pytest.fixture
def session(mocker):
    session = MagicMock()
    mocker.patch.object(account, "get_db_session", side_effect=lambda existing=None: nullcontext(existing or session))
    session.execute.return_value.scalars.return_value.all.return_value = []
    return session


def compiled(statement):
    return statement.compile(dialect=postgresql.dialect())


def test_account_locks_serialize_import_and_use_stable_identity_order(session):
    account.lock_account_keys(session, "identity", "user@example.com")
    calls = session.execute.call_args_list
    assert "pg_advisory_xact_lock_shared" in str(calls[0].args[0])
    assert [call.args[1]["key"] for call in calls[1:]] == [
        "account-email:user@example.com", "account-id:identity",
    ]


@pytest.mark.parametrize("lookup,value,field", [
    (account.get_account, "identity", "user_id"),
    (account.get_account_by_email, " User@Example.COM ", "user_email"),
])
def test_account_lookup_returns_active_row_with_normalized_identity(session, lookup, value, field):
    session.execute.return_value.scalars.return_value.all.return_value = [
        UserAccount(user_id="identity", user_email="user@example.com")
    ]
    result = lookup(value, session)
    assert result["user_id"] == "identity"
    assert result["email"] == "user@example.com"
    query = compiled(session.execute.call_args.args[0])
    assert query.params[field + "_1"] == ("identity" if field == "user_id" else "user@example.com")
    assert query.params["delete_flag_1"] == "N"


def test_missing_account_lookup_returns_none(session):
    assert account.get_account("missing", session) is None


def test_ambiguous_accounts_are_rejected(session):
    session.execute.return_value.scalars.return_value.all.return_value = [object(), object()]
    with pytest.raises(AccountConflictError, match="Ambiguous"):
        account.get_account("ambiguous", session)


@pytest.mark.parametrize("email", ["", "a" * 256, "invalid", "a@@example.com", "a @example.com"])
def test_invalid_email_never_writes_an_account(session, email):
    with pytest.raises(ValueError, match="Invalid account email"):
        account.create_account(email, db_session=session)
    session.add.assert_not_called()


@pytest.mark.parametrize("duplicate_by", ["get_account", "get_account_by_email"])
def test_duplicate_id_or_email_never_creates_account(session, mocker, duplicate_by):
    mocker.patch.object(account, duplicate_by, return_value={"user_id": "existing"})
    with pytest.raises(AccountConflictError, match="Email already exists"):
        account.create_account("user@example.com", user_id="identity", db_session=session)
    session.add.assert_not_called()


@pytest.mark.parametrize("password_enabled", [True, False])
def test_create_account_preserves_hash_or_disables_provider_only_password(session, password_enabled):
    encoded = hash_password("Password123") if password_enabled else None
    result = account.create_account(" User@Example.COM ", encoded, db_session=session)
    stored = session.add.call_args.args[0]
    assert str(UUID(result["user_id"])) == result["user_id"]
    assert stored.user_email == "user@example.com"
    assert stored.password_hash == encoded
    assert stored.password_login_enabled is password_enabled
    assert stored.password_hash_scheme == ("scrypt" if password_enabled else None)
    assert stored.token_version == 0
    assert stored.account_status == "active"
    assert stored.delete_flag == "N"
    assert stored.email_confirmed_at is not None
    assert stored.created_by == stored.updated_by == result["user_id"]
    session.flush.assert_called_once()


def test_create_account_keeps_explicit_identity(session):
    assert account.create_account("user@example.com", user_id="original", db_session=session)["user_id"] == "original"


def test_explicit_api_only_account_has_no_email_or_password(session):
    result = account.create_account(None, user_id="api-user", api_only=True, created_by="admin", db_session=session)
    stored = session.add.call_args.args[0]
    assert result["user_id"] == "api-user"
    assert stored.user_email is stored.password_hash is stored.password_hash_scheme is stored.email_confirmed_at is None
    assert stored.account_status == "active" and stored.password_login_enabled is False
    assert stored.source_metadata == {"api_only": True}
    assert stored.created_by == stored.updated_by == "admin"
    assert all("account-email:None" not in str(call) for call in session.execute.call_args_list)


@pytest.mark.parametrize("email,encoded", [("api@example.com", None), (None, "hash")])
def test_api_only_mode_cannot_smuggle_password_credentials(session, email, encoded):
    with pytest.raises(ValueError, match="API-only"):
        account.create_account(email, encoded, api_only=True, db_session=session)
    session.add.assert_not_called()


def test_normal_account_creation_still_requires_email(session):
    with pytest.raises(ValueError, match="Invalid account email"):
        account.create_account(None, db_session=session)
    session.add.assert_not_called()


def test_delete_account_disables_login_and_invalidates_existing_tokens(session):
    account.delete_account("identity", session)
    query = compiled(session.execute.call_args.args[0])
    assert query.params["delete_flag"] == "Y"
    assert query.params["account_status"] == "disabled"
    assert query.params["password_hash"] is None
    assert query.params["password_login_enabled"] is False
    assert query.params["updated_by"] == "identity"
    assert "token_version=(nexent.user_account_t.token_version +" in str(query)
    assert query.params["delete_flag_1"] == "N"


@pytest.mark.parametrize("rowcount,changed", [(1, True), (0, False)])
def test_password_update_compares_old_hash_and_increments_token_version(session, rowcount, changed):
    session.execute.return_value.rowcount = rowcount
    encoded = hash_password("NewPassword456")
    assert account.change_password("identity", "old-hash", encoded) is changed
    query = compiled(session.execute.call_args.args[0])
    assert query.params["password_hash_1"] == "old-hash"
    assert query.params["account_status_1"] == "active"
    assert query.params["delete_flag_1"] == "N"
    assert query.params["password_hash"] == encoded
    assert query.params["password_hash_scheme"] == "scrypt"
    assert query.params["password_login_enabled"] is True
    assert "token_version=(nexent.user_account_t.token_version +" in str(query)


@pytest.mark.parametrize("existing", [None, {"user_id": "identity"}])
def test_profile_email_change_normalizes_and_keeps_current_identity(session, mocker, existing):
    mocker.patch.object(account, "get_account", return_value={"user_id": "identity"})
    lookup = mocker.patch.object(account, "get_account_by_email", return_value=existing)
    account.set_account_profile("identity", "DEV", " Updated@Example.COM ", "actor", session)
    lookup.assert_called_once_with("updated@example.com", session)
    query = compiled(session.execute.call_args.args[0])
    assert query.params["user_email"] == "updated@example.com"
    assert query.params["user_role"] == "DEV"
    assert query.params["updated_by"] == "actor"
