from __future__ import annotations

import os
import hashlib
from pathlib import Path

import pytest
from shared.config import repo_root
from shared.postgres import postgres_sql, postgres_target
from shared.factories.scratch_database import scratch_name, create_scratch, drop_scratch

CASE_ID = 'DEP-AUTO-3BABDFB6FBFB43A1'
STAGE = 'D5'

SCHEMA = 'nexent'
TABLE = 'model_monitoring_record_t'

MIGRATION_FILE = Path(
    os.environ.get(
        'CONTEXT_BUDGET_V2_MIGRATION',
        str(repo_root() / 'deploy/sql/migrations/v2.5.4_0910_context_budget_v2.sql'),
    )
)

MISSING_TABLE_MESSAGE = (
    'nexent.model_monitoring_record_t must exist before Context Budget V2 migration'
)
BACKFILL_CONSISTENCY_MESSAGE = (
    'Context Budget V2 historical backfill consistency check failed'
)

# legacy column -> final column used by the rename/merge steps of the migration.
RENAME_MAP = {
    'provider_input_limit_tokens': 'effective_input_limit_tokens',
    'budget_provider_input_limit_tokens': 'budget_effective_input_limit_tokens',
    'budget_soft_limit_ratio': 'budget_compaction_trigger_ratio',
    'budget_soft_input_budget_tokens': 'budget_compaction_trigger_threshold_tokens',
}

V2_ADDED_COLUMNS = [
    'budget_schema_version',
    'budget_compaction_trigger_ratio_source',
    'budget_compaction_target_ratio',
    'budget_compaction_target_ratio_source',
    'budget_compaction_target_tokens',
]

COLUMN_TYPES = {
    'budget_fingerprint': 'VARCHAR(255)',
    'provider_input_limit_tokens': 'INTEGER',
    'effective_input_limit_tokens': 'INTEGER',
    'budget_provider_input_limit_tokens': 'INTEGER',
    'budget_effective_input_limit_tokens': 'INTEGER',
    'budget_soft_limit_ratio': 'FLOAT',
    'budget_compaction_trigger_ratio': 'FLOAT',
    'budget_soft_input_budget_tokens': 'INTEGER',
    'budget_compaction_trigger_threshold_tokens': 'INTEGER',
    'budget_hard_input_budget_tokens': 'INTEGER',
    'budget_schema_version': 'INTEGER',
    'budget_compaction_trigger_ratio_source': 'VARCHAR(32)',
    'budget_compaction_target_ratio': 'FLOAT',
    'budget_compaction_target_ratio_source': 'VARCHAR(32)',
    'budget_compaction_target_tokens': 'INTEGER',
}


def _pg_env():
    target = postgres_target()
    return {
        'host': target.host, 'port': target.port, 'user': target.user,
        'password': target.password,
        'dbname': os.environ.get('NEXENT_TEST_SCRATCH_DATABASE') or target.database,
    }


def _scratch_database() -> str:
    return scratch_name()


def _create_scratch_database(name: str) -> None:
    create_scratch(name)


def _drop_scratch_database(name: str) -> None:
    drop_scratch(name)


def _connect():
    import psycopg2

    try:
        connection = psycopg2.connect(**_pg_env())
    except Exception:
        scratch = os.environ.pop('NEXENT_TEST_SCRATCH_DATABASE',None)
        if scratch:
            drop_scratch(scratch)
        raise
    connection.autocommit = True
    return connection


def _migration_sql():
    return MIGRATION_FILE.read_text(encoding='utf-8')


def _execute(connection, statement, params=None):
    with connection.cursor() as cursor:
        cursor.execute(statement, params)


def _query_one(connection, statement, params=None):
    with connection.cursor() as cursor:
        cursor.execute(statement, params)
        return cursor.fetchone()


def _query_all(connection, statement, params=None):
    with connection.cursor() as cursor:
        cursor.execute(statement, params)
        return cursor.fetchall()


def _reset_schema(connection):
    _execute(connection, 'DROP SCHEMA IF EXISTS ' + SCHEMA + ' CASCADE')
    _execute(connection, 'CREATE SCHEMA ' + SCHEMA)


def _drop_schema(connection):
    try:
        _execute(connection, 'DROP SCHEMA IF EXISTS ' + SCHEMA + ' CASCADE')
    except Exception:
        pass


def _qualified():
    return SCHEMA + '.' + TABLE


def _create_table(connection, columns):
    definitions = ['id INTEGER']
    for column in columns:
        definitions.append(column + ' ' + COLUMN_TYPES[column])
    _execute(
        connection,
        'CREATE TABLE ' + _qualified() + ' (' + ', '.join(definitions) + ')',
    )


def _insert(connection, record_id, values):
    columns = ['id'] + list(values.keys())
    quoted = ', '.join(columns)
    placeholders = ', '.join(['%s'] * len(columns))
    params = [record_id] + list(values.values())
    _execute(
        connection,
        'INSERT INTO ' + _qualified() + ' (' + quoted + ') VALUES (' + placeholders + ')',
        params,
    )


def _columns(connection):
    rows = _query_all(
        connection,
        'SELECT column_name FROM information_schema.columns '
        'WHERE table_schema = %s AND table_name = %s',
        (SCHEMA, TABLE),
    )
    return {row[0] for row in rows}


def _table_exists(connection):
    row = _query_one(
        connection,
        'SELECT to_regclass(%s) IS NOT NULL',
        (_qualified(),),
    )
    return bool(row[0])


def _row(connection, record_id):
    rows = _query_all(connection, 'SELECT * FROM ' + _qualified() + ' WHERE id = %s', (record_id,))
    assert len(rows) == 1
    names = _query_all(
        connection,
        'SELECT column_name FROM information_schema.columns '
        'WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position',
        (SCHEMA, TABLE),
    )
    return dict(zip((name[0] for name in names), rows[0]))


def _run_migration(connection):
    _execute(connection, _migration_sql())


def _expect_migration_error(connection, expected_message):
    import psycopg2

    with pytest.raises(psycopg2.Error) as caught:
        _execute(connection, _migration_sql())
    # The failed script aborts its explicit transaction; roll it back so this
    # connection stays reusable for the next scenario.
    _execute(connection, 'ROLLBACK')
    assert expected_message in str(caught.value)
    return caught.value


def _floor_target_tokens(effective_tokens):
    # PostgreSQL computes FLOOR(integer * 0.6) with exact NUMERIC arithmetic;
    # 0.6 == 6/10 makes this integer math exact.
    return effective_tokens * 6 // 10


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage(STAGE)
def test_context_budget_v2_migration():
    scratch = _scratch_database()
    _create_scratch_database(scratch)
    os.environ['NEXENT_TEST_SCRATCH_DATABASE'] = scratch
    connection = _connect()
    try:
        _reset_schema(connection)

        # Scenario 1: legacy-only columns are renamed and V1 history backfilled.
        _create_table(
            connection,
            [
                'budget_fingerprint',
                'provider_input_limit_tokens',
                'budget_provider_input_limit_tokens',
                'budget_soft_limit_ratio',
                'budget_soft_input_budget_tokens',
                'budget_hard_input_budget_tokens',
            ],
        )
        _insert(
            connection,
            1,
            {
                'budget_fingerprint': 'fp_1',
                'provider_input_limit_tokens': 1000,
                'budget_provider_input_limit_tokens': 800,
                'budget_soft_limit_ratio': 0.8,
                'budget_soft_input_budget_tokens': 600,
                'budget_hard_input_budget_tokens': 1234,
            },
        )
        _run_migration(connection)
        columns = _columns(connection)
        for legacy, target in RENAME_MAP.items():
            assert legacy not in columns, legacy
            assert target in columns, target
        for added in V2_ADDED_COLUMNS:
            assert added in columns, added
        assert 'budget_hard_input_budget_tokens' not in columns
        row = _row(connection, 1)
        assert row['effective_input_limit_tokens'] == 1000
        assert row['budget_effective_input_limit_tokens'] == 800
        assert row['budget_compaction_trigger_ratio'] == 0.8
        assert row['budget_compaction_trigger_threshold_tokens'] == 600
        assert row['budget_schema_version'] == 1
        assert row['budget_compaction_trigger_ratio_source'] == 'legacy_payload'
        assert row['budget_compaction_target_ratio'] == 0.6
        assert row['budget_compaction_target_ratio_source'] == 'code_default'
        assert row['budget_compaction_target_tokens'] == _floor_target_tokens(800)

        # Scenario 2: coexisting legacy + final columns merge then drop the source.
        _reset_schema(connection)
        _create_table(
            connection,
            [
                'budget_fingerprint',
                'provider_input_limit_tokens',
                'effective_input_limit_tokens',
                'budget_provider_input_limit_tokens',
                'budget_effective_input_limit_tokens',
                'budget_soft_limit_ratio',
                'budget_compaction_trigger_ratio',
                'budget_soft_input_budget_tokens',
                'budget_compaction_trigger_threshold_tokens',
                'budget_hard_input_budget_tokens',
            ],
        )
        _insert(
            connection,
            1,
            {
                'provider_input_limit_tokens': 1100,
                'budget_provider_input_limit_tokens': 900,
                'budget_soft_limit_ratio': 0.7,
                'budget_soft_input_budget_tokens': 700,
                'budget_hard_input_budget_tokens': 1,
            },
        )
        _insert(
            connection,
            2,
            {
                'effective_input_limit_tokens': 2100,
                'provider_input_limit_tokens': 999,
                'budget_effective_input_limit_tokens': 1900,
                'budget_provider_input_limit_tokens': 999,
                'budget_compaction_trigger_ratio': 0.65,
                'budget_soft_limit_ratio': 0.99,
                'budget_compaction_trigger_threshold_tokens': 1700,
                'budget_soft_input_budget_tokens': 999,
                'budget_hard_input_budget_tokens': 2,
            },
        )
        _run_migration(connection)
        columns = _columns(connection)
        for legacy in RENAME_MAP:
            assert legacy not in columns, legacy
        row1 = _row(connection, 1)
        assert row1['effective_input_limit_tokens'] == 1100
        assert row1['budget_effective_input_limit_tokens'] == 900
        assert row1['budget_compaction_trigger_ratio'] == 0.7
        assert row1['budget_compaction_trigger_threshold_tokens'] == 700
        row2 = _row(connection, 2)
        assert row2['effective_input_limit_tokens'] == 2100
        assert row2['budget_effective_input_limit_tokens'] == 1900
        assert row2['budget_compaction_trigger_ratio'] == 0.65
        assert row2['budget_compaction_trigger_threshold_tokens'] == 1700
        assert 'budget_hard_input_budget_tokens' not in columns

        # Scenario 3: idempotent re-apply leaves the final state untouched.
        _run_migration(connection)
        assert _columns(connection) == columns
        assert _row(connection, 1) == row1
        assert _row(connection, 2) == row2

        # Scenario 4: inconsistent V1 backfill raises and rolls back cleanly.
        _reset_schema(connection)
        _create_table(
            connection,
            [
                'budget_fingerprint',
                'provider_input_limit_tokens',
                'budget_provider_input_limit_tokens',
                'budget_soft_limit_ratio',
                'budget_soft_input_budget_tokens',
                'budget_hard_input_budget_tokens',
                'budget_schema_version',
                'budget_compaction_trigger_ratio_source',
                'budget_compaction_target_ratio',
                'budget_compaction_target_ratio_source',
                'budget_compaction_target_tokens',
            ],
        )
        _insert(
            connection,
            1,
            {
                'budget_fingerprint': 'fp_2',
                'provider_input_limit_tokens': 1000,
                'budget_provider_input_limit_tokens': 800,
                'budget_soft_limit_ratio': 0.8,
                'budget_soft_input_budget_tokens': 600,
                'budget_hard_input_budget_tokens': 1234,
                'budget_schema_version': 1,
                'budget_compaction_trigger_ratio_source': 'legacy_payload',
                'budget_compaction_target_ratio': 0.7,
                'budget_compaction_target_ratio_source': 'code_default',
                'budget_compaction_target_tokens': _floor_target_tokens(800),
            },
        )
        _expect_migration_error(connection, BACKFILL_CONSISTENCY_MESSAGE)
        inspector = _connect()
        try:
            rolled_back_columns = _columns(inspector)
            assert 'provider_input_limit_tokens' in rolled_back_columns
            assert 'effective_input_limit_tokens' not in rolled_back_columns
            assert 'budget_hard_input_budget_tokens' in rolled_back_columns
        finally:
            inspector.close()

        # Scenario 5: missing table is blocked without partial DDL.
        _reset_schema(connection)
        _expect_migration_error(connection, MISSING_TABLE_MESSAGE)
        assert _table_exists(connection) is False
    finally:
        _drop_schema(connection)
        connection.close()
        os.environ.pop('NEXENT_TEST_SCRATCH_DATABASE', None)
        _drop_scratch_database(scratch)
