# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Isolated password compatibility and source mapping regressions."""

from datetime import datetime
from uuid import uuid4

import bcrypt
import pytest

from infrastructure.security.passwords import (
    hash_password,
    password_scheme,
    verify_password,
)
from deploy.sql.tools.supabase_to_postgres.migration import MigrationConflict, map_source_user


def source_user(**overrides):
    return dict(
        id=str(uuid4()),
        email="User@Example.com",
        encrypted_password=hash_password("OldPassword123"),
        created_at="2020-01-02T03:04:05Z",
        updated_at="2021-02-03T04:05:06Z",
        email_confirmed_at="2020-01-02T03:04:05Z",
        **overrides,
    )


def test_scrypt_salted_and_full_password_verified():
    first = hash_password("Password123")
    assert first != hash_password("Password123")
    assert password_scheme(first) == "scrypt"
    assert verify_password("Password123", first)
    assert not verify_password("Password124", first)
    assert "Password123" not in first


@pytest.mark.parametrize("prefix", ["2a", "2b", "2y"])
def test_imported_bcrypt_original_password_and_legacy_byte_limit(prefix):
    encoded = bcrypt.hashpw(b"LegacyPassword123", bcrypt.gensalt(rounds=4)).decode()
    encoded = "$" + prefix + encoded[3:]
    assert password_scheme(encoded) == "bcrypt"
    assert verify_password("LegacyPassword123", encoded)
    assert not verify_password("wrong", encoded)
    long_hash = bcrypt.hashpw(b"a" * 72, bcrypt.gensalt(rounds=4)).decode()
    assert verify_password("a" * 72 + "tail", long_hash)


@pytest.mark.parametrize("password", ["", "a" * 1025])
def test_password_byte_boundaries(password):
    with pytest.raises(ValueError):
        hash_password(password)
    assert not verify_password(password, hash_password("Valid123"))


@pytest.mark.parametrize(
    "encoded",
    [
        "plaintext",
        "$2b$31$" + "a" * 53,
        "scrypt$999999999$8$1$AAAA$AAAA",
        "scrypt$16384$8$1$?$?",
    ],
)
def test_malformed_or_unbounded_hashes_rejected(encoded):
    assert not verify_password("Password123", encoded)
    with pytest.raises(ValueError):
        password_scheme(encoded)


def test_source_mapping_preserves_identity_hash_times_and_separates_roles():
    row = source_user(raw_app_meta_data={"role": "admin"})
    mapped = map_source_user(row)
    assert mapped["user_id"] == row["id"]
    assert mapped["password_hash"] == row["encrypted_password"]
    assert mapped["email"] == "user@example.com"
    assert mapped["create_time"] == datetime(2020, 1, 2, 3, 4, 5)
    assert "user_role" not in mapped
    assert mapped["source_metadata"]["raw_app_meta_data"] == {"role": "admin"}


@pytest.mark.parametrize(
    "extra",
    [
        {"deleted_at": "2025-01-01T00:00:00Z"},
        {"banned_until": "2999-01-01T00:00:00Z"},
        {"is_anonymous": True},
    ],
)
def test_inactive_source_users_stay_disabled(extra):
    assert map_source_user(source_user(**extra))["account_status"] == "disabled"


def test_cas_generated_password_does_not_enable_password_login():
    row = source_user(raw_user_meta_data={"provider": "cas"})
    assert not map_source_user(row)["password_login_enabled"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "bad-id"),
        ("encrypted_password", "secret-plaintext"),
        ("email", ""),
        ("created_at", "yesterday"),
    ],
)
def test_source_validation_errors_do_not_expose_credentials(field, value):
    row = source_user()
    row[field] = value
    with pytest.raises(MigrationConflict) as error:
        map_source_user(row)
    assert "secret-plaintext" not in str(error.value)
    assert row.get("encrypted_password", "") not in str(error.value)


def test_migration_cli_rejects_missing_password_without_connecting(monkeypatch, mocker, capsys):
    from deploy.sql.tools.supabase_to_postgres import migrate

    mocker.patch.object(migrate, "load_settings", return_value={})
    monkeypatch.setattr("sys.argv", ["migrate.py"])
    connect = mocker.patch("psycopg2.connect")
    assert migrate.main() == 1
    connect.assert_not_called()
    assert "SUPABASE_POSTGRES_PASSWORD" in capsys.readouterr().err


def test_migration_cli_hides_database_connection_details(monkeypatch, mocker, capsys):
    from deploy.sql.tools.supabase_to_postgres import migrate

    secret = "private-source-dsn-marker"
    mocker.patch.object(migrate, "load_settings", return_value={
        "SUPABASE_POSTGRES_HOST": secret,
        "SUPABASE_POSTGRES_PASSWORD": "source-secret",
        "NEXENT_POSTGRES_PASSWORD": "target-secret",
    })
    monkeypatch.setattr("sys.argv", ["migrate.py", "--apply"])
    mocker.patch("psycopg2.connect", side_effect=RuntimeError(secret))
    assert migrate.main() == 1
    output = capsys.readouterr()
    assert "RuntimeError" in output.err
    assert secret not in output.out + output.err
