# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Table existence is the only completion marker; migration has one transaction."""
import argparse
import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from deploy.sql.tools.supabase_to_postgres import migrate_docker as migration


@pytest.fixture
def upgrade(tmp_path, mocker):
    args = argparse.Namespace(deployment="docker", namespace="nexent", database_target="owned-db",
                              config_target="owned-config", env_file=tmp_path / ".env",
                              source_container=None, wait_timeout=1, apply=True)
    source = mocker.patch.object(migration, "_source_target", return_value={"target": "supabase-db", "configuration": {"owned": True}})
    mocker.patch.object(migration, "source_snapshot", return_value=[])
    sql = mocker.patch.object(migration, "_psql", side_effect=[
        '{"complete":false,"legacy":true}', '{"source":0,"dry_run":false}'])
    cleanup = mocker.patch.object(migration, "cleanup_source_stack")
    return args, source, sql, cleanup


def test_completed_table_skips_source_access_and_all_writes(upgrade):
    args, source, sql, cleanup = upgrade
    sql.side_effect = ['{"complete":true,"legacy":true}']
    assert migration.automatic_upgrade(args)["skipped"]
    source.assert_not_called()
    cleanup.assert_not_called()
    assert sql.call_count == 1
    assert "user_account_t" in sql.call_args.args[2]
    assert "schema_migrations" not in sql.call_args.args[2]


def test_fresh_database_uses_normal_initialization_without_source(upgrade):
    args, source, sql, cleanup = upgrade
    sql.side_effect = ['{"complete":false,"legacy":false}']
    assert migration.automatic_upgrade(args)["new"]
    source.assert_not_called()
    cleanup.assert_not_called()


def test_upgrade_runs_one_atomic_sql_command_before_cleanup(upgrade):
    args, _, sql, cleanup = upgrade
    assert migration.automatic_upgrade(args) == {"source": 0, "dry_run": False}
    command = sql.call_args.args[2]
    assert command.startswith("BEGIN;") and command.rstrip().endswith("COMMIT;")
    assert command.index("CREATE TABLE IF NOT EXISTS nexent.user_account_t") < command.index("CREATE TEMP TABLE")
    cleanup.assert_called_once_with({"owned": True})
    assert not (args.env_file.parent / ".migration-state").exists()


def test_missing_source_does_not_create_target_or_process_files(upgrade):
    args, source, sql, cleanup = upgrade
    source.return_value = None
    with pytest.raises(migration.MigrationSetupError, match="original Supabase database"):
        migration.automatic_upgrade(args)
    assert sql.call_count == 1
    cleanup.assert_not_called()
    assert not list(args.env_file.parent.glob("*.json"))


def test_import_failure_keeps_source_and_no_persistent_retry_state(upgrade):
    args, _, sql, cleanup = upgrade
    sql.side_effect = ['{"complete":false,"legacy":true}', migration.MigrationSetupError("database failure")]
    with pytest.raises(migration.MigrationSetupError):
        migration.automatic_upgrade(args)
    cleanup.assert_not_called()
    assert not list(args.env_file.parent.glob("*.json"))


def test_cleanup_failure_preserves_committed_accounts_and_reports_warning(upgrade, capsys):
    args, _, _, cleanup = upgrade
    cleanup.side_effect = migration.MigrationSetupError("cleanup")
    assert migration.automatic_upgrade(args)["source"] == 0
    assert "cleanup" in capsys.readouterr().err.lower()


def test_preview_rolls_back_and_does_not_reclaim_source(upgrade):
    args, _, sql, cleanup = upgrade
    args.apply = False
    migration.automatic_upgrade(args)
    assert sql.call_args.args[2].rstrip().endswith("ROLLBACK;")
    cleanup.assert_not_called()


def test_invalid_source_is_rejected_before_target_ddl(upgrade, mocker):
    args, _, sql, cleanup = upgrade
    mocker.patch.object(migration, "source_snapshot", return_value=[{"id": "invalid"}])
    with pytest.raises(migration.MigrationConflict):
        migration.automatic_upgrade(args)
    assert sql.call_count == 1
    cleanup.assert_not_called()


def test_remote_source_does_not_discover_local_containers(mocker):
    docker = mocker.patch.object(migration, "_docker")
    args = argparse.Namespace(source_container=None)
    assert migration._source_target(args, {"SUPABASE_POSTGRES_HOST": "external"}) == {"remote": True}
    docker.assert_not_called()


def test_worker_conflict_is_sanitized_and_payload_uses_stdin(upgrade, mocker):
    execute = mocker.patch.object(migration, "_exec", return_value='{"migration_error":"identity conflict"}')
    with pytest.raises(migration.MigrationConflict, match="identity conflict"):
        migration._run_worker(upgrade[0], {"action": "snapshot", "params": {"password": "credential"}})
    command, payload = execute.call_args.args[2:]
    assert "credential" not in str(command)
    assert json.loads(payload)["job"]["params"]["password"] == "credential"


def test_completed_manual_migration_skips_source_credentials_and_discovery(mocker, capsys):
    mocker.patch.object(migration.sys, "argv", ["migrate_docker.py", "--apply"])
    mocker.patch.object(migration, "load_settings", return_value={"NEXENT_POSTGRES_PASSWORD": "target-only"})
    connection = mocker.patch("psycopg2.connect").return_value
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value.fetchone.return_value = (True,)
    source = mocker.patch.object(migration, "connections")
    discovery = mocker.patch.object(migration, "prepare_source")
    assert migration.main() == 0
    assert json.loads(capsys.readouterr().out)["complete"]
    source.assert_not_called()
    discovery.assert_not_called()
    connection.close.assert_called_once()


def test_source_metadata_is_quoted_and_never_used_as_sql_template():
    sql = migration._account_import_sql([{
        "id": str(uuid4()), "email": "__DRY_RUN__@example.com",
        "raw_user_meta_data": {"literal": "__ROWS__ __DRY_RUN__ O'Reilly \\"},
    }])
    assert "__dry_run__@example.com" in sql
    assert "__ROWS__ __DRY_RUN__ O''Reilly" in sql
    assert sql.startswith("SET LOCAL standard_conforming_strings=on;")


@pytest.mark.parametrize("deployment", ["docker", "kubernetes"])
def test_psql_conflict_keeps_ids_without_exposing_raw_error(upgrade, mocker, deployment):
    args = upgrade[0]
    args.deployment = deployment
    ids = [str(uuid4()),str(uuid4())]
    marker = 'ERROR: NEXENT_ACCOUNT_CONFLICT=' + json.dumps(ids)
    mocker.patch.object(migration, "_database_environment", return_value={"POSTGRES_PASSWORD":"private-password"})
    mocker.patch.object(migration.subprocess,"run",return_value=argparse.Namespace(
        returncode=1,stdout=b'',stderr=(marker+'\nprivate-password raw SQL').encode()))
    # The fixture's psql boundary is mocked for automatic-upgrade tests.
    from deploy.sql.tools.supabase_to_postgres.migrate_docker import _command
    with pytest.raises(migration.MigrationConflict) as error:
        _command([deployment,'exec'])
    assert all(value in str(error.value) for value in ids)
    assert 'private-password' not in str(error.value) and 'raw SQL' not in str(error.value)


def test_duplicate_source_uuid_reports_its_id():
    uid=str(uuid4())
    with pytest.raises(migration.MigrationConflict,match=uid):
        migration._account_import_sql([{"id":uid,"email":"a@example.com"},{"id":uid,"email":"b@example.com"}])


def test_conflict_marker_inside_unrelated_sql_context_is_not_exposed():
    message='CONTEXT: SQL statement contains NEXENT_ACCOUNT_CONFLICT=["private-value"]'
    assert migration._migration_conflict(message) is None


@pytest.mark.parametrize("payload", ['[]','[123]','[""]','["'+('x'*101)+'"]','["line\\nvalue"]','[invalid]'])
def test_malformed_conflict_details_are_not_logged(payload):
    assert migration._migration_conflict('NEXENT_ACCOUNT_CONFLICT='+payload) is None


def test_import_conflict_preserves_ids_before_savepoint_rollback(mocker):
    uid=str(uuid4())
    failure=RuntimeError("private driver details")
    failure.diag=SimpleNamespace(message_primary='NEXENT_ACCOUNT_CONFLICT='+json.dumps([uid]))
    target=MagicMock()
    cursor=target.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value=(False,)
    cursor.execute.side_effect=[None,None,None,failure,None,None]
    mocker.patch.object(migration,"_account_import_sql",return_value="import-body")
    with pytest.raises(migration.MigrationConflict,match=uid) as error:
        migration.import_users(target,[],dry_run=False)
    assert 'private driver details' not in str(error.value)
    assert [call.args[0] for call in cursor.execute.call_args_list][-2:] == [
        'ROLLBACK TO SAVEPOINT account_migration','RELEASE SAVEPOINT account_migration']
