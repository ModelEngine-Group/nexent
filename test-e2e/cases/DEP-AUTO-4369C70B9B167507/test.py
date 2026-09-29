from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from shared.config import repo_root

CASE_ID = 'DEP-AUTO-4369C70B9B167507'
MIGRATION_REL = 'deploy/sql/migrations/v2.5.3_database_bootstrap_idempotency.sql'
SCRIPT_REL = 'deploy/tests/test_database_bootstrap_idempotency.sh'
SUCCESS_MESSAGE = 'Database bootstrap idempotency contract passed.'


def _compact(sql: str) -> str:
    cleaned = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
    cleaned = re.sub(r'--[^\n]*', '', cleaned)
    return re.sub(r'\s+', '', cleaned).lower()


def _assert_sequence_resync(compact: str) -> None:
    assert "pg_get_serial_sequence('nexent.role_permission_t','role_permission_id')" in compact, (
        'sequence must be located via pg_get_serial_sequence for nexent.role_permission_t/role_permission_id'
    )
    assert 'setval' in compact, 'missing setval sequence resync'
    assert 'coalesce(max(role_permission_id),1)' in compact, (
        'setval must resync the sequence to COALESCE(MAX(role_permission_id), 1)'
    )
    is_called = (
        'coalesce(max(role_permission_id),1),true)' in compact
        or 'coalesce(max(role_permission_id),1),(max(role_permission_id)isnotnull)' in compact
    )
    assert is_called, 'setval is_called must be true (or MAX IS NOT NULL) so inserts advance from MAX+1'


def _assert_trigger_guard(compact: str) -> None:
    fn_token = 'createorreplacefunctionprovision_unified_tag_management_after_user_tenant_insert'
    assert compact.count(fn_token) == 1, (
        'provision_unified_tag_management_after_user_tenant_insert must be defined exactly once'
    )
    assert 'provision_unified_tag_management(' in compact, 'trigger must call provision_unified_tag_management'
    assert ("coalesce(delete_flag,'n')<>'y'" in compact) or ("coalesce(delete_flag,'n')!='y'" in compact), (
        'trigger must guard on COALESCE(delete_flag,N) <> Y'
    )
    assert "nullif(btrim(tenant_id),'')isnotnull" in compact, 'trigger must skip empty tenant_id'


def _assert_transaction(compact: str) -> None:
    assert 'begin;' in compact, 'migration body must be wrapped in a BEGIN; transaction'
    assert 'commit;' in compact, 'migration body must be closed with COMMIT;'
    assert compact.find('begin;') < compact.find('commit;'), 'BEGIN; must precede COMMIT;'
    assert 'createorreplacefunction' in compact, 'migration must use CREATE OR REPLACE FUNCTION for idempotent reruns'


@pytest.mark.stage('D5')
@pytest.mark.case_id(CASE_ID)
def test_database_bootstrap_idempotency_contract() -> None:
    repo = repo_root()
    migration_path = repo / MIGRATION_REL
    script_path = repo / SCRIPT_REL

    assert migration_path.is_file(), f'missing required file: {migration_path}'
    assert script_path.is_file(), f'missing required file: {script_path}'

    sql = migration_path.read_text(encoding='utf-8')
    compact = _compact(sql)

    _assert_sequence_resync(compact)
    _assert_trigger_guard(compact)
    _assert_transaction(compact)

    proc = subprocess.run(
        ['bash', str(script_path)],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = proc.stdout + '\n' + proc.stderr
    assert proc.returncode == 0, f'contract script failed with exit {proc.returncode}; output={combined!r}'
    assert SUCCESS_MESSAGE in combined, f'contract script did not emit success message; output={combined!r}'
