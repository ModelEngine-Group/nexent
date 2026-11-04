# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Database-only migration worker keeps credentials/transactions inside its container."""
import json
from unittest.mock import MagicMock

import psycopg2
import pytest

from deploy.sql.tools.supabase_to_postgres import migrate_docker as migration


@pytest.fixture
def worker(mocker, monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "target.internal")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("NEXENT_POSTGRES_PASSWORD", "target-private")
    monkeypatch.setenv("SUPABASE_POSTGRES_HOST", "source.internal")
    monkeypatch.setenv("SUPABASE_POSTGRES_PASSWORD", "source-private")
    target, source = MagicMock(), MagicMock()
    target.__enter__.return_value = target
    source.__enter__.return_value = source
    target.cursor.return_value.__enter__.return_value.fetchone.return_value = (False, True)
    connect = mocker.patch("psycopg2.connect", side_effect=[target, source])
    mocker.patch.object(migration, "read_source_users", return_value=[{"identity": "original"}])
    importer = mocker.patch.object(migration, "import_users", return_value={"source": 1})
    mocker.patch.object(migration.subprocess, "run", side_effect=AssertionError("Worker invoked a host CLI"))
    return target, source, connect, importer


@pytest.mark.parametrize("apply", [False, True])
def test_worker_migrates_with_explicit_container_addresses_and_closes_connections(worker, capsys, apply):
    target, source, connect, importer = worker
    arguments = ["--container"] + (["--apply"] if apply else [])
    assert migration.container_main(arguments) == 0
    assert connect.call_args_list[0].kwargs["host"] == "target.internal"
    assert connect.call_args_list[1].kwargs["host"] == "source.internal"
    source.set_session.assert_called_once_with(readonly=True, isolation_level="REPEATABLE READ")
    importer.assert_called_once_with(target, [{"identity": "original"}], dry_run=not apply)
    target.close.assert_called_once()
    source.close.assert_called_once()
    assert json.loads(capsys.readouterr().out) == {"source": 1, "committed": apply}


@pytest.mark.parametrize("state", [(True, True), (False, False)])
def test_worker_rechecks_complete_and_fresh_targets_without_accessing_source(worker, capsys, state):
    target, source, connect, importer = worker
    target.cursor.return_value.__enter__.return_value.fetchone.return_value = state
    assert migration.container_main(["--container", "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["skipped"]
    assert connect.call_count == 1
    importer.assert_not_called()
    source.close.assert_not_called()
    target.close.assert_called_once()


@pytest.mark.parametrize("failure", [migration.MigrationConflict('Account migration conflict IDs: ["original-id"]'), RuntimeError("source-private hash-value")])
def test_worker_failure_rolls_back_and_sanitizes_driver_details(worker, capsys, failure):
    target, _, _, importer = worker
    importer.side_effect = failure
    assert migration.container_main(["--container", "--apply"]) == 1
    target.rollback.assert_called()
    target.close.assert_called_once()
    output = capsys.readouterr()
    assert not output.out
    assert "source-private" not in output.err and "hash-value" not in output.err
    if isinstance(failure, migration.MigrationConflict):
        assert "original-id" in output.err


def test_worker_bounds_source_readiness_and_preserves_target(worker, mocker, capsys):
    target, _, connect, importer = worker
    connect.side_effect = [target, psycopg2.OperationalError("source-private")]
    mocker.patch.object(migration.time, "monotonic", side_effect=[0, 301])
    assert migration.container_main(["--container", "--apply"]) == 1
    importer.assert_not_called()
    target.rollback.assert_called()
    assert "source-private" not in capsys.readouterr().err


def test_worker_rejects_missing_target_secret_before_any_connection(worker, monkeypatch, capsys):
    _, _, connect, _ = worker
    monkeypatch.delenv("NEXENT_POSTGRES_PASSWORD")
    assert migration.container_main(["--container"]) == 1
    connect.assert_not_called()
    assert "missing" in capsys.readouterr().err


@pytest.mark.parametrize("timeout", ["0", "301"])
def test_worker_rejects_unbounded_timeout_before_connecting(worker, timeout):
    with pytest.raises(SystemExit) as error:
        migration.container_main(["--container", "--wait-timeout", timeout])
    assert error.value.code == 2
    worker[2].assert_not_called()


def test_worker_missing_source_configuration_preserves_target(worker, monkeypatch, capsys):
    monkeypatch.delenv("SUPABASE_POSTGRES_PASSWORD")
    assert migration.container_main(["--container", "--apply"]) == 1
    assert worker[2].call_count == 1
    worker[3].assert_not_called()
    worker[0].rollback.assert_called()
    assert "missing" in capsys.readouterr().err


def test_worker_retries_source_then_commits_without_printing_connection_error(worker, mocker, capsys):
    target, source, connect, importer = worker
    connect.side_effect = [target, psycopg2.OperationalError("source-private"), source]
    mocker.patch.object(migration.time, "monotonic", side_effect=[0, 1])
    sleep = mocker.patch.object(migration.time, "sleep")
    assert migration.container_main(["--container", "--apply"]) == 0
    sleep.assert_called_once_with(1)
    importer.assert_called_once()
    assert "source-private" not in str(capsys.readouterr())


def test_worker_failed_source_read_closes_both_connections_and_never_imports(worker, mocker, capsys):
    mocker.patch.object(migration, "read_source_users", side_effect=RuntimeError("private row"))
    assert migration.container_main(["--container", "--apply"]) == 1
    worker[0].close.assert_called_once()
    worker[1].close.assert_called_once()
    worker[3].assert_not_called()
    assert "private row" not in capsys.readouterr().err
