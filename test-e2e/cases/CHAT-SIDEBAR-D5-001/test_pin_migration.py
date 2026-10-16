# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Execute the deployment SQL against disposable PostgreSQL schemas only."""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database.client import db_client

pytestmark = [pytest.mark.case_id("CHAT-SIDEBAR-D5-001"), pytest.mark.stage("D5")]

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "deploy/sql/migrations/v2.7.1_004_workbench_pin_timestamp.sql"


@pytest.fixture
def schema():
    name = "wb_pin_migrate_" + uuid4().hex
    with db_client.engine.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {name}"))
        connection.execute(text(f"""CREATE TABLE {name}.conversation_record_t (
            conversation_id INT PRIMARY KEY, created_by VARCHAR(100), updated_by VARCHAR(100),
            conversation_title VARCHAR(100), workbench_config JSONB, delete_flag VARCHAR(1),
            create_time TIMESTAMP, update_time TIMESTAMP)"""))
        connection.execute(text(f"""INSERT INTO {name}.conversation_record_t
            SELECT id, CASE WHEN id=3 THEN 'other' ELSE 'owner' END, 'original', 'History',
            CASE WHEN id=5 THEN NULL WHEN id=6 THEN 'null'::jsonb ELSE '{{}}'::jsonb END,
            CASE WHEN id=4 THEN 'Y' ELSE 'N' END, '2026-01-01', '2026-01-02'
            FROM generate_series(1,8) id"""))
    try:
        yield name
    finally:
        with db_client.engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {name} CASCADE"))


def legacy(name, ambiguous=False):
    with db_client.engine.begin() as connection:
        connection.execute(text(f"""CREATE TABLE {name}.conversation_workbench_pin_t (
            pin_id SERIAL PRIMARY KEY, user_id VARCHAR(100), tenant_id VARCHAR(100),
            conversation_id INT, pinned_at TIMESTAMPTZ, delete_flag VARCHAR(1))"""))
        connection.execute(text(f"""INSERT INTO {name}.conversation_workbench_pin_t
            (user_id,tenant_id,conversation_id,pinned_at,delete_flag) VALUES
            ('owner','a',1,'2026-02-01','N'), ('owner','a',1,'2026-03-01','N'),
            ('owner','a',2,'2026-02-01','N'), ('owner','a',2,'2026-02-02','Y'),
            ('owner','a',3,'2026-02-01','N'), ('owner','a',4,'2026-02-01','N'),
            ('owner','a',5,'2026-02-01','N'), ('owner','a',6,'2026-02-01','N'),
            ('owner','b',8,'2026-02-01','N'), ('owner','a',999,'2026-02-01','N')"""))
        if ambiguous:
            connection.execute(text(f"""INSERT INTO {name}.conversation_workbench_pin_t
                (user_id,tenant_id,conversation_id,pinned_at,delete_flag)
                VALUES ('owner','b',1,'2026-04-01','N')"""))


def migrate(name):
    sql = MIGRATION.read_text(encoding="utf-8").replace("nexent.", name + ".").replace("'nexent'", repr(name))
    with db_client.engine.begin() as connection:
        connection.exec_driver_sql(sql)


def snapshot(name):
    with db_client.engine.connect() as connection:
        return connection.execute(text(f"SELECT conversation_id,created_by,updated_by,conversation_title,workbench_config,delete_flag,create_time,update_time FROM {name}.conversation_record_t ORDER BY conversation_id")).all()


def test_legacy_backfill_and_rerun_preserve_personal_pins_and_activity(schema):
    legacy(schema)
    before = snapshot(schema)
    migrate(schema)
    with db_client.engine.begin() as connection:
        rows = connection.execute(text(f"SELECT conversation_id,workbench_pinned_at::text FROM {schema}.conversation_record_t ORDER BY conversation_id")).all()
        assert [id for id,stamp in rows if stamp is not None] == [1,8]
        assert rows[0][1].startswith("2026-03-01")
        assert connection.scalar(text(f"SELECT count(*) FROM {schema}.conversation_workbench_pin_t")) == 10
        assert connection.scalar(text(f"SELECT col_description('{schema}.conversation_record_t'::regclass, attnum) FROM pg_attribute WHERE attrelid='{schema}.conversation_record_t'::regclass AND attname='workbench_pinned_at'"))
        index = connection.scalar(text("SELECT indexdef FROM pg_indexes WHERE schemaname=:schema AND indexname='idx_conversation_workbench_pin_order'"), {"schema":schema})
        assert "created_by, workbench_pinned_at DESC, conversation_id DESC" in index
        connection.execute(text(f"UPDATE {schema}.conversation_record_t SET workbench_pinned_at=NULL WHERE conversation_id=1"))
    migrate(schema)
    with db_client.engine.connect() as connection:
        assert connection.scalar(text(f"SELECT workbench_pinned_at FROM {schema}.conversation_record_t WHERE conversation_id=1")) is None
        assert connection.scalar(text(f"SELECT count(*) FROM {schema}.conversation_record_t WHERE workbench_pinned_at IS NOT NULL")) == 1
    assert snapshot(schema) == before


def test_ambiguous_legacy_tenants_abort_atomically_without_losing_state(schema):
    legacy(schema, ambiguous=True)
    before = snapshot(schema)
    with pytest.raises(DBAPIError, match="Ambiguous Workbench pins across tenants"):
        migrate(schema)
    with db_client.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_schema=:schema AND table_name='conversation_record_t' AND column_name='workbench_pinned_at'"), {"schema": schema}) == 0
        assert connection.scalar(text(f"SELECT count(*) FROM {schema}.conversation_workbench_pin_t")) == 11
    assert snapshot(schema) == before


def test_fresh_install_without_legacy_table_is_repeatable(schema):
    before = snapshot(schema)
    migrate(schema)
    migrate(schema)
    with db_client.engine.connect() as connection:
        assert connection.scalar(text(f"SELECT count(*) FROM {schema}.conversation_record_t WHERE workbench_pinned_at IS NOT NULL")) == 0
    assert snapshot(schema) == before
