# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Direct personal pin schema deployment in disposable PostgreSQL schemas."""

import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra/automation"))
from shared.postgres import postgres_url

pytestmark = [pytest.mark.case_id("CHAT-SIDEBAR-D5-001"), pytest.mark.stage("D5")]
ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "deploy/sql/migrations/v2.7.1_004_workbench_pin_timestamp.sql"
FOLLOWUP = ROOT / "deploy/sql/migrations/v2.7.1_009_workbench_pin_utc_timestamp.sql"


@pytest.fixture(params=["UTC", "Asia/Shanghai", "America/New_York"])
def engine(request):
    value = create_engine(postgres_url(), connect_args={"options": f"-c timezone={request.param}"})
    try:
        yield value
    finally:
        value.dispose()


@pytest.fixture
def schema(engine):
    name = "wb_pin_schema_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {name}"))
        connection.execute(text(f"""CREATE TABLE {name}.conversation_record_t (
            conversation_id INT PRIMARY KEY, created_by VARCHAR(100), updated_by VARCHAR(100),
            conversation_title VARCHAR(100), workbench_config JSONB, delete_flag VARCHAR(1),
            create_time TIMESTAMP, update_time TIMESTAMP)"""))
        connection.execute(text(f"""INSERT INTO {name}.conversation_record_t
            SELECT id, 'owner', 'original', 'History',
            CASE WHEN id=5 THEN NULL WHEN id=6 THEN 'null'::jsonb ELSE '{{}}'::jsonb END,
            CASE WHEN id=4 THEN 'Y' ELSE 'N' END, '2026-01-01', '2026-01-02'
            FROM generate_series(1,8) id"""))
    try:
        yield name
    finally:
        with engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {name} CASCADE"))
            assert connection.scalar(text("SELECT count(*) FROM pg_namespace WHERE nspname=:schema"), {"schema":name}) == 0


def migrate(name, engine, followup=True):
    with engine.begin() as connection:
        for path in (MIGRATION, FOLLOWUP) if followup else (MIGRATION,):
            sql = path.read_text(encoding="utf-8").replace("nexent.", name + ".").replace("'nexent'", repr(name))
            connection.exec_driver_sql(sql)


def snapshot(name, engine):
    with engine.connect() as connection:
        return connection.execute(text(f"SELECT conversation_id,created_by,updated_by,conversation_title,workbench_config,delete_flag,create_time,update_time FROM {name}.conversation_record_t ORDER BY conversation_id")).all()


def test_direct_pin_field_and_index_preserve_existing_conversations(schema, engine):
    before = snapshot(schema, engine)
    migrate(schema, engine)
    with engine.connect() as connection:
        column = connection.execute(text("SELECT data_type,is_nullable,column_default FROM information_schema.columns WHERE table_schema=:schema AND table_name='conversation_record_t' AND column_name='workbench_pinned_at'"), {"schema":schema}).one()
        assert tuple(column) == ("timestamp without time zone", "YES", None)
        assert connection.scalar(text(f"SELECT count(*) FROM {schema}.conversation_record_t WHERE workbench_pinned_at IS NULL")) == 8
        assert connection.scalar(text(f"SELECT col_description('{schema}.conversation_record_t'::regclass, attnum) FROM pg_attribute WHERE attrelid='{schema}.conversation_record_t'::regclass AND attname='workbench_pinned_at'"))
        index = connection.scalar(text("SELECT indexdef FROM pg_indexes WHERE schemaname=:schema AND indexname='idx_conversation_workbench_pin_order'"), {"schema":schema})
        assert "created_by, workbench_pinned_at DESC, conversation_id DESC" in index
        for predicate in ("delete_flag", "workbench_pinned_at IS NOT NULL", "workbench_config IS NOT NULL", "'null'::jsonb"):
            assert predicate in index
        tables = connection.scalars(text("SELECT table_name FROM information_schema.tables WHERE table_schema=:schema"), {"schema":schema}).all()
        assert tables == ["conversation_record_t"]
    assert snapshot(schema, engine) == before


@pytest.mark.parametrize("previously_deployed", [False, True])
def test_repeat_deployment_preserves_current_pin_and_activity(schema, engine, previously_deployed):
    before = snapshot(schema, engine)
    migrate(schema, engine, followup=not previously_deployed)
    value = "TIMESTAMPTZ '2026-10-16 08:00:00.123456+08'" if previously_deployed else "TIMESTAMP '2026-10-16 00:00:00.123456'"
    with engine.begin() as connection:
        connection.execute(text(f"UPDATE {schema}.conversation_record_t SET workbench_pinned_at={value} WHERE conversation_id IN (1,2)"))
        pins_before = connection.execute(text(f"SELECT conversation_id,extract(epoch FROM workbench_pinned_at) FROM {schema}.conversation_record_t ORDER BY conversation_id")).all()
    migrate(schema, engine)
    migrate(schema, engine)
    with engine.connect() as connection:
        assert connection.execute(text(f"SELECT conversation_id,extract(epoch FROM workbench_pinned_at) FROM {schema}.conversation_record_t ORDER BY conversation_id")).all() == pins_before
        assert connection.scalar(text(f"SELECT workbench_pinned_at FROM {schema}.conversation_record_t WHERE conversation_id=1")) == datetime(2026, 10, 16, microsecond=123456)
        assert connection.scalars(text(f"SELECT conversation_id FROM {schema}.conversation_record_t WHERE workbench_pinned_at IS NOT NULL ORDER BY workbench_pinned_at DESC,conversation_id DESC")).all() == [2, 1]
        assert connection.scalar(text("SELECT data_type FROM information_schema.columns WHERE table_schema=:schema AND table_name='conversation_record_t' AND column_name='workbench_pinned_at'"), {"schema":schema}) == "timestamp without time zone"
        assert connection.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_schema=:schema AND table_name='conversation_record_t' AND column_name='workbench_pinned_at'"), {"schema":schema}) == 1
        assert connection.scalar(text("SELECT count(*) FROM pg_indexes WHERE schemaname=:schema AND indexname='idx_conversation_workbench_pin_order'"), {"schema":schema}) == 1
        assert connection.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname=:schema"), {"schema":schema}) == 1
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL enable_seqscan=off"))
        plan = connection.execute(text(f"EXPLAIN (COSTS OFF) SELECT conversation_id FROM {schema}.conversation_record_t WHERE created_by='owner' AND delete_flag='N' AND workbench_pinned_at IS NOT NULL AND workbench_config IS NOT NULL AND workbench_config != 'null'::jsonb ORDER BY workbench_pinned_at DESC,conversation_id DESC")).all()
        assert "idx_conversation_workbench_pin_order" in str(plan)
    assert snapshot(schema, engine) == before


def test_catalog_does_not_create_a_separate_pin_table_or_retain_compatibility_sql():
    migrations = MIGRATION.parent
    assert not (migrations / "v2.7.1_003_workbench_history_pins.sql").exists()
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "alter table nexent.conversation_record_t" in sql
    assert "add column if not exists workbench_pinned_at" in sql
    assert "conversation_workbench_pin_t" not in sql
    assert "drop table" not in sql and "update nexent.conversation_record_t" not in sql
    for file in migrations.glob("*.sql"):
        assert "conversation_workbench_pin_t" not in file.read_text(encoding="utf-8").lower(), file.name
