# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Existing source container startup and sanitized Docker failures."""

import json
import subprocess
from unittest.mock import MagicMock

import pytest

from deploy.sql.tools.supabase_to_postgres import migrate as runtime
from deploy.sql.tools.supabase_to_postgres.migrate import MigrationSetupError


@pytest.mark.parametrize("running", [True, False])
def test_existing_source_only_starts_when_stopped(mocker, running):
    state = {"running": running, "ports": {"5436/tcp": [{"HostIp": "0.0.0.0", "HostPort": "15436"}]}}
    docker = mocker.patch.object(runtime, "_docker", side_effect=["supabase_db\n", json.dumps(state), "supabase_db", json.dumps(state)])
    params = {"host": "127.0.0.1", "port": 5436}
    runtime.prepare_source(params)
    assert params == {"host": "127.0.0.1", "port": 15436}
    commands = [call.args[0] for call in docker.call_args_list]
    assert commands == (["ps", "inspect"] if running else ["ps", "inspect", "start", "inspect"])


def test_selected_container_skips_discovery_and_ipv6_binding(mocker):
    state = {"running": True, "ports": {"5432/tcp": [
        {"HostIp": "::", "HostPort": "5436"}, {"HostIp": "127.0.0.1", "HostPort": "5436"}]}}
    docker = mocker.patch.object(runtime, "_docker", return_value=json.dumps(state))
    params = {"port": 5436}
    runtime.prepare_source(params, "selected")
    assert docker.call_args.args[-1] == "selected"
    assert params["host"] == "127.0.0.1" and params["port"] == 5436


@pytest.mark.parametrize("names", ["", "supabase_db\nsupabase-db-mini\n"])
def test_missing_or_ambiguous_containers_never_create_empty_database(mocker, names):
    docker = mocker.patch.object(runtime, "_docker", return_value=names)
    with pytest.raises(MigrationSetupError, match="No empty database"):
        runtime.prepare_source({"port": 5436})
    docker.assert_called_once()


def test_no_start_option_preserves_stopped_container(mocker):
    docker = mocker.patch.object(runtime, "_docker", return_value=json.dumps({"running": False}))
    with pytest.raises(MigrationSetupError, match="stopped"):
        runtime.prepare_source({"port": 5436}, "source", allow_start=False)
    docker.assert_called_once()


def test_missing_port_is_actionable(mocker):
    mocker.patch.object(runtime, "_docker", return_value=json.dumps({"running": True, "ports": None}))
    with pytest.raises(MigrationSetupError, match="published PostgreSQL port"):
        runtime.prepare_source({"port": 5436}, "source")


@pytest.mark.parametrize("error", [OSError("private-path"), subprocess.TimeoutExpired("private", 20)])
def test_docker_unavailable_errors_are_sanitized(mocker, error):
    mocker.patch.object(runtime.subprocess, "run", side_effect=error)
    with pytest.raises(MigrationSetupError) as raised:
        runtime._docker("ps")
    assert "private" not in str(raised.value)


def test_docker_failure_does_not_expose_stderr(mocker):
    mocker.patch.object(runtime.subprocess, "run", return_value=MagicMock(returncode=1, stderr="private-password"))
    with pytest.raises(MigrationSetupError) as raised:
        runtime._docker("start", "source")
    assert "private-password" not in str(raised.value)


def test_malformed_inspect_data_is_sanitized(mocker):
    mocker.patch.object(runtime, "_docker", return_value="private-password")
    with pytest.raises(MigrationSetupError, match="Cannot read source"):
        runtime.prepare_source({"port": 5436}, "source")


def test_managed_source_connection_wait_is_bounded(mocker, monkeypatch, capsys):
    import psycopg2
    from deploy.sql.tools.supabase_to_postgres import migrate

    mocker.patch.object(migrate, "load_settings", return_value={})
    mocker.patch.object(migrate, "connections", return_value=({"password": "secret"}, {}, True))
    prepare = mocker.patch.object(migrate, "prepare_source")
    mocker.patch.object(migrate.time, "monotonic", side_effect=[0, 100])
    mocker.patch("psycopg2.connect", side_effect=psycopg2.OperationalError("secret"))
    monkeypatch.setattr("sys.argv", ["migrate.py", "--wait-timeout", "1"])
    assert migrate.main() == 1
    prepare.assert_called_once()
    output = capsys.readouterr().err
    assert "Cannot connect to source PostgreSQL" in output
    assert "secret" not in output


def test_explicit_source_never_starts_a_container(mocker, monkeypatch):
    from deploy.sql.tools.supabase_to_postgres import migrate

    mocker.patch.object(migrate, "load_settings", return_value={})
    mocker.patch.object(migrate, "connections", return_value=({}, {}, False))
    prepare = mocker.patch.object(migrate, "prepare_source")
    mocker.patch("psycopg2.connect", side_effect=RuntimeError("stop"))
    monkeypatch.setattr("sys.argv", ["migrate.py"])
    assert migrate.main() == 1
    prepare.assert_not_called()
