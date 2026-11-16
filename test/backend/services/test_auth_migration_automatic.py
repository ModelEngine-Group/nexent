# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Account coverage selects migration; schema and credentials share one transaction."""
import json
from types import SimpleNamespace
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


def test_duplicate_source_uuid_reports_its_id():
    uid=str(uuid4())
    with pytest.raises(migration.MigrationConflict,match=uid):
        migration._account_import_sql([{"id":uid,"email":"a@example.com"},{"id":uid,"email":"b@example.com"}])


@pytest.mark.parametrize("prefix", ["", "ERROR: "])
def test_incomplete_coverage_error_keeps_ids_and_recovery_guidance_only(prefix):
    error = migration._migration_conflict(prefix + 'NEXENT_ACCOUNT_INCOMPLETE=["missing-user"]\nprivate-source-password raw SQL')
    assert "missing-user" in str(error) and "backup" in str(error)
    assert "private-source-password" not in str(error) and "raw SQL" not in str(error)


@pytest.mark.parametrize("ids", ['[]', '[123]', '["bad\\nidentifier"]', '"not-a-list"'])
def test_malformed_incomplete_error_is_not_exposed(ids):
    assert migration._migration_conflict('NEXENT_ACCOUNT_INCOMPLETE=' + ids) is None


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
    cursor.fetchone.return_value=({"complete": False, "legacy": True},)
    cursor.execute.side_effect=[None,None,None,failure,None,None]
    mocker.patch.object(migration,"_account_import_sql",return_value="import-body")
    with pytest.raises(migration.MigrationConflict,match=uid) as error:
        migration.import_users(target,[],dry_run=False)
    assert 'private driver details' not in str(error.value)
    assert [call.args[0] for call in cursor.execute.call_args_list][-2:] == [
        'ROLLBACK TO SAVEPOINT account_migration','RELEASE SAVEPOINT account_migration']
