# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Canonical account profile ownership and mutation boundaries."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from contracts.errors.exceptions import AccountConflictError
from management.db.identity import account
from management.db.models import UserAccount, UserTenant


def test_profile_fields_belong_only_to_account_table():
    assert {"user_role", "user_email"} <= set(UserAccount.__table__.columns.keys())
    assert "email" not in UserAccount.__table__.columns
    assert {"user_role", "user_email"}.isdisjoint(UserTenant.__table__.columns.keys())


def test_account_dictionary_preserves_public_email_contract():
    result = account._account_dict(UserAccount(user_id="identity", user_email="user@example.com", user_role="DEV"))
    assert result["email"] == result["user_email"] == "user@example.com"
    assert result["user_role"] == "DEV"


def test_missing_account_profile_rejected(mocker):
    mocker.patch.object(account, "get_account", return_value=None)
    session = MagicMock()
    with pytest.raises(AccountConflictError):
        account.set_account_profile("identity", "ADMIN", None, "actor", session)
    session.execute.assert_not_called()


def test_role_update_writes_account_and_keeps_existing_email(mocker):
    mocker.patch.object(account, "get_account", return_value={"user_id": "identity"})
    session = MagicMock()
    account.set_account_profile("identity", "DEV", None, "actor", session)
    statement = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "UPDATE nexent.user_account_t" in str(statement)
    assert statement.params["user_role"] == "DEV"
    assert "user_email" not in statement.params


def test_duplicate_profile_email_rejected(mocker):
    mocker.patch.object(account, "get_account", return_value={"user_id":"identity"})
    mocker.patch.object(account, "get_account_by_email", return_value={"user_id":"other"})
    mocker.patch.object(account, "lock_account_keys")
    session = MagicMock()
    with pytest.raises(AccountConflictError):
        account.set_account_profile("identity", "USER", "other@example.com", "actor", session)
    session.execute.assert_not_called()
