"""Opt-in PostgreSQL integration coverage for Dreaming advisory locks."""

import os

import psycopg2
import pytest

from database.memory_dreaming_db import advisory_lock_key

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="set RUN_POSTGRES_INTEGRATION=1 with local PostgreSQL env",
)


def _connect():
    return psycopg2.connect(
        host=os.getenv("DREAMING_TEST_POSTGRES_HOST", os.environ["POSTGRES_HOST"]),
        port=os.getenv("DREAMING_TEST_POSTGRES_PORT", os.environ["POSTGRES_PORT"]),
        user=os.getenv("DREAMING_TEST_POSTGRES_USER", os.environ["POSTGRES_USER"]),
        password=os.getenv(
            "DREAMING_TEST_POSTGRES_PASSWORD",
            os.environ["NEXENT_POSTGRES_PASSWORD"],
        ),
        dbname=os.getenv("DREAMING_TEST_POSTGRES_DB", os.environ["POSTGRES_DB"]),
    )


def _try_lock(connection, lock_key):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", (lock_key,))
        return cursor.fetchone()[0]


def test_ac007_real_postgres_scope_lock_is_non_blocking_and_released():
    same_scope = advisory_lock_key("dreaming-it", "user", "agent")
    other_scope = advisory_lock_key("dreaming-it", "user", "other-agent")

    first = _connect()
    second = _connect()
    try:
        assert _try_lock(first, same_scope) is True
        assert _try_lock(second, same_scope) is False
        assert _try_lock(second, other_scope) is True

        first.rollback()
        assert _try_lock(second, same_scope) is True
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()


def test_ac010_real_postgres_audit_schema_matches_orm_contract():
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'nexent'
                  AND table_name = 'memory_dreaming_audit_t'
                """
            )
            columns = {row[0] for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'nexent'
                  AND tablename = 'memory_dreaming_audit_t'
                """
            )
            indexes = {row[0] for row in cursor.fetchall()}
        assert {
            "run_id",
            "tenant_id",
            "user_id",
            "agent_id",
            "status",
            "current_phase",
            "result_json",
            "error",
        } <= columns
        assert "idx_memory_dreaming_audit_scope" in indexes
    finally:
        connection.close()
