# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Administrator bootstrap and command-line credential transport contracts."""

from contextlib import nullcontext
from io import StringIO
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from contracts.errors.exceptions import AccountConflictError
from infrastructure.security import account_cli as cli
from infrastructure.security.passwords import verify_password


@pytest.fixture
def store(mocker):
    session = MagicMock()
    session.execute.return_value.first.return_value = None
    session.execute.return_value.scalars.return_value.all.return_value = [SimpleNamespace(user_role="SU")]
    mocker.patch("management.db.client.get_db_session", return_value=nullcontext(session))
    lock = mocker.patch("management.db.identity.account.lock_account_keys")
    lookup = mocker.patch("management.db.identity.account.get_account_by_email", return_value=None)
    create = mocker.patch("management.db.identity.account.create_account", return_value={"user_id": "new-su"})
    member = mocker.patch("management.db.identity.user_tenant.insert_user_tenant")
    return SimpleNamespace(session=session, lock=lock, lookup=lookup, create=create, member=member)


def test_bootstrap_creates_identity_and_su_membership_in_one_transaction(store):
    assert cli.bootstrap_super_admin(" SUAdmin@Example.com ", "Password123") == {"created": True}
    store.lock.assert_called_once_with(store.session, "super-admin-bootstrap", "suadmin@example.com")
    email, encoded = store.create.call_args.args
    assert email == "suadmin@example.com"
    assert verify_password("Password123", encoded)
    assert store.create.call_args.kwargs["db_session"] is store.session
    store.member.assert_called_once_with("new-su", "", "SU", email, created_by="system", db_session=store.session)


@pytest.mark.parametrize("check_only", [True, False])
def test_existing_su_is_idempotent_without_password_work(store, check_only):
    store.lookup.return_value = {"user_id": "original", "account_status": "active"}
    assert cli.bootstrap_super_admin("su@example.com", "", check_only=check_only) == {"exists": True}
    store.create.assert_not_called()
    store.member.assert_not_called()


@pytest.mark.parametrize("status,roles", [("disabled", ["SU"]), ("active", []), ("active", ["SU", "USER"])])
def test_unavailable_or_non_su_identity_cannot_be_promoted(store, status, roles):
    store.lookup.return_value = {"user_id": "original", "account_status": status}
    store.session.execute.return_value.scalars.return_value.all.return_value = [SimpleNamespace(user_role=r) for r in roles]
    with pytest.raises(AccountConflictError, match="unavailable or non-SU"):
        cli.bootstrap_super_admin("su@example.com", "Password123")
    store.create.assert_not_called()


@pytest.mark.parametrize("password", ["Aa1", "password123", "PASSWORD123", "PasswordOnly"])
def test_bootstrap_rejects_weak_password_before_writing(store, password):
    with pytest.raises(ValueError, match="uppercase, lowercase and digit"):
        cli.bootstrap_super_admin("su@example.com", password)
    store.create.assert_not_called()
    store.member.assert_not_called()


@pytest.mark.parametrize("result,code,check", [({"created": True}, 0, False), ({"exists": True}, 0, True), ({"exists": False}, 3, True)])
def test_cli_exit_codes_and_stdin_password_are_stable(mocker, capsys, result, code, check):
    args = ["account_admin.py", "bootstrap-su", "--email", "su@example.com"] + (["--check"] if check else [])
    mocker.patch("sys.argv", args)
    mocker.patch.object(cli.sys, "stdin", StringIO("Password123\r\nignored\n"))
    bootstrap = mocker.patch.object(cli, "bootstrap_super_admin", return_value=result)
    assert cli.main() == code
    bootstrap.assert_called_once_with("su@example.com", "" if check else "Password123", check_only=check)
    output = capsys.readouterr()
    assert json.loads(output.out) == result
    assert output.err == ""
    assert "Password123" not in output.out


@pytest.mark.parametrize("error,expected", [
    (AccountConflictError("Account credentials await migration"), "Account preflight rejected"),
    (RuntimeError("password=private-credential"), "Account operation failed (RuntimeError)"),
])
def test_cli_failure_returns_safe_diagnostics(mocker, capsys, error, expected):
    mocker.patch("sys.argv", ["account_admin.py", "bootstrap-su", "--check"])
    mocker.patch.object(cli, "bootstrap_super_admin", side_effect=error)
    assert cli.main() == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert expected in output.err
    assert "private-credential" not in output.err


def test_container_entry_point_propagates_cli_status(mocker):
    main = mocker.patch.object(cli, "main", return_value=3)
    path = Path(__file__).resolve().parents[3] / "backend/account_admin.py"
    with pytest.raises(SystemExit) as raised:
        runpy.run_path(str(path), run_name="__main__")
    assert raised.value.code == 3
    main.assert_called_once_with()


def test_cli_module_entry_point_runs_preflight(mocker, capsys):
    mocker.patch("sys.argv", ["account_cli.py", "bootstrap-su", "--check"])
    mocker.patch("management.db.client.get_db_session", side_effect=RuntimeError("private-dsn"))
    with pytest.raises(SystemExit) as raised:
        runpy.run_module(cli.__name__, run_name="__main__")
    assert raised.value.code == 1
    output = capsys.readouterr()
    assert "RuntimeError" in output.err
    assert "private-dsn" not in output.err
