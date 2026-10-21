# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""ORM schema contract; actual PostgreSQL migration execution is a separate D5 proof."""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateColumn, SetColumnComment


@pytest.fixture(scope="module")
def table():
    # This metadata module has no database clients or configuration side effects.
    path = Path(__file__).resolve().parents[3] / "backend/database/db_models.py"
    spec = importlib.util.spec_from_file_location("outlet_schema_metadata", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ModelRecord.__table__


@pytest.mark.parametrize(
    "name,sql_type",
    [
        ("reasoning_supported", "BOOLEAN"),
        ("reasoning_controls", "JSONB"),
        ("native_tool_call_supported", "BOOLEAN"),
        ("structured_output_supported", "BOOLEAN"),
        ("temperature_supported", "BOOLEAN"),
        ("top_p_supported", "BOOLEAN"),
        ("input_modalities", "JSONB"),
        ("output_modalities", "JSONB"),
        ("enable_thinking", "BOOLEAN"),
        ("reasoning_effort", "VARCHAR(30)"),
        ("reasoning_budget_tokens", "INTEGER"),
        ("protocol_id", "VARCHAR(30)"),
        ("resolved_profile", "JSONB"),
        ("profile_schema_version", "INTEGER"),
    ],
)
def test_new_fields_have_reviewed_types_and_no_inferred_default(table, name, sql_type):
    column = table.c[name]
    assert str(column.type.compile(dialect=postgresql.dialect())) == sql_type
    assert column.nullable is True
    assert column.default is None
    assert column.server_default is None
    assert column.comment and column.comment.isascii()
    assert column.comment in str(
        SetColumnComment(column).compile(dialect=postgresql.dialect())
    )


def test_revision_has_database_default_for_old_and_new_rows(table):
    column = table.c.config_revision
    assert column.nullable is False
    assert column.default.arg == 1
    assert str(column.server_default.arg) == "1"
    assert "DEFAULT 1 NOT NULL" in str(
        CreateColumn(column).compile(dialect=postgresql.dialect())
    )
    assert column.comment in str(
        SetColumnComment(column).compile(dialect=postgresql.dialect())
    )


def test_existing_value_columns_remain_single_storage_locations(table):
    expected = {
        "temperature": "FLOAT",
        "top_p": "FLOAT",
        "extra_params": "JSONB",
        "api_key": "VARCHAR(500)",
    }
    for name, sql_type in expected.items():
        assert str(table.c[name].type.compile(dialect=postgresql.dialect())) == sql_type
    assert not table.c.reasoning_controls.index
    assert not table.c.native_tool_call_supported.index
