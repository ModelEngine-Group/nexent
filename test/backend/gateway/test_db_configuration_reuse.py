# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PostgreSQL credentials are reused unless a nonempty Gateway override is given."""

import pytest

from gateway.configuration import load_settings


BASE = {"POSTGRES_HOST": "existing-db", "POSTGRES_PORT": "5544", "POSTGRES_DB": "existing",
        "POSTGRES_USER": "existing-user", "NEXENT_POSTGRES_PASSWORD": "existing-secret"}
OVERRIDES = {"GATEWAY_DB_HOST": "reader-db", "GATEWAY_DB_PORT": "5545", "GATEWAY_DB_NAME": "identities",
             "GATEWAY_DB_USER": "reader", "GATEWAY_DB_PASSWORD": "reader-secret"}


def test_existing_postgresql_connection_is_reused():
    options = load_settings(BASE).database_options()
    assert options == dict(host="existing-db", port=5544, database="existing", user="existing-user",
                           password="existing-secret", max_size=8, timeout=5)
    assert "existing-secret" not in repr(load_settings(BASE))


def test_nonempty_gateway_overrides_win():
    options = load_settings(BASE | OVERRIDES).database_options()
    assert options == dict(host="reader-db", port=5545, database="identities", user="reader",
                           password="reader-secret", max_size=8, timeout=5)
    assert "reader-secret" not in repr(load_settings(BASE | OVERRIDES))


@pytest.mark.parametrize("empty", ["", None])
def test_empty_gateway_overrides_reuse_postgresql(empty):
    assert load_settings(BASE | dict.fromkeys(OVERRIDES, empty)).database_options() == load_settings(BASE).database_options()


def test_empty_postgresql_uses_existing_defaults_without_default_password():
    settings = load_settings(dict.fromkeys(BASE, ""))
    assert (settings.db_host, settings.db_port, settings.db_name, settings.db_user) == ("localhost", 5432, "nexent", "root")
    with pytest.raises(ValueError, match="password"):
        settings.database_options()


def test_password_override_is_independent_and_missing_effective_password_fails():
    assert load_settings(BASE | {"GATEWAY_DB_PASSWORD": "override"}).database_options()["password"] == "override"
    with pytest.raises(ValueError, match="password"):
        load_settings({"POSTGRES_USER": "existing-user"}).database_options()


@pytest.mark.parametrize("name,value", [("POSTGRES_PORT", "wrong"), ("POSTGRES_PORT", "0")])
def test_invalid_effective_postgres_port_fails(name, value):
    with pytest.raises(ValueError):
        load_settings(BASE | {name: value})
