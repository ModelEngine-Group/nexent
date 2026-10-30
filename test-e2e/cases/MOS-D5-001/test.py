# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Actual PostgreSQL upgrade, idempotence and transactional recovery."""

import json
from contextlib import closing
from pathlib import Path

import psycopg2
import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from management.db.models import ConversationRecord, ModelRecord
from shared.factories.scratch_database import isolated_schema_database
from shared.postgres import postgres_connect_kwargs, postgres_scalar, postgres_sql

pytestmark = [pytest.mark.case_id("MOS-D5-001"), pytest.mark.stage("D5")]
ROOT = Path(__file__).resolve().parents[3]
COLUMNS = {
    "reasoning_supported": "boolean",
    "reasoning_controls": "jsonb",
    "native_tool_call_supported": "boolean",
    "structured_output_supported": "boolean",
    "temperature_supported": "boolean",
    "top_p_supported": "boolean",
    "input_modalities": "jsonb",
    "output_modalities": "jsonb",
    "enable_thinking": "boolean",
    "reasoning_effort": "character varying",
    "reasoning_budget_tokens": "integer",
    "protocol_id": "character varying",
    "resolved_profile": "jsonb",
    "profile_schema_version": "integer",
    "config_revision": "integer",
}


def migration_sql():
    # D5 deliberately locks the deployment artifact, rather than a business API.
    candidates = list((ROOT / "deploy/sql/migrations").glob("*_model_outlet_profile_columns.sql"))
    assert len(candidates) == 1
    return candidates[0].read_text(encoding="utf-8")


def prepare_previous_table():
    postgres_sql("TRUNCATE nexent.model_record_t CASCADE;")
    postgres_sql("ALTER TABLE nexent.model_record_t " + ", ".join(
        f'DROP COLUMN IF EXISTS "{name}"' for name in COLUMNS
    ) + ";")
    postgres_sql("""
        INSERT INTO nexent.model_record_t
        (model_name, model_factory, base_url, context_window_tokens,
         max_input_tokens, max_output_tokens, ssl_verify, temperature, top_p,
         extra_params, tenant_id, delete_flag)
        VALUES ('Exact/OLD', 'custom-provider', 'https://fixture.invalid/v1',
                200000, 180000, 20000, false, 0, 0,
                '{"enable_thinking":false,"vendor_limit":0}'::jsonb,
                'schema-test', 'N');
    """)
    return json.loads(postgres_scalar(
        "SELECT row_to_json(t) FROM nexent.model_record_t t;"
    ))


def metadata():
    return json.loads(postgres_scalar("""
        SELECT json_agg(json_build_object(
          'name', a.attname, 'type', format_type(a.atttypid, a.atttypmod),
          'not_null', a.attnotnull,
          'default', pg_get_expr(d.adbin, d.adrelid),
          'comment', col_description(a.attrelid, a.attnum)) ORDER BY a.attname)
        FROM pg_attribute a LEFT JOIN pg_attrdef d
          ON d.adrelid=a.attrelid AND d.adnum=a.attnum
        WHERE a.attrelid='nexent.model_record_t'::regclass
          AND a.attnum>0 AND NOT a.attisdropped;
    """))


def test_upgrade_preserves_values_and_repeats():
    with isolated_schema_database():
        before = prepare_previous_table()
        postgres_sql("BEGIN;\n" + migration_sql() + "\nCOMMIT;")
        after = json.loads(postgres_scalar("SELECT row_to_json(t) FROM nexent.model_record_t t;"))
        assert {key: after[key] for key in before} == before
        assert after["config_revision"] == 1
        assert all(after[key] is None for key in COLUMNS if key != "config_revision")
        initial_metadata = metadata()
        fields = {field["name"]: field for field in initial_metadata}
        for name, expected_type in COLUMNS.items():
            field = fields[name]
            expected = "character varying(30)" if expected_type == "character varying" else expected_type
            assert field["type"] == expected
            assert field["not_null"] is (name == "config_revision")
            assert field["default"] == ("1" if name == "config_revision" else None)
            assert field["comment"] and field["comment"].isascii()
        postgres_sql("BEGIN;\n" + migration_sql() + "\nCOMMIT;")
        assert metadata() == initial_metadata
        assert json.loads(postgres_scalar("SELECT row_to_json(t) FROM nexent.model_record_t t;")) == after


def test_failed_upgrade_rolls_back_and_recovers():
    with isolated_schema_database():
        before = prepare_previous_table()
        connection = psycopg2.connect(**postgres_connect_kwargs())
        try:
            with pytest.raises(psycopg2.errors.DivisionByZero), connection, connection.cursor() as cursor:
                cursor.execute(migration_sql())
                cursor.execute("SELECT 1 / 0;")
        finally:
            connection.close()
        assert not set(COLUMNS).intersection(field["name"] for field in metadata())
        assert json.loads(postgres_scalar("SELECT row_to_json(t) FROM nexent.model_record_t t;")) == before
        postgres_sql("BEGIN;\n" + migration_sql() + "\nCOMMIT;")
        assert set(COLUMNS).issubset(field["name"] for field in metadata())
        restored = json.loads(postgres_scalar("SELECT row_to_json(t) FROM nexent.model_record_t t;"))
        assert {key: restored[key] for key in before} == before
        assert restored["config_revision"] == 1


@pytest.mark.parametrize("table_name", ["model_record_t", "conversation_record_t"])
def test_first_pr_schema_covers_orm_columns_without_later_migrations(table_name):
    """AC-04: execute first-layer SQL against prior schema before real ORM queries."""
    with isolated_schema_database():
        prepare_previous_table()
        postgres_sql("ALTER TABLE nexent.model_record_t "
                     "DROP COLUMN IF EXISTS http_headers, "
                     "DROP COLUMN IF EXISTS default_max_output_tokens;")
        postgres_sql("ALTER TABLE nexent.conversation_record_t "
                     "DROP COLUMN IF EXISTS selected_model_id, "
                     "DROP COLUMN IF EXISTS model_parameter_preferences, "
                     "DROP COLUMN IF EXISTS model_parameter_preferences_version;")
        migrations = ROOT / "deploy/sql/migrations"
        suffixes = ["model_outlet_profile_columns", "model_output_default",
                    "conversation_model_preferences", "model_http_headers"]
        paths = []
        for suffix in suffixes:
            matches = list(migrations.glob("*_" + suffix + ".sql"))
            assert len(matches) <= 1
            paths.extend(matches)
        sql = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        postgres_sql(sql)
        model = ModelRecord if table_name == "model_record_t" else ConversationRecord
        statement = select(model).limit(0).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
        # A real server must accept every selected column, even with no data rows.
        with closing(psycopg2.connect(**postgres_connect_kwargs())) as connection:
            with connection, connection.cursor() as cursor:
                cursor.execute(str(statement))
        assert len(paths) == len(suffixes)
        row = json.loads(postgres_scalar("SELECT row_to_json(t) FROM nexent.model_record_t t;"))
        assert row["http_headers"] == {}
        assert row["temperature"] == 0 and row["top_p"] == 0
        columns = json.loads(postgres_scalar("""
            SELECT json_object_agg(column_name, json_build_object(
              'type', data_type, 'nullable', is_nullable, 'default', column_default))
            FROM information_schema.columns WHERE table_schema='nexent'
              AND table_name='conversation_record_t';
        """))
        assert columns["selected_model_id"] == {"type": "integer", "nullable": "YES", "default": None}
        assert columns["model_parameter_preferences"]["default"] == "'{}'::jsonb"
        assert columns["model_parameter_preferences_version"]["default"] == "0"
        postgres_sql(sql)
        assert json.loads(postgres_scalar("SELECT row_to_json(t) FROM nexent.model_record_t t;")) == row
