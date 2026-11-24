# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Static contracts for the versioned system configuration migration."""

import re
from pathlib import Path

from test.backend.configuration.test_catalog import EXPECTED_DEFAULTS

ROOT = Path(__file__).resolve().parents[3]


def _migration() -> str:
    path = ROOT / "deploy/sql/migrations/v2.9.0_009_system_configuration.sql"
    assert path.is_file()
    return path.read_text(encoding="utf-8")


def _su_migration() -> str:
    path = ROOT / "deploy/sql/migrations/v2.9.0_014_su_system_configuration.sql"
    assert path.is_file()
    return path.read_text(encoding="utf-8")


def test_sql_seed_matches_the_shared_catalog_exactly():
    sql = _migration()
    seeds = dict(re.findall(r"\('([A-Z_]+)',\s*'([^']+)'::jsonb\)", sql))
    expected = {
        key: str(value).lower() if isinstance(value, bool) else str(value)
        for key, value in {**EXPECTED_DEFAULTS, "MAX_SUPER_ADMIN_COUNT": 1}.items()
    }

    assert seeds == {key: value for key, value in expected.items() if key != "NL2AGENT_RESOURCE_DENYLIST"}
    assert ".env" not in sql
    assert "os.getenv" not in sql


def test_denylist_migration_preserves_existing_values_and_adds_an_array_default():
    sql = (ROOT / "deploy/sql/migrations/v2.9.0_014_nl2agent_resource_denylist.sql").read_text(encoding="utf-8")
    assert "SELECT 'NL2AGENT_RESOURCE_DENYLIST', '[]'::jsonb" in sql
    assert "WHERE NOT EXISTS" in sql
    assert "pg_advisory_xact_lock(hashtext('nexent_system_configuration'))" in sql
    assert "THEN jsonb_typeof(configuration_value) = 'array'" in sql


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


def test_su_migration_retires_key_and_revokes_only_ops_configuration_grants():
    sql = _su_migration()

    assert "configuration_key = 'MAX_SUPER_ADMIN_COUNT'" in sql
    assert "delete_flag = 'Y'" in sql
    assert "user_role = 'OPS'" in sql
    assert "permission_type = 'OPS.CONFIGURATION'" in sql
    assert "permission_subtype = '/ops/configuration'" in sql
    assert "user_role = 'SU'" not in sql


def test_model_matches_migration_shape():
    from infrastructure.system_configuration.models import SystemConfiguration

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
