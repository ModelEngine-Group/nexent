"""Opt-in PostgreSQL integration coverage for Dreaming advisory locks."""

import os
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from database.db_models import MemoryDreamingAudit, MemoryDreamingDecision, MemoryLongTermVersion
from database.memory_dreaming_db import advisory_lock_key

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="set RUN_POSTGRES_INTEGRATION=1 with local PostgreSQL env",
)

DREAMING_SOURCE_MARKER = (
    "-- Source migration: v2.5.0_0813_versioned_markdown_long_term_memory.sql"
)


def _read_dreaming_migration() -> str:
    root = Path(__file__).resolve().parents[3]
    merged = (root / "deploy/sql/migrations/v2.5.0_merged_migrations.sql").read_text()
    assert DREAMING_SOURCE_MARKER in merged
    dreaming_and_later = merged.split(DREAMING_SOURCE_MARKER, maxsplit=1)[1]
    next_source_marker = "\n-- Source migration:"
    assert next_source_marker in dreaming_and_later
    return dreaming_and_later.split(next_source_marker, maxsplit=1)[0]


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
            cursor.execute(
                """
                SELECT data_type, udt_name
                FROM information_schema.columns
                WHERE table_schema = 'nexent'
                  AND table_name = 'memory_dreaming_decision_t'
                  AND column_name = 'evidence_ids'
                """
            )
            decision_evidence_type = cursor.fetchone()
            cursor.execute(
                """
                SELECT data_type, udt_name
                FROM information_schema.columns
                WHERE table_schema = 'nexent'
                  AND table_name = 'memory_long_term_version_t'
                  AND column_name = 'evidence_ids'
                """
            )
            long_term_evidence_type = cursor.fetchone()
        assert {
            "run_id",
            "tenant_id",
            "user_id",
            "agent_id",
            "status",
            "current_phase",
            "published_version_id",
            "reason",
            "error",
        } <= columns
        assert "decisions" not in columns
        assert "idx_memory_dreaming_audit_scope" in indexes
        assert decision_evidence_type == ("ARRAY", "_varchar")
        assert long_term_evidence_type == ("jsonb", "jsonb")
    finally:
        connection.close()


def test_ac010_real_postgres_evidence_types_round_trip_through_orm():
    engine = create_engine(
        URL.create(
            "postgresql+psycopg2",
            username=os.getenv("DREAMING_TEST_POSTGRES_USER", os.environ["POSTGRES_USER"]),
            password=os.getenv(
                "DREAMING_TEST_POSTGRES_PASSWORD",
                os.environ["NEXENT_POSTGRES_PASSWORD"],
            ),
            host=os.getenv("DREAMING_TEST_POSTGRES_HOST", os.environ["POSTGRES_HOST"]),
            port=int(os.getenv("DREAMING_TEST_POSTGRES_PORT", os.environ["POSTGRES_PORT"])),
            database=os.getenv("DREAMING_TEST_POSTGRES_DB", os.environ["POSTGRES_DB"]),
        )
    )
    subject_id = f"schema-test-{uuid4()}"
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(bind=connection) as session:
                audit = MemoryDreamingAudit(
                    tenant_id="schema-test",
                    user_id="schema-test",
                    agent_id="__user__",
                    status="completed",
                )
                session.add(audit)
                session.flush()
                decision = MemoryDreamingDecision(
                    run_id=audit.run_id,
                    decision_order=0,
                    memory_id=64,
                    score=0.91,
                    evidence_ids=["64", "65"],
                    event="SELECT",
                    reason="eligible",
                )
                session.add(decision)
                version = MemoryLongTermVersion(
                    tenant_id="schema-test",
                    scope="user",
                    subject_id=subject_id,
                    version_no=1,
                    is_active=True,
                    content="## Schema test",
                    source="manual",
                    author_user_id="schema-test",
                    editor_user_id="schema-test",
                    character_count=14,
                    evidence_ids=["64", "65"],
                )
                session.add(version)
                session.flush()
                session.expire_all()
                assert decision.evidence_ids == ["64", "65"]
                assert version.evidence_ids == ["64", "65"]
        finally:
            transaction.rollback()
            engine.dispose()


def test_ac075_real_postgres_upgrades_json_decisions_and_is_repeatable():
    connection = _connect()
    migration = _read_dreaming_migration()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE nexent.memory_dreaming_audit_t "
                "ADD COLUMN decisions JSONB NOT NULL DEFAULT '[]'::jsonb"
            )
            cursor.execute(
                """
                INSERT INTO nexent.memory_dreaming_audit_t (
                    tenant_id, user_id, agent_id, status, decisions
                ) VALUES (
                    'migration-test', 'migration-test', '', 'completed',
                    '[{"memory_id":64,"score":0.91,"noise":false,"signal_count":5,
                       "context_diversity":3,"evidence_ids":["64"],"event":"SELECT",
                       "reason":"eligible","archive_suggested":false}]'::jsonb
                ) RETURNING run_id
                """
            )
            run_id = cursor.fetchone()[0]
            cursor.execute(migration)
            cursor.execute(migration)
            cursor.execute(
                """
                SELECT memory_id, score, signal_count, context_diversity, event, reason
                FROM nexent.memory_dreaming_decision_t WHERE run_id = %s
                """,
                (run_id,),
            )
            assert cursor.fetchall() == [(64, 0.91, 5, 3, "SELECT", "eligible")]
            cursor.execute(
                """
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_schema = 'nexent' AND table_name = 'memory_dreaming_audit_t'
                  AND column_name = 'decisions'
                """
            )
            assert cursor.fetchone()[0] == 0
    finally:
        connection.rollback()
        connection.close()
