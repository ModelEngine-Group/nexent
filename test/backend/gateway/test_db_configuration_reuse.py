# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Gateway consumes the existing PostgreSQL connection configuration directly."""

import pytest

from gateway.configuration import load_settings


BASE = {"POSTGRES_HOST": "existing-db", "POSTGRES_PORT": "5544", "POSTGRES_DB": "existing",
        "POSTGRES_USER": "existing-user", "NEXENT_POSTGRES_PASSWORD": "existing-secret"}


def test_existing_postgresql_connection_is_used_directly():
    settings = load_settings(BASE)
    assert settings.database_options() == dict(host="existing-db", port=5544, database="existing",
        user="existing-user", password="existing-secret", max_size=8, timeout=5)
    assert "existing-secret" not in repr(settings)


def test_empty_postgresql_uses_defaults_without_default_password():
    settings = load_settings(dict.fromkeys(BASE, ""))
    assert (settings.db_host, settings.db_port, settings.db_name, settings.db_user) == ("localhost", 5432, "nexent", "root")
    with pytest.raises(ValueError, match="password"):
        settings.database_options()


@pytest.mark.parametrize("value", ["wrong", "0", "65536"])
def test_invalid_postgres_port_fails(value):
    with pytest.raises(ValueError):
        load_settings(BASE | {"POSTGRES_PORT": value})


def test_password_is_required():
    with pytest.raises(ValueError, match="password"):
        load_settings(BASE | {"NEXENT_POSTGRES_PASSWORD": ""}).database_options()
