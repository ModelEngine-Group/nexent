# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Host migration endpoints and credential precedence regressions."""

from pathlib import Path

import pytest

from deploy.sql.tools.supabase_to_postgres import migrate_docker as settings


@pytest.fixture
def values():
    return {"SUPABASE_POSTGRES_PASSWORD": "source", "NEXENT_POSTGRES_PASSWORD": "target"}


def test_host_defaults(values, mocker):
    prompt = mocker.patch.object(settings.getpass, "getpass")
    source, target, managed = settings.connections(values)
    assert (source["host"], source["port"]) == ("127.0.0.1", 5436)
    assert (target["host"], target["port"]) == ("127.0.0.1", 5434)
    assert managed
    prompt.assert_not_called()


def test_environment_overrides_deployment_file(mocker):
    mocker.patch.object(Path, "is_file", return_value=True)
    mocker.patch("dotenv.dotenv_values", return_value={"SUPABASE_POSTGRES_PASSWORD": "file", "POSTGRES_USER": "root"})
    result = settings.load_settings(Path("config.env"), {"SUPABASE_POSTGRES_PASSWORD": "exported"})
    assert result == {"SUPABASE_POSTGRES_PASSWORD": "exported", "POSTGRES_USER": "root"}


def test_missing_env_file_is_optional(mocker):
    mocker.patch.object(Path, "is_file", return_value=False)
    assert settings.load_settings(Path("missing"), {"ONE": "value"}) == {"ONE": "value"}


@pytest.mark.parametrize("host", ["supabase_db", "supabase-db-mini", "nexent-supabase-db"])
def test_service_hostnames_map_to_published_host_ports(values, host):
    source, target, managed = settings.connections({**values, "SUPABASE_POSTGRES_HOST": host,
                                                 "POSTGRES_HOST": "nexent-postgresql", "POSTGRES_PORT": "5432"})
    assert source["host"] == target["host"] == "127.0.0.1"
    assert target["port"] == 5434
    assert managed


def test_existing_connection_fields(values):
    source, target, managed = settings.connections({**values,
        "SUPABASE_POSTGRES_HOST": "archive.example", "SUPABASE_POSTGRES_PORT": "1234",
        "SUPABASE_POSTGRES_DB": "archive", "SUPABASE_POSTGRES_USER": "reader",
        "POSTGRES_HOST": "target.example", "POSTGRES_PORT": "2345",
    })
    assert (source["host"], source["port"], source["dbname"], source["user"]) == ("archive.example", 1234, "archive", "reader")
    assert (target["host"], target["port"]) == ("target.example", 2345)
    assert not managed


def test_missing_source_password_prompts_hidden(values, mocker):
    values.pop("SUPABASE_POSTGRES_PASSWORD")
    mocker.patch.object(settings.sys.stdin, "isatty", return_value=True)
    prompt = mocker.patch.object(settings.getpass, "getpass", return_value="interactive")
    assert settings.connections(values)[0]["password"] == "interactive"
    prompt.assert_called_once()


@pytest.mark.parametrize("interactive", [True, False])
def test_missing_password_fails_without_echoing_input(values, interactive, mocker):
    values.pop("SUPABASE_POSTGRES_PASSWORD")
    mocker.patch.object(settings.sys.stdin, "isatty", return_value=interactive)
    mocker.patch.object(settings.getpass, "getpass", return_value="")
    with pytest.raises(settings.MigrationSetupError):
        settings.connections(values)


@pytest.mark.parametrize("port", ["bad", "0", "65536"])
def test_invalid_port_rejected(values, port):
    with pytest.raises(settings.MigrationSetupError):
        settings.connections({**values, "SUPABASE_POSTGRES_PORT": port})


def test_missing_target_password_rejected(values):
    values.pop("NEXENT_POSTGRES_PASSWORD")
    with pytest.raises(settings.MigrationSetupError, match="NEXENT_POSTGRES_PASSWORD"):
        settings.connections(values)
