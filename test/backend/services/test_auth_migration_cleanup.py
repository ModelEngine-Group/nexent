# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Only a committed local apply reclaims the selected Supabase stack."""

from unittest.mock import MagicMock

import pytest

from deploy.sql.tools.supabase_to_postgres import migrate, migration, source_container
from deploy.sql.tools.supabase_to_postgres.settings import MigrationSetupError


@pytest.fixture
def cli(mocker):
    events = []
    source, target = MagicMock(), MagicMock()
    target.__exit__.side_effect = lambda *args: events.append("commit" if args[0] is None else "rollback") or False
    target.close.side_effect = lambda: events.append("close")
    mocker.patch.object(migrate, "load_settings", return_value={})
    mocker.patch.object(migrate, "connections", return_value=({}, {}, True))
    mocker.patch.object(migrate, "prepare_source", return_value="supabase-selected-db")
    mocker.patch.object(migrate, "source_stack_configuration", return_value={"selected": True})
    mocker.patch("psycopg2.connect", side_effect=[source, target])
    mocker.patch.object(migration, "read_source_users", return_value=[])
    importer = mocker.patch.object(migration, "import_users", return_value={"inserted": 0})
    cleanup = mocker.patch.object(migrate, "cleanup_source_stack", side_effect=lambda values: events.append("cleanup"))
    return events, importer, cleanup


@pytest.mark.parametrize("apply", [False, True])
def test_cleanup_only_after_successful_apply_and_closed_transaction(mocker, cli, apply):
    events, importer, cleanup = cli
    mocker.patch("sys.argv", ["migrate.py"] + (["--apply"] if apply else []))
    assert migrate.main() == 0
    assert importer.call_args.kwargs["dry_run"] is not apply
    assert events == (["commit", "close", "cleanup"] if apply else ["commit", "close"])
    assert cleanup.call_count == int(apply)


def test_failed_import_preserves_containers_for_retry(mocker, cli):
    events, importer, cleanup = cli
    importer.side_effect = migration.MigrationConflict("identity conflict")
    mocker.patch("sys.argv", ["migrate.py", "--apply"])
    assert migrate.main() == 1
    assert events == ["rollback", "close"]
    cleanup.assert_not_called()


def test_remote_source_does_not_remove_local_containers(mocker, cli):
    events, importer, cleanup = cli
    mocker.patch.object(migrate, "connections", return_value=({}, {}, False))
    mocker.patch("sys.argv", ["migrate.py", "--apply"])
    assert migrate.main() == 0
    cleanup.assert_not_called()


@pytest.mark.parametrize("error", [MigrationSetupError("Docker cleanup unavailable"), RuntimeError("private-secret")])
def test_cleanup_error_reports_committed_data_without_leaking_driver_values(mocker, cli, capsys, error):
    events, importer, cleanup = cli
    cleanup.side_effect = error
    mocker.patch("sys.argv", ["migrate.py", "--apply"])
    assert migrate.main() == 1
    output = capsys.readouterr()
    assert "migration committed; source cleanup failed" in output.err
    assert "private-secret" not in output.err
    assert events == ["commit", "close"]


def test_source_stack_cleanup_uses_exact_selected_db_and_retains_volumes(mocker):
    from deploy.sql.tools.supabase_to_postgres import legacy_stack

    values = source_container.source_stack_configuration({}, "supabase-original-db")
    assert values["SUPABASE_MIGRATION_DB_CONTAINER"] == "supabase-original-db"
    execute = mocker.patch.object(legacy_stack, "execute")
    source_container.cleanup_source_stack(values)
    execute.assert_called_once_with("down", values)
