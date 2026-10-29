# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execute the additive migration against legacy PostgreSQL fixtures only."""

import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra" / "automation"))
from shared.postgres import postgres_sql


ROOT = Path(__file__).resolve().parents[3]
MERGED = ROOT / "deploy/sql/migrations/v2.8.0_merged_migrations.sql"
SECTION = "v2.7.1_007_conversation_activity_and_source.sql"


def migration_source():
    """Read this case's section out of the consolidated v2.8.0 migration bundle."""
    text = MERGED.read_text(encoding="utf-8")
    marker = f"-- Source migration: {SECTION}"
    start = text.index(marker)
    end = text.find("-- Source migration: ", start + len(marker))
    return text[start:] if end == -1 else text[start:end]


@pytest.mark.case_id("CHAT-ACTIVITY-D5-001")
@pytest.mark.stage("D5")
@pytest.mark.parametrize("zone", ["UTC", "Asia/Shanghai", "America/New_York"])
@pytest.mark.parametrize("existing_activity", [False, True])
def test_additive_migration_and_repeatability(zone, existing_activity):
    schema = "activity_migration_" + uuid4().hex
    source = migration_source()
    assert "CREATE TABLE" not in source.upper()
    sql = f"SET TIME ZONE '{zone}';\n" + source.replace("nexent.", schema + ".")
    try:
        postgres_sql(f"""
            CREATE SCHEMA {schema};
            CREATE TABLE {schema}.conversation_record_t (
                conversation_id INTEGER PRIMARY KEY, created_by VARCHAR(100), delete_flag VARCHAR(1),
                create_time TIMESTAMP, update_time TIMESTAMP);
            CREATE TABLE {schema}.conversation_message_t (
                message_id INTEGER PRIMARY KEY, conversation_id INTEGER, message_role VARCHAR(30),
                message_content TEXT, delete_flag VARCHAR(1), create_time TIMESTAMP);
            CREATE TABLE {schema}.agent_automation_run_t (
                conversation_id INTEGER, user_message_id INTEGER, assistant_message_id INTEGER);
            INSERT INTO {schema}.conversation_record_t VALUES
                (1,'owner','N','2026-01-01','2026-10-20'),(2,'owner','N','2026-02-01','2026-10-20');
            INSERT INTO {schema}.conversation_message_t VALUES
                (1,1,'user','manual','N','2026-03-01'),
                (2,1,'user','automation','N','2026-04-01'),
                (3,1,'assistant','answer','N','2026-04-02 00:00:00.123456'),
                (4,1,'user','deleted','Y','2026-10-01'),
                (5,1,'assistant','','N','2026-10-02'),
                (6,1,'user','unlinked automation','N','2026-03-15'),
                (7,1,'user','wrong conversation reference','N','2026-03-16'),
                (8,1,'user','deleted automation','Y','2026-10-01');
            INSERT INTO {schema}.agent_automation_run_t VALUES
                (1,2,3),(1,2,3),(1,NULL,NULL),(2,7,NULL),
                (1,999998,999999),(1,8,NULL);
        """)
        if existing_activity:
            postgres_sql(f"""
                ALTER TABLE {schema}.conversation_record_t ADD COLUMN last_activity_time TIMESTAMP;
                UPDATE {schema}.conversation_record_t SET last_activity_time =
                    TIMESTAMP '2026-04-03 12:34:56.654321' WHERE conversation_id=1;
                CREATE INDEX idx_conversation_activity_order ON {schema}.conversation_record_t
                    (created_by, (COALESCE(last_activity_time, create_time)) DESC, conversation_id DESC)
                    WHERE delete_flag='N';
            """)
        audit_query = f"SELECT conversation_id,created_by,delete_flag,create_time,update_time FROM {schema}.conversation_record_t ORDER BY conversation_id;"
        audits = postgres_sql(audit_query)
        prior_epoch = postgres_sql(f"SELECT extract(epoch FROM last_activity_time) FROM {schema}.conversation_record_t WHERE conversation_id=1;") if existing_activity else None
        conversation_versions_query = f"SELECT conversation_id,xmin FROM {schema}.conversation_record_t ORDER BY conversation_id;"
        conversation_versions = postgres_sql(conversation_versions_query)
        postgres_sql(sql)
        assert postgres_sql(conversation_versions_query) == conversation_versions
        assert postgres_sql(f"SELECT data_type FROM information_schema.columns WHERE table_schema='{schema}' AND table_name='conversation_record_t' AND column_name='last_activity_time';").strip() == "timestamp without time zone"
        if existing_activity:
            assert postgres_sql(f"SELECT extract(epoch FROM last_activity_time) FROM {schema}.conversation_record_t WHERE conversation_id=1;") == prior_epoch
        def snapshot():
            return postgres_sql(f"""
                SELECT message_id,message_source FROM {schema}.conversation_message_t ORDER BY message_id;
                SELECT conversation_id,last_activity_time
                  FROM {schema}.conversation_record_t ORDER BY conversation_id;
            """)
        expected = snapshot()
        assert "1\tCHAT" in expected and "2\tAUTOMATION" in expected and "3\tAUTOMATION" in expected
        assert "4\tCHAT" in expected and "5\tCHAT" in expected
        assert "6\tCHAT" in expected and "7\tCHAT" in expected and "8\tAUTOMATION" in expected
        activities = postgres_sql(f"SELECT conversation_id,COALESCE(last_activity_time::text,'NULL') FROM {schema}.conversation_record_t ORDER BY conversation_id;")
        assert activities.strip().splitlines() == [
            "1\t" + ("2026-04-03 12:34:56.654321" if existing_activity else "NULL"),
            "2\tNULL",
        ]
        effective = postgres_sql(f"SELECT conversation_id,COALESCE(last_activity_time,create_time) FROM {schema}.conversation_record_t ORDER BY COALESCE(last_activity_time,create_time) DESC,conversation_id DESC;")
        assert effective.strip().splitlines() == (
            ["1\t2026-04-03 12:34:56.654321", "2\t2026-02-01 00:00:00"]
            if existing_activity else ["2\t2026-02-01 00:00:00", "1\t2026-01-01 00:00:00"]
        )
        message_versions_query = f"SELECT message_id,xmin FROM {schema}.conversation_message_t ORDER BY message_id;"
        message_versions = postgres_sql(message_versions_query)
        postgres_sql(sql)
        assert snapshot() == expected
        assert postgres_sql(message_versions_query) == message_versions
        assert postgres_sql(conversation_versions_query) == conversation_versions
        assert postgres_sql(audit_query) == audits
        index = postgres_sql(f"SELECT indexdef FROM pg_indexes WHERE schemaname='{schema}' AND indexname='idx_conversation_activity_order';")
        assert "COALESCE(last_activity_time, create_time)" in index and "AT TIME ZONE" not in index
        plan = postgres_sql(f"BEGIN; SET LOCAL enable_seqscan = off; EXPLAIN (COSTS OFF) SELECT conversation_id FROM {schema}.conversation_record_t WHERE created_by='owner' AND delete_flag='N' ORDER BY COALESCE(last_activity_time,create_time) DESC,conversation_id DESC; ROLLBACK;")
        assert "idx_conversation_activity_order" in plan
        assert postgres_sql(f"SELECT count(*) FROM pg_tables WHERE schemaname='{schema}';").strip() == "3"
        assert postgres_sql(f"SELECT count(*) FROM pg_indexes WHERE schemaname='{schema}' AND indexname LIKE 'idx_conversation_%';").strip() == "2"
        postgres_sql(f"INSERT INTO {schema}.conversation_message_t (message_id) VALUES (9);")
        assert postgres_sql(f"SELECT message_source FROM {schema}.conversation_message_t WHERE message_id=9;").strip() == "CHAT"
    finally:
        postgres_sql(f"DROP SCHEMA IF EXISTS {schema} CASCADE;")
        assert postgres_sql(f"SELECT count(*) FROM pg_namespace WHERE nspname='{schema}';").strip() == "0"
