# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Version-selected migration phases contain no account-state trigger logic."""

import argparse
import json

import pytest

from deploy.sql.tools.supabase_to_postgres import migrate_docker as migration
from deploy.sql.tools.supabase_to_postgres.migrate_docker import (
    _run_worker,
    _source_target,
)


@pytest.fixture
def upgrade(tmp_path, mocker, monkeypatch):
    monkeypatch.delenv("POSTGRES_DB", raising=False)
    args = argparse.Namespace(deployment="docker", namespace="nexent", database_target="owned-db",
                              config_target="owned-config", state_dir=tmp_path, env_file=tmp_path / ".env",
                              source_container=None, deploy_phase="prepare", wait_timeout=1)
    source = mocker.patch.object(migration, "_source_target", return_value={"target": "supabase-db", "configuration": {"owned": True}})
    mocker.patch.object(migration, "source_snapshot", return_value=[])
    worker = mocker.patch.object(migration, "_run_worker", return_value={"source": 0})
    cleanup = mocker.patch.object(migration, "cleanup_source_stack")
    return args, source, worker, cleanup


def test_version_selected_prepare_and_apply_import_data_without_schema_sql(upgrade):
    args, _, worker, cleanup = upgrade
    assert migration.automatic_upgrade(args)["source"] == 0
    args.deploy_phase = "apply"
    assert migration.automatic_upgrade(args) == {"source": 0}
    worker.assert_called_once_with(args, {"action": "apply", "rows": []})
    cleanup.assert_called_once_with({"owned": True})
    assert not list(args.state_dir.glob("*.json"))


def test_missing_source_stops_the_version_upgrade(upgrade):
    args, source, worker, cleanup = upgrade
    source.return_value = None
    with pytest.raises(migration.MigrationSetupError, match="original Supabase database"):
        migration.automatic_upgrade(args)
    worker.assert_not_called()
    cleanup.assert_not_called()


def test_prepare_retry_uses_snapshot_and_rejects_other_target(upgrade):
    args, source, _, _ = upgrade
    migration.automatic_upgrade(args)
    source.reset_mock()
    assert migration.automatic_upgrade(args)["retained"]
    source.assert_not_called()
    args.database_target = "other"
    with pytest.raises(migration.MigrationSetupError, match="different deployment"):
        migration.automatic_upgrade(args)


def test_failed_import_retains_source_and_snapshot(upgrade):
    args, _, worker, cleanup = upgrade
    migration.automatic_upgrade(args)
    args.deploy_phase = "apply"
    worker.side_effect = migration.MigrationConflict("conflict")
    with pytest.raises(migration.MigrationConflict):
        migration.automatic_upgrade(args)
    cleanup.assert_not_called()
    assert not json.loads(next(args.state_dir.glob("*.json")).read_text()).get("imported")


def test_cleanup_retry_does_not_reimport_committed_accounts(upgrade):
    args, _, worker, cleanup = upgrade
    migration.automatic_upgrade(args)
    args.deploy_phase = "apply"
    cleanup.side_effect = migration.MigrationSetupError("cleanup")
    with pytest.raises(migration.MigrationSetupError):
        migration.automatic_upgrade(args)
    assert json.loads(next(args.state_dir.glob("*.json")).read_text())["imported"]
    cleanup.side_effect = None
    worker.reset_mock()
    migration.automatic_upgrade(args)
    worker.assert_not_called()
    assert not list(args.state_dir.glob("*.json"))


def test_apply_requires_a_prepared_snapshot(upgrade):
    args = upgrade[0]
    args.deploy_phase = "apply"
    with pytest.raises(migration.MigrationSetupError, match="snapshot is missing"):
        migration.automatic_upgrade(args)


def test_worker_only_imports_accounts_without_running_schema_sql(mocker):
    connection = mocker.patch("psycopg2.connect").return_value
    importer = mocker.patch.object(migration, "import_users", return_value={"source": 0})
    migration._worker({"action": "apply", "rows": []})
    importer.assert_called_once_with(connection, [], dry_run=False)
    connection.cursor.assert_not_called()
    connection.close.assert_called_once()


def test_remote_source_does_not_discover_local_containers(upgrade, mocker):
    docker = mocker.patch.object(migration, "_docker")
    assert _source_target(upgrade[0], {"SUPABASE_POSTGRES_HOST": "external"}) == {"remote": True}
    docker.assert_not_called()


def test_worker_conflict_is_sanitized_and_payload_uses_stdin(upgrade, mocker):
    execute = mocker.patch.object(migration, "_exec", return_value='{"migration_error":"identity conflict"}')
    with pytest.raises(migration.MigrationConflict, match="identity conflict"):
        _run_worker(upgrade[0], {"action": "apply", "rows": [{"private": "credential"}]})
    command, payload = execute.call_args.args[2:]
    assert "credential" not in str(command)
    assert json.loads(payload)["job"]["rows"] == [{"private": "credential"}]
