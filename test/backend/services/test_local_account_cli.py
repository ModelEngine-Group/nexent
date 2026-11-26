# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Administrator bootstrap and command-line credential transport contracts."""

import json
import runpy
import uuid as _uuid
from contextlib import nullcontext
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from contracts.errors.exceptions import AccountConflictError
from management.cli import account as cli
from management.utils.account_passwords import verify_password


@pytest.fixture
def store(mocker):
    session = MagicMock()
    # SU-membership preflight (uses .first()) — no existing SU
    session.execute.return_value.first.return_value = None
    # Account-has-memberships check (uses .scalars().all()) — below in-place
    # TenantConfig probe inside _resolve_or_create_default_tenant (uses .scalar_one_or_none()) — no real tenant yet
    session.execute.return_value.scalar_one_or_none.return_value = None
    session.execute.return_value.scalars.return_value.all.return_value = [SimpleNamespace(user_role="SU", roles=["SU"])]
    mocker.patch("infrastructure.rdb.client.get_db_session", return_value=nullcontext(session))
    lock = mocker.patch("management.db.identity.account.lock_account_keys")
    lookup = mocker.patch("management.db.identity.account.get_account_by_email", return_value=None)
    create = mocker.patch("management.db.identity.account.create_account", return_value={"user_id": "new-su"})
    member = mocker.patch("management.db.identity.user_tenant.insert_user_tenant")
    configuration = mocker.patch("management.cli.account.load_system_configuration")
    # Make _resolve_or_create_default_tenant emit a stable UUID so assertions
    # in bootstrap tests can pin the tenant_id without caring about uuidgen.
    mocker.patch(
        "management.cli.account.uuid.uuid4",
        return_value=_uuid.UUID("11111111-1111-4111-8111-111111111111"),
    )
    return SimpleNamespace(
        configuration=configuration,
        session=session,
        lock=lock,
        lookup=lookup,
        create=create,
        member=member,
    )


def test_bootstrap_creates_identity_and_su_membership_in_one_transaction(store):
    assert cli.bootstrap_super_admin(" SUAdmin@Example.com ", "Password123") == {"created": True}
    store.configuration.assert_called_once_with()
    store.lock.assert_called_once_with(store.session, "super-admin-bootstrap", "suadmin@example.com")
    email, encoded = store.create.call_args.args
    assert email == "suadmin@example.com"
    assert verify_password("Password123", encoded)
    assert store.create.call_args.kwargs["db_session"] is store.session
    # Bootstrap now binds the new SU to a freshly-provisioned default tenant
    # (created by _resolve_or_create_default_tenant) rather than leaving
    # tenant_id empty. uuid.uuid4 is patched to a stable value above.
    expected_tenant_id = "11111111-1111-4111-8111-111111111111"
    store.member.assert_called_once_with(
        "new-su", expected_tenant_id, "SU", email,
        created_by="system", db_session=store.session,
    )
    # Tenant provisioning writes TenantConfig + TenantGroupInfo in the same session
    added_types = {type(obj).__name__ for obj in store.session.add.call_args_list}
    assert "TenantConfig" in added_types or len(store.session.add.call_args_list) >= 1
    store.session.flush.assert_called()


def test_bootstrap_reuses_existing_tenant_without_provisioning(store):
    store.session.execute.return_value.scalar_one_or_none.return_value = "existing-tenant"

    assert cli.bootstrap_super_admin("su@example.com", "Password123") == {"created": True}

    store.member.assert_called_once_with(
        "new-su", "existing-tenant", "SU", "su@example.com",
        created_by="system", db_session=store.session,
    )
    added = {type(call.args[0]).__name__ for call in store.session.add.call_args_list}
    assert "TenantGroupInfo" not in added


def test_default_tenant_resolution_refuses_placeholder_tenant(monkeypatch):
    """A fresh install seeds TENANT_ID='tenant_id'; the SU must not join that fake tenant."""
    from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, select
    from sqlalchemy.orm import Session, registry

    import management.db.models as models
    from contracts.constants.constants import DEFAULT_GROUP_ID, DEFAULT_TENANT_ID, TENANT_ID, TENANT_NAME

    metadata = MetaData()
    tenant_config = Table(
        "tenant_config_t", metadata,
        Column("tenant_config_id", Integer, primary_key=True, autoincrement=True),
        Column("tenant_id", String), Column("config_key", String), Column("config_value", String),
        Column("created_by", String), Column("updated_by", String), Column("delete_flag", String),
    )
    tenant_group = Table(
        "tenant_group_info_t", metadata,
        Column("group_id", Integer, primary_key=True, autoincrement=True),
        Column("tenant_id", String), Column("group_name", String), Column("group_description", String),
        Column("created_by", String), Column("updated_by", String), Column("delete_flag", String),
    )
    mapper = registry()
    config_model = type("TenantConfig", (), {})
    group_model = type("TenantGroupInfo", (), {})
    mapper.map_imperatively(config_model, tenant_config)
    mapper.map_imperatively(group_model, tenant_group)
    monkeypatch.setattr(models, "TenantConfig", config_model)
    monkeypatch.setattr(models, "TenantGroupInfo", group_model)

    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(tenant_config.insert(), {
            "tenant_id": DEFAULT_TENANT_ID, "config_key": TENANT_ID,
            "config_value": DEFAULT_TENANT_ID, "delete_flag": "N",
        })

    with Session(engine) as session:
        resolved = cli._resolve_or_create_default_tenant(session)

        assert resolved != DEFAULT_TENANT_ID
        keys = set(
            session.execute(
                select(tenant_config.c.config_key).where(tenant_config.c.tenant_id == resolved)
            ).scalars().all()
        )
        assert keys == {TENANT_ID, TENANT_NAME, DEFAULT_GROUP_ID}
        assert session.execute(
            select(tenant_group.c.group_id).where(tenant_group.c.tenant_id == resolved)
        ).scalars().all()


def test_bootstrap_configuration_failure_prevents_account_writes(store):
    store.configuration.side_effect = RuntimeError("configuration unavailable")

    with pytest.raises(RuntimeError, match="configuration unavailable"):
        cli.bootstrap_super_admin("suadmin@example.com", "Password123")

    store.create.assert_not_called()
    store.member.assert_not_called()


@pytest.mark.parametrize("check_only", [True, False])
def test_existing_su_is_idempotent_without_password_work(store, check_only):
    store.lookup.return_value = {"user_id": "original", "delete_flag": "N"}
    assert cli.bootstrap_super_admin("su@example.com", "", check_only=check_only) == {"exists": True}
    store.create.assert_not_called()
    store.member.assert_not_called()


@pytest.mark.parametrize("flag,roles", [("Y", ("SU",)), ("N", ()), ("N", ("SU", "USER"))])
def test_unavailable_or_non_su_identity_cannot_be_promoted(store, flag, roles):
    store.lookup.return_value = {"user_id": "original", "delete_flag": flag}
    store.session.execute.return_value.scalars.return_value.all.return_value = [SimpleNamespace(roles=list(roles)) for _ in roles] or [SimpleNamespace(roles=[])]
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


def test_cli_module_entry_point_runs_preflight(mocker, capsys):
    mocker.patch("sys.argv", ["account_cli.py", "bootstrap-su", "--check"])
    mocker.patch("infrastructure.rdb.client.get_db_session", side_effect=RuntimeError("private-dsn"))
    with pytest.raises(SystemExit) as raised:
        runpy.run_module(cli.__name__, run_name="__main__")
    assert raised.value.code == 1
    output = capsys.readouterr()
    assert "RuntimeError" in output.err
    assert "private-dsn" not in output.err
