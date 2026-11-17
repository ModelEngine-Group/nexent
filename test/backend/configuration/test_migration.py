# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Static contracts for the versioned system configuration migration."""

import re
from pathlib import Path

from test.backend.configuration.test_catalog import EXPECTED_DEFAULTS

ROOT = Path(__file__).resolve().parents[3]


def _migration() -> str:
    paths = list((ROOT / "deploy/sql/migrations").glob("*system_configuration.sql"))
    assert len(paths) == 1
    return paths[0].read_text(encoding="utf-8")


def test_sql_seed_matches_the_shared_catalog_exactly():
    sql = _migration()
    seeds = dict(re.findall(r"\('([A-Z_]+)',\s*'([^']+)'::jsonb\)", sql))
    expected = {
        key: str(value).lower() if isinstance(value, bool) else str(value)
        for key, value in EXPECTED_DEFAULTS.items()
    }

    assert seeds == expected
    assert ".env" not in sql
    assert "os.getenv" not in sql


def test_migration_defines_one_audited_scalar_table_and_safe_seed_protocol():
    sql = _migration()

    assert sql.count("CREATE TABLE IF NOT EXISTS nexent.sys_configuration_t") == 1
    assert "configuration_value JSONB NOT NULL" in sql
    assert "jsonb_typeof(configuration_value) IN ('number', 'boolean')" in sql
    for column in (
        "created_by",
        "create_time",
        "updated_by",
        "update_time",
        "delete_flag",
    ):
        assert column in sql
        assert re.search(
            rf"COMMENT ON COLUMN nexent\.sys_configuration_t\.{column} IS '[A-Z]", sql
        )
    assert "UNIQUE" not in sql.upper()
    assert "CREATE INDEX IF NOT EXISTS ix_sys_configuration_active_key" in sql
    assert "WHERE delete_flag = 'N'" in sql
    assert "pg_advisory_xact_lock(hashtext('nexent_system_configuration'))" in sql
    assert "WHERE NOT EXISTS" in sql
    assert "CREATE ROLE nexent_configuration_reader NOLOGIN" in sql
    assert (
        "GRANT SELECT ON nexent.sys_configuration_t TO nexent_configuration_reader"
        in sql
    )
    assert "GRANT USAGE ON SCHEMA nexent TO nexent_configuration_reader" in sql
    assert "role_permission_t" not in sql
    assert "'OPS_ADMIN'" not in sql
    assert "'/system-config'" not in sql


def test_model_matches_migration_shape():
    from management.configuration.models import SystemConfiguration

    table = SystemConfiguration.__table__
    assert table.name == "sys_configuration_t"
    assert table.schema == "nexent"
    assert table.c.configuration_key.comment
    assert table.c.configuration_value.comment
    for column in (
        "created_by",
        "create_time",
        "updated_by",
        "update_time",
        "delete_flag",
    ):
        assert column in table.c
    index = next(
        item for item in table.indexes if item.name == "ix_sys_configuration_active_key"
    )
    assert not index.unique
    assert [column.name for column in index.columns] == ["configuration_key"]
    assert "delete_flag = 'N'" in str(index.dialect_options["postgresql"]["where"])
