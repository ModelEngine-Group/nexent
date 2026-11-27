# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Account coverage selects migration; schema and credentials share one transaction."""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from deploy.sql.tools.supabase_to_postgres import migrate_docker as migration


def test_source_metadata_is_quoted_and_never_used_as_sql_template():
    sql = migration._account_import_sql([{
        "id": str(uuid4()), "email": "__DRY_RUN__@example.com",
        "raw_user_meta_data": {"literal": "__ROWS__ __DRY_RUN__ O'Reilly \\"},
    }])
    assert "__dry_run__@example.com" in sql
    assert "__ROWS__ __DRY_RUN__ O''Reilly" in sql
    assert sql.startswith("SET LOCAL standard_conforming_strings=on;")


def test_duplicate_source_uuid_warns_and_does_not_select_credentials(capsys):
    uid, unique = str(uuid4()), str(uuid4())
    sql = migration._account_import_sql([
        {"id": uid, "email": "a@example.com"},
        {"id": uid.upper(), "email": "b@example.com"},
        {"id": unique, "email": "unique@example.com"},
    ])
    warnings = capsys.readouterr().err.splitlines()
    assert len(warnings) == 2
    assert all("[warning]" in warning and uid in warning for warning in warnings)
    assert "a@example.com" in warnings[0] and "b@example.com" in warnings[1]
    assert uid not in sql and unique in sql
    assert "'source',3" in sql


@pytest.mark.parametrize("dry_run", [True, False])
def test_import_warns_about_incomplete_coverage_and_returns_success(mocker, capsys, dry_run):
    target = MagicMock()
    cursor = target.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [
        ({"complete": False, "legacy": True, "account_table": False},),
        ({"inserted": 1, "account_conflicts": [
            {"user_id": "conflict-user", "user_email": "shared@example.com", "reason": "Duplicate active email"},
        ], "account_warnings": [
            {"user_id": "missing-user", "user_email": "old@example.com"},
        ]},),
    ]
    mocker.patch.object(migration, "_account_import_sql", return_value="import-body")
    assert migration.import_users(target, [], dry_run=dry_run) == {"inserted": 1}
    warning = capsys.readouterr().err
    assert "[warning]" in warning and "missing-user" in warning and "old@example.com" in warning
    assert "Duplicate active email" in warning and "conflict-user" in warning and "shared@example.com" in warning
    queries = [call.args[0] for call in cursor.execute.call_args_list]
    assert ("ROLLBACK TO SAVEPOINT account_migration_preview" in queries) is dry_run
    assert queries[-1] == ("RELEASE SAVEPOINT account_migration_preview" if dry_run else "import-body")


def test_conflict_marker_inside_unrelated_sql_context_is_not_exposed():
    message='CONTEXT: SQL statement contains NEXENT_ACCOUNT_CONFLICT=["private-value"]'
    assert migration._migration_conflict(message) is None


@pytest.mark.parametrize("payload", ['[]','[123]','[""]','["'+('x'*101)+'"]','["line\\nvalue"]','[invalid]'])
def test_malformed_conflict_details_are_not_logged(payload):
    assert migration._migration_conflict('NEXENT_ACCOUNT_CONFLICT='+payload) is None


@pytest.mark.parametrize("dry_run", [False, True])
def test_import_propagates_database_errors_to_transaction_owner(mocker, dry_run):
    failure=RuntimeError("private driver details")
    target=MagicMock()
    cursor=target.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value=({"complete": False, "legacy": True},)
    cursor.execute.side_effect = [None, None, *([None] if dry_run else []), failure]
    mocker.patch.object(migration,"_account_import_sql",return_value="import-body")
    with pytest.raises(RuntimeError) as error:
        migration.import_users(target, [], dry_run=dry_run)
    assert error.value is failure
    assert cursor.execute.call_args.args == ("import-body",)
    target.rollback.assert_not_called()
