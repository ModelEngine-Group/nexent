from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "deploy/sql/migrations/v2.3.0_0721_agent_runtime_framework.sql"
INIT_SQL = ROOT / "deploy/sql/init.sql"


def test_runtime_framework_migration_backfills_and_enforces_immutability():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS runtime_framework VARCHAR(20)" in sql
    assert "SET runtime_framework = 'smolagents'" in sql
    assert "runtime_framework IN ('smolagents', 'openjiuwen')" in sql
    assert "OLD.runtime_framework IS NOT NULL" in sql
    assert "NEW.runtime_framework IS DISTINCT FROM OLD.runtime_framework" in sql
    assert "AGENT_RUNTIME_FRAMEWORK_IMMUTABLE" in sql


def test_runtime_framework_schema_change_is_migration_only():
    init_sql = INIT_SQL.read_text(encoding="utf-8")

    assert "runtime_framework VARCHAR(20)" not in init_sql
    assert "enforce_agent_runtime_framework_immutable_trigger" not in init_sql
