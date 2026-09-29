'''Data-integrity test for the v2.5.2 MCP legacy tag migration backfill.

mcp_record.tags / mcp_community.tags / mcp_market.tags are migrated into the
unified tag management tables. This test proves that non-empty tags survive
normalization without loss or duplication, soft-deleted records stay soft
deleted, empty and NULL tags leave no residue, cross-tenant data stays
isolated, unattributable community/market records block the migration instead
of being silently dropped, and the migration is idempotent on replay.
'''

from __future__ import annotations

import os
import uuid

import psycopg2
import pytest

from shared.config import repo_root
from shared.postgres import postgres_target
from shared.postgres import postgres_connect_kwargs as _pg_config

CASE_ID = 'DEP-AUTO-2D0252F1DB402184'
MIGRATION_PATH = 'deploy/sql/migrations/v2.5.2_unified_tag_management.sql'
RESOURCE_TYPE = 'mcp_service'


def _normalize(tag):
    return (tag or '').strip().lower()


def _connect():
    config = _pg_config()
    missing = [key for key, value in config.items() if not value]
    if missing:
        raise RuntimeError(f'PostgreSQL connection settings missing: {missing}')
    return psycopg2.connect(**config)


def _migration_body():
    path = repo_root() / MIGRATION_PATH
    lines = path.read_text(encoding='utf-8').splitlines()
    kept = [line for line in lines if line.strip().upper() not in ('BEGIN;', 'COMMIT;')]
    return chr(10).join(kept)


def _seed_user_tenant(cur, tenant_id):
    cur.execute(
        'INSERT INTO nexent.user_tenant_t (user_id, tenant_id, user_role, user_email) '
        'VALUES (%s, %s, %s, %s)',
        ('test-user', tenant_id, 'ADMIN', 'test@example.com'),
    )


def _seed_mcp(cur, tenant_id, mcp_id, tags, delete_flag):
    cur.execute(
        'INSERT INTO nexent.mcp_record_t '
        '(mcp_id, tenant_id, user_id, mcp_name, mcp_server, tags, enabled, delete_flag) '
        'VALUES (%s, %s, %s, %s, %s, %s::text[], %s, %s)',
        (mcp_id, tenant_id, 'test-user', f'mcp-{mcp_id}', f'http://example/{mcp_id}', tags, True, delete_flag),
    )


def _seed_community(cur, tenant_id, community_id, tags, delete_flag):
    cur.execute(
        'INSERT INTO nexent.mcp_community_record_t '
        '(community_id, tenant_id, user_id, mcp_name, mcp_server, tags, delete_flag) '
        'VALUES (%s, %s, %s, %s, %s, %s::text[], %s)',
        (community_id, tenant_id, 'test-user', f'community-{community_id}', f'http://example/community/{community_id}', tags, delete_flag),
    )


def _seed_market(cur, tenant_id, market_id, source_mcp_id, tags, delete_flag):
    cur.execute(
        'INSERT INTO nexent.mcp_market_record_t '
        '(market_id, tenant_id, user_id, mcp_name, mcp_server, source_mcp_id, tags, delete_flag) '
        'VALUES (%s, %s, %s, %s, %s, %s, %s::text[], %s)',
        (market_id, tenant_id, 'test-user', f'market-{market_id}', f'http://example/market/{market_id}', source_mcp_id, tags, delete_flag),
    )


def _keyword_values(cur, tenant_id):
    cur.execute(
        'SELECT value.normalized_value '
        'FROM nexent.tag_value AS value '
        'JOIN nexent.tag_definition AS definition '
        '  ON definition.tenant_id = value.tenant_id '
        ' AND definition.definition_id = value.definition_id '
        'WHERE value.tenant_id = %s '
        '  AND definition.definition_key = %s '
        '  AND value.delete_flag = %s '
        'ORDER BY value.normalized_value',
        (tenant_id, 'keywords', 'N'),
    )
    return [row[0] for row in cur.fetchall()]


def _assignments(cur, tenant_id, delete_flag):
    cur.execute(
        'SELECT assignment.resource_id, value.normalized_value '
        'FROM nexent.resource_tag_assignment AS assignment '
        'JOIN nexent.tag_value AS value '
        '  ON value.tenant_id = assignment.tenant_id '
        ' AND value.definition_id = assignment.definition_id '
        ' AND value.value_id = assignment.value_id '
        'WHERE assignment.tenant_id = %s '
        '  AND assignment.resource_type = %s '
        '  AND assignment.delete_flag = %s '
        'ORDER BY assignment.resource_id, value.normalized_value',
        (tenant_id, RESOURCE_TYPE, delete_flag),
    )
    return cur.fetchall()


def _assert_migration_blocked(cur, expected_reason):
    with pytest.raises(psycopg2.Error) as excinfo:
        cur.execute(_migration_body())
    message = str(excinfo.value)
    assert 'Unified tag migration blocked' in message
    assert expected_reason in message


def _drop_migration_temp_tables(cur):
    cur.execute(
        'DROP TABLE IF EXISTS utm_legacy_source, utm_conflict, utm_normalized_source, '
        'utm_agent_category_alias, utm_agent_category_source, utm_agent_category_projection'
    )


def _assert_happy_path_migration():
    tenant_a = 'dep-auto-' + uuid.uuid4().hex[:12]
    tenant_b = 'dep-auto-' + uuid.uuid4().hex[:12]
    conn = _connect()
    try:
        conn.autocommit = False
        cur = conn.cursor()
        _seed_user_tenant(cur, tenant_a)
        _seed_user_tenant(cur, tenant_b)
        _seed_mcp(cur, tenant_a, -101, ['Alpha', ' beta ', 'BETA', ' gamma'], 'N')
        _seed_mcp(cur, tenant_a, -102, ['Alpha', 'delta'], 'N')
        _seed_mcp(cur, tenant_a, -103, ['soft-only'], 'Y')
        _seed_mcp(cur, tenant_a, -104, [], 'N')
        _seed_mcp(cur, tenant_a, -105, None, 'N')
        _seed_mcp(cur, tenant_a, -106, [], 'N')
        _seed_mcp(cur, tenant_b, -107, ['OtherTenantTag'], 'N')
        _seed_market(cur, tenant_a, -301, -106, ['MarketTag', 'marketTag'], 'N')

        cur.execute(_migration_body())

        expected_values = sorted({
            _normalize(tag)
            for tag in ['Alpha', ' beta ', 'BETA', ' gamma', 'delta', 'soft-only', 'MarketTag', 'marketTag']
        })
        assert _keyword_values(cur, tenant_a) == expected_values

        active = _assignments(cur, tenant_a, 'N')
        assert len(active) == len(set(active))
        active_by_resource = {}
        for resource_id, value in active:
            active_by_resource.setdefault(resource_id, []).append(value)
        assert sorted(active_by_resource.get('-101', [])) == ['alpha', 'beta', 'gamma']
        assert sorted(active_by_resource.get('-102', [])) == ['alpha', 'delta']
        assert sorted(active_by_resource.get('-106', [])) == ['markettag']
        assert '-103' not in active_by_resource
        assert '-104' not in active_by_resource
        assert '-105' not in active_by_resource
        for values in active_by_resource.values():
            assert len(values) == len(set(values))
            assert len(values) <= 100

        soft = _assignments(cur, tenant_a, 'Y')
        assert sorted(value for resource_id, value in soft if resource_id == '-103') == ['soft-only']

        tenant_b_values = _keyword_values(cur, tenant_b)
        assert tenant_b_values == ['othertenanttag']
        assert set(tenant_b_values).isdisjoint(expected_values)
    finally:
        conn.rollback()
        conn.close()


def _assert_community_blocking():
    tenant = 'dep-auto-' + uuid.uuid4().hex[:12]
    conn = _connect()
    try:
        conn.autocommit = False
        cur = conn.cursor()
        _seed_user_tenant(cur, tenant)
        _seed_community(cur, tenant, -401, ['CommunityTag'], 'N')
        _assert_migration_blocked(cur, 'community_canonical_source_unprovable')
    finally:
        conn.rollback()
        conn.close()


def _assert_market_missing_source_blocking():
    tenant = 'dep-auto-' + uuid.uuid4().hex[:12]
    conn = _connect()
    try:
        conn.autocommit = False
        cur = conn.cursor()
        _seed_user_tenant(cur, tenant)
        _seed_market(cur, tenant, -501, -999999, ['OrphanMarketTag'], 'N')
        _assert_migration_blocked(cur, 'canonical_source_missing_or_tenant_mismatch')
    finally:
        conn.rollback()
        conn.close()


def _assert_idempotent_replay():
    tenant = 'dep-auto-' + uuid.uuid4().hex[:12]
    conn = _connect()
    try:
        conn.autocommit = False
        cur = conn.cursor()
        _seed_user_tenant(cur, tenant)
        _seed_mcp(cur, tenant, -601, ['RepeatTag', 'repeatTag'], 'N')

        body = _migration_body()
        cur.execute(body)

        values_before = set(_keyword_values(cur, tenant))
        assignments_before = set(_assignments(cur, tenant, 'N'))

        _drop_migration_temp_tables(cur)
        cur.execute(body)

        assert set(_keyword_values(cur, tenant)) == values_before
        assert set(_assignments(cur, tenant, 'N')) == assignments_before
        assert sorted(_keyword_values(cur, tenant)) == ['repeattag']
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D5')
def test_mcp_tag_legacy_migration_backfill():
    _assert_happy_path_migration()
    _assert_community_blocking()
    _assert_market_missing_source_blocking()
    _assert_idempotent_replay()
