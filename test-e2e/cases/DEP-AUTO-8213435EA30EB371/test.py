from __future__ import annotations

from pathlib import Path

import pytest

from shared.config import repo_root
from shared.postgres import postgres_scalar, postgres_sql


CASE_ID = 'DEP-AUTO-8213435EA30EB371'
MIGRATION_SQL = 'deploy/sql/migrations/v2.5.3_database_bootstrap_idempotency.sql'
VALIDATION_SH = 'deploy/tests/test_database_bootstrap_idempotency.sh'
PASS_MARKER = 'Database bootstrap idempotency contract passed.'
TRIGGER_FN = 'provision_unified_tag_management_after_user_tenant_insert'


def _compact(text: str) -> str:
    return ''.join(text.split()).lower()


def _repo_file(relative: str) -> Path:
    return repo_root() / relative


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D5')
def test_database_bootstrap_idempotency_contract() -> None:
    sql_path = _repo_file(MIGRATION_SQL)
    assert sql_path.is_file(), f'missing migration script: {sql_path}'
    sql = sql_path.read_text(encoding='utf-8')
    # Execute the migration twice against the deployed PostgreSQL instance.
    # This proves executable idempotency instead of testing source substrings.
    postgres_sql(sql, tuples_only=False)
    postgres_sql(sql, tuples_only=False)
    sequence_ok = postgres_scalar("""
WITH state AS (
  SELECT COALESCE(MAX(role_permission_id), 0)::bigint AS maximum
    FROM nexent.role_permission_t
), seq AS (
  SELECT last_value::bigint
    FROM pg_sequences
   WHERE schemaname = split_part(pg_get_serial_sequence('nexent.role_permission_t', 'role_permission_id'), '.', 1)
     AND sequencename = split_part(pg_get_serial_sequence('nexent.role_permission_t', 'role_permission_id'), '.', 2)
)
SELECT CASE
  WHEN state.maximum = 0 THEN seq.last_value >= 1
  ELSE seq.last_value >= state.maximum
END
FROM state CROSS JOIN seq;
""")
    assert sequence_ok == 't', 'role_permission sequence is not aligned with persisted IDs'
    trigger_count = postgres_scalar("""
SELECT count(*)
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'nexent'
   AND p.proname = 'provision_unified_tag_management_after_user_tenant_insert';
""")
    assert trigger_count == '1', f'expected exactly one deployed trigger function, got {trigger_count}'
