# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""SU preflight must not report a historical membership as an empty installation."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from contracts.errors.exceptions import AccountConflictError
from infrastructure.security.account_cli import bootstrap_super_admin


@pytest.mark.parametrize("check_only", [True, False])
def test_existing_su_blocks_before_missing_or_password_branch(mocker, check_only):
    session = MagicMock()
    session.execute.return_value.first.return_value = ("original-su-id",)

    @contextmanager
    def transaction():
        yield session

    mocker.patch("management.db.client.get_db_session", transaction)
    mocker.patch("management.db.identity.account.lock_account_keys")
    mocker.patch("management.db.identity.account.get_account_by_email", return_value=None)
    create = mocker.patch("management.db.identity.account.create_account")
    with pytest.raises(AccountConflictError, match="migrate_docker.py --apply"):
        bootstrap_super_admin("suadmin@nexent.com", "", check_only=check_only)
    create.assert_not_called()


def test_empty_installation_check_still_reports_absent(mocker):
    session = MagicMock()
    session.execute.return_value.first.return_value = None

    @contextmanager
    def transaction():
        yield session

    mocker.patch("management.db.client.get_db_session", transaction)
    mocker.patch("management.db.identity.account.lock_account_keys")
    mocker.patch("management.db.identity.account.get_account_by_email", return_value=None)
    assert bootstrap_super_admin("suadmin@nexent.com", "", check_only=True) == {"exists": False}


@pytest.mark.parametrize("check_only", [True, False])
def test_pending_account_requires_credentials_before_bootstrap(mocker, check_only):
    mocker.patch("management.db.client.get_db_session", return_value=MagicMock())
    mocker.patch("management.db.identity.account.lock_account_keys")
    mocker.patch("management.db.identity.account.get_account_by_email", return_value={
        "source_metadata": {"credential_migration_pending": True}, "account_status": "disabled",
    })
    create = mocker.patch("management.db.identity.account.create_account")
    with pytest.raises(AccountConflictError, match="migrate_docker.py --apply"):
        bootstrap_super_admin("suadmin@nexent.com", "", check_only=check_only)
    create.assert_not_called()


def test_orphaned_membership_cannot_be_replaced_by_new_default_su(mocker):
    session = MagicMock()
    session.execute.return_value.first.side_effect = [None, ("original-identity",)]

    @contextmanager
    def transaction():
        yield session

    mocker.patch("management.db.client.get_db_session", transaction)
    mocker.patch("management.db.identity.account.lock_account_keys")
    mocker.patch("management.db.identity.account.get_account_by_email", return_value=None)
    create = mocker.patch("management.db.identity.account.create_account")
    with pytest.raises(AccountConflictError, match="original account"):
        bootstrap_super_admin("suadmin@nexent.com", "", check_only=True)
    create.assert_not_called()
