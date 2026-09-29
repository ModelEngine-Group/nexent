'''D5 special reliability test for unified tag management tenant provisioning.

Verifies that provision_unified_tag_management (and its AFTER INSERT trigger on
nexent.user_tenant_t) provisions, per tenant, exactly two tag buckets
(default_resource, knowledge_content), six resource-type bindings, one
agent_category multi_select definition with its 20 preset values, and stays
idempotent across repeated trigger fires and direct function calls.
'''

from __future__ import annotations

import os
import random
import re
import string
import subprocess
import time
from pathlib import Path

import pytest

from shared.asset_registry import AutomationInfrastructureError
from shared.config import repo_root
from shared.asset_registry import mark_asset_state
from shared.factories.owned_container import register_container, stop_owned_container, OWNER

CASE_ID = 'DEP-AUTO-E89502155049473D'
STAGE = 'D5'

POSTGRES_TEST_IMAGE = os.environ.get('POSTGRES_TEST_IMAGE', 'postgres:15-alpine')
DOCKER_BIN = os.environ.get('DOCKER_BIN', 'docker')
POSTGRES_PASSWORD = 'utm-test-password'
MIGRATION_TARGET = 'v2.6.0_merged_migrations.sql'

_EXPECTED_BUCKET_KEYS = 'default_resource,knowledge_content'
_EXPECTED_RESOURCE_TYPES = 'agent,knowledge_base,knowledge_document,mcp_service,skill,tool'
_EXPECTED_BINDINGS = (
    'default_resource:agent,'
    'default_resource:knowledge_base,'
    'knowledge_content:knowledge_document,'
    'default_resource:mcp_service,'
    'default_resource:skill,'
    'default_resource:tool'
)
_EXPECTED_PRESET_VALUES = (
    'marketing,copywriting,content_creation,code_review,quality,devops,data,'
    'visualization,bi,customer_service,ticket,automation,meeting,minutes,'
    'productivity,design,color_scheme,inspiration,spreadsheet,office'
)


def _natural_key(name: str) -> list:
    return [int(part) if part.isdigit() else part for part in re.split(r'([0-9]+)', name)]


class _PostgresFixture:
    def __init__(self, container_name: str, database: str) -> None:
        self.container_name = container_name
        self.database = database

    def _exec(self, sql: str, user: str, database: str = '', search_path: bool = False) -> str:
        cmd = [DOCKER_BIN, 'exec', '-i']
        if search_path:
            # docker exec does not inherit the host subprocess environment.
            cmd.extend(['-e', 'PGOPTIONS=-c search_path=nexent,public'])
        cmd.extend([
            self.container_name,
            'psql', '-X', '-v', 'ON_ERROR_STOP=1',
            '-U', user, '-d', database or self.database,
            '-A', '-t', '-q',
        ])
        result = subprocess.run(cmd, input=sql, capture_output=True, text=True)
        if result.returncode != 0:
            raise AutomationInfrastructureError(f'psql failed ({result.returncode}): {result.stderr}')
        return result.stdout.strip()

    def run_sql(self, sql: str) -> str:
        return self._exec(sql, user='root', search_path=True)

    def run_file(self, path: Path) -> None:
        self._exec(path.read_text(encoding='utf-8'), user='root', search_path=True)

    def query(self, sql: str) -> str:
        return self.run_sql(sql)


def _migrations_through_target(repo: Path) -> list:
    migrations_dir = repo / 'deploy' / 'sql' / 'migrations'
    files = sorted(migrations_dir.glob('*.sql'), key=lambda p: _natural_key(p.name))
    target = next((f for f in files if f.name == MIGRATION_TARGET), None)
    if target is None:
        raise AutomationInfrastructureError(f'migration target not found: {MIGRATION_TARGET}')
    return files[: files.index(target) + 1]


def _provision_count_sql(tenant: str) -> str:
    return f'''SELECT (SELECT count(*) FROM nexent.tag_bucket WHERE tenant_id = '{tenant}' AND delete_flag = 'N') || '|' || (SELECT count(*) FROM nexent.tag_bucket_resource_type WHERE tenant_id = '{tenant}' AND delete_flag = 'N') || '|' || (SELECT count(*) FROM nexent.tag_definition WHERE tenant_id = '{tenant}' AND definition_key = 'agent_category' AND delete_flag = 'N') || '|' || (SELECT count(*) FROM nexent.tag_value AS value JOIN nexent.tag_definition AS definition USING (tenant_id, definition_id) WHERE definition.tenant_id = '{tenant}' AND definition.definition_key = 'agent_category' AND value.delete_flag = 'N');'''


@pytest.fixture(scope='session')
def utm_db():
    repo = repo_root()
    migrations = _migrations_through_target(repo)
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    container_name = f'nexent-utm-d5-{suffix}'
    database = f'utm_dep_auto_{suffix}'

    start = subprocess.run(
        [DOCKER_BIN, 'run', '--rm', '-d', '--name', container_name,
         '--label', f'nexent.test.owner={OWNER}',
         '-e', f'POSTGRES_PASSWORD={POSTGRES_PASSWORD}', POSTGRES_TEST_IMAGE],
        capture_output=True, text=True,
    )
    if start.returncode != 0:
        raise AutomationInfrastructureError(f'could not start PostgreSQL container: {start.stderr}')

    container_id = start.stdout.strip()
    try:
        register_container(container_name, container_id, DOCKER_BIN)
    except BaseException:
        stop_owned_container(container_name, container_id, DOCKER_BIN)
        raise

    try:
        ready = False
        for _ in range(60):
            check = subprocess.run(
                [DOCKER_BIN, 'exec', container_name, 'pg_isready', '-U', 'postgres', '-d', 'postgres'],
                capture_output=True,
            )
            if check.returncode == 0:
                ready = True
                break
            time.sleep(1)
        if not ready:
            raise AutomationInfrastructureError('PostgreSQL container did not become ready')

        db = _PostgresFixture(container_name, database)
        db._exec(f'CREATE DATABASE {database};', user='postgres', database='postgres')
        db._exec(
            '''DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'root') THEN CREATE ROLE root LOGIN SUPERUSER; END IF; END; $$;''',
            user='postgres',
        )
        db.run_file(repo / 'deploy' / 'sql' / 'init.sql')
        for migration in migrations:
            db.run_file(migration)
        yield db
    finally:
        stop_owned_container(container_name, container_id, DOCKER_BIN)
        mark_asset_state('owned_containers', container_name, 'DELETED')


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage(STAGE)
def test_unified_tag_provisioning_is_idempotent(utm_db) -> None:
    tenant = 'dep-auto-e89502155049473d'
    soft_deleted_tenant = 'dep-auto-e89502155049473d-soft-deleted'

    utm_db.run_sql(
        f'''INSERT INTO nexent.user_tenant_t (user_id, tenant_id, created_by, delete_flag) VALUES ('user-{tenant}-1', '{tenant}', 'user-{tenant}-1', 'N');'''
    )

    assert utm_db.query(_provision_count_sql(tenant)) == '2|6|1|20'
    assert utm_db.query(
        f'''SELECT string_agg(bucket_key, ',' ORDER BY bucket_key) FROM nexent.tag_bucket WHERE tenant_id = '{tenant}' AND delete_flag = 'N';'''
    ) == _EXPECTED_BUCKET_KEYS
    assert utm_db.query(
        f'''SELECT string_agg(resource_type, ',' ORDER BY resource_type) FROM nexent.tag_bucket_resource_type WHERE tenant_id = '{tenant}' AND delete_flag = 'N';'''
    ) == _EXPECTED_RESOURCE_TYPES
    assert utm_db.query(
        f'''SELECT string_agg(bucket.bucket_key || ':' || binding.resource_type, ',' ORDER BY binding.resource_type) FROM nexent.tag_bucket_resource_type AS binding JOIN nexent.tag_bucket AS bucket ON bucket.tenant_id = binding.tenant_id AND bucket.bucket_id = binding.bucket_id WHERE binding.tenant_id = '{tenant}' AND binding.delete_flag = 'N';'''
    ) == _EXPECTED_BINDINGS
    assert utm_db.query(
        f'''SELECT selection_mode FROM nexent.tag_definition WHERE tenant_id = '{tenant}' AND definition_key = 'agent_category' AND delete_flag = 'N';'''
    ) == 'multi_select'
    assert utm_db.query(
        f'''SELECT string_agg(value.normalized_value, ',' ORDER BY value.sort_order) FROM nexent.tag_value AS value JOIN nexent.tag_definition AS definition USING (tenant_id, definition_id) WHERE definition.tenant_id = '{tenant}' AND definition.definition_key = 'agent_category' AND value.delete_flag = 'N';'''
    ) == _EXPECTED_PRESET_VALUES

    utm_db.run_sql(
        f'''INSERT INTO nexent.user_tenant_t (user_id, tenant_id, created_by, delete_flag) VALUES ('user-{tenant}-2', '{tenant}', 'user-{tenant}-2', 'N');'''
    )
    assert utm_db.query(_provision_count_sql(tenant)) == '2|6|1|20'

    utm_db.run_sql(f'''SELECT nexent.provision_unified_tag_management('{tenant}', 'test');''')
    assert utm_db.query(_provision_count_sql(tenant)) == '2|6|1|20'

    utm_db.run_sql(
        f'''INSERT INTO nexent.user_tenant_t (user_id, tenant_id, created_by, delete_flag) VALUES ('user-{soft_deleted_tenant}-1', '{soft_deleted_tenant}', 'user-{soft_deleted_tenant}-1', 'Y');'''
    )
    assert utm_db.query(_provision_count_sql(soft_deleted_tenant)) == '0|0|0|0'
