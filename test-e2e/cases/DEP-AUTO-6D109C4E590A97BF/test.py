'''D5-SPECIAL upgrade-compatibility test: conversation_source_search_t citation migration.

Verifies deploy/sql/migrations/v2.5.0_0813_conversation_source_search_citation.sql:

* adds retrieval_highlight_terms as jsonb
* widens score_overall to numeric(14, 6)
* high-precision relevance scores and highlight terms persist and round-trip losslessly
* the migration is safe to re-run (idempotent)
'''

from __future__ import annotations

import json
import os
from decimal import Decimal

import pytest

from shared.config import repo_root
from shared.postgres import postgres_target
from shared.postgres import postgres_connect_kwargs as _postgres_config

CASE_ID = 'DEP-AUTO-6D109C4E590A97BF'
_SCHEMA = 'nexent'
_TABLE = 'conversation_source_search_t'
_MIGRATION_REL = 'deploy/sql/migrations/v2.5.0_0813_conversation_source_search_citation.sql'


def _execute_script(cursor, script):
    for statement in script.split(';'):
        statement = statement.strip()
        if statement:
            cursor.execute(statement)


def _table_exists(cursor):
    cursor.execute(
        'SELECT 1 FROM information_schema.tables '
        'WHERE table_schema = %s AND table_name = %s',
        (_SCHEMA, _TABLE),
    )
    return cursor.fetchone() is not None


def _column_metadata(cursor, column):
    cursor.execute(
        'SELECT data_type, udt_name, numeric_precision, numeric_scale '
        'FROM information_schema.columns '
        'WHERE table_schema = %s AND table_name = %s AND column_name = %s',
        (_SCHEMA, _TABLE, column),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {
        'data_type': row[0],
        'udt_name': row[1],
        'numeric_precision': row[2],
        'numeric_scale': row[3],
    }


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D5')
def test_conversation_source_search_citation_migration():
    import psycopg2

    migration_file = repo_root() / _MIGRATION_REL
    assert migration_file.is_file(), f'migration file not found: {migration_file}'
    migration_sql = migration_file.read_text(encoding='utf-8')

    conn = psycopg2.connect(**_postgres_config())
    conn.autocommit = True
    cursor = conn.cursor()
    try:
        assert _table_exists(cursor), (
            f'precondition failed: {_SCHEMA}.{_TABLE} missing in local test database'
        )

        _execute_script(cursor, migration_sql)

        highlight = _column_metadata(cursor, 'retrieval_highlight_terms')
        assert highlight is not None, 'retrieval_highlight_terms column missing after migration'
        udt = highlight['udt_name']
        assert udt == 'jsonb', f'retrieval_highlight_terms expected jsonb, got {udt!r}'

        score = _column_metadata(cursor, 'score_overall')
        assert score is not None, 'score_overall column missing after migration'
        precision = score['numeric_precision']
        scale = score['numeric_scale']
        assert (precision, scale) == (14, 6), f'score_overall expected numeric(14,6), got numeric({precision},{scale})'

        high_precision = Decimal('12345678.123456')
        highlight_terms = ['nexent', 'citation', 'source highlight']

        conn.autocommit = False
        try:
            cursor.execute(
                'INSERT INTO nexent.conversation_source_search_t '
                '(score_overall, retrieval_highlight_terms) '
                'VALUES (%s, %s::jsonb) '
                'RETURNING score_overall, retrieval_highlight_terms',
                (high_precision, json.dumps(highlight_terms)),
            )
            read_score, read_terms = cursor.fetchone()
            assert read_score == high_precision, (
                f'high-precision score truncated: wrote {high_precision}, read back {read_score}'
            )
            assert read_terms == highlight_terms, (
                f'highlight terms lost or reordered: wrote {highlight_terms}, read back {read_terms}'
            )

            legacy_score = Decimal('0.123456')
            cursor.execute(
                'INSERT INTO nexent.conversation_source_search_t '
                '(score_overall, retrieval_highlight_terms) '
                'VALUES (%s, NULL) '
                'RETURNING score_overall, retrieval_highlight_terms',
                (legacy_score,),
            )
            legacy_read_score, legacy_read_terms = cursor.fetchone()
            assert legacy_read_score == legacy_score, (
                f'legacy score corrupted: wrote {legacy_score}, read back {legacy_read_score}'
            )
            assert legacy_read_terms is None, (
                f'legacy row highlight terms expected NULL, got {legacy_read_terms!r}'
            )
        finally:
            conn.rollback()
            conn.autocommit = True

        _execute_script(cursor, migration_sql)
        cursor.execute(
            'SELECT count(*) FROM information_schema.columns '
            'WHERE table_schema = %s AND table_name = %s AND column_name = %s',
            (_SCHEMA, _TABLE, 'retrieval_highlight_terms'),
        )
        column_count = cursor.fetchone()[0]
        assert column_count == 1, (
            f'migration not idempotent: {column_count} retrieval_highlight_terms columns found'
        )
    finally:
        cursor.close()
        conn.close()
