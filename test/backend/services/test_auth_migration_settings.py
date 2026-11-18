# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared environment precedence and container-address migration settings."""

import pytest

from deploy.sql.tools.supabase_to_postgres import migrate_docker as worker
from test.backend.services.migration_shell_fixture import run_migration


def test_managed_sources_use_internal_container_ports(tmp_path):
    result = run_migration(tmp_path, values={"POSTGRES_PORT": "5544", "SUPABASE_POSTGRES_PORT": "5545"})
    assert result.code == 0, result.stderr
    assert result.connections["target_host"] == "10.0.0.2"
    assert result.connections["source_host"] == "10.0.0.3"
    assert result.connections["target_port"] == result.connections["source_port"] == "5432"


def test_environment_overrides_deployment_file(tmp_path):
    result = run_migration(tmp_path, env_text="SUPABASE_POSTGRES_PASSWORD=file-value\nPOSTGRES_USER=file-user\n")
    assert result.code == 0, result.stderr
    assert result.connections["target_user"] == "root"
    assert result.connections["secret_match"] == "source-secret-matched"


@pytest.mark.parametrize("host", ["supabase_db", "supabase-db-mini", "nexent-supabase-db"])
def test_service_hostnames_resolve_original_container(tmp_path, host):
    result = run_migration(tmp_path, values={"SUPABASE_POSTGRES_HOST": host})
    assert result.code == 0, result.stderr
    assert result.connections["source_host"] == "10.0.0.3"


def test_external_connection_fields_are_preserved(tmp_path):
    result = run_migration(tmp_path, values={"SUPABASE_POSTGRES_HOST": "archive.example",
        "SUPABASE_POSTGRES_PORT": "1234", "SUPABASE_POSTGRES_DB": "archive", "SUPABASE_POSTGRES_USER": "reader"})
    assert result.code == 0, result.stderr
    assert [result.connections[key] for key in ("source_host", "source_port", "source_db", "source_user")] == ["archive.example", "1234", "archive", "reader"]


@pytest.mark.parametrize("key", ["SUPABASE_POSTGRES_PASSWORD", "NEXENT_POSTGRES_PASSWORD"])
def test_missing_password_fails_without_echoing_input(tmp_path, key):
    result = run_migration(tmp_path, values={key: None})
    assert result.code != 0
    assert "password" in result.stderr
    assert "private-source" not in result.stdout + result.stderr
    assert "private-target" not in result.stdout + result.stderr
    assert not any(command[1:2] == ["create"] for command in result.commands)


@pytest.mark.parametrize("port", ["bad", "0", "65536"])
def test_invalid_port_is_rejected_by_database_worker(port):
    with pytest.raises(worker.MigrationSetupError):
        worker._port(port)
