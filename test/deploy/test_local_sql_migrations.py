from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_standard_sql_migration_runner_is_the_only_local_runner() -> None:
    assert not (ROOT / "deploy/common/run_local_sql_migrations.py").exists()
    runner = (ROOT / "deploy/common/run-sql-migrations.sh").read_text(encoding="utf-8")
    assert "pg_advisory_lock" in runner
    assert "schema_migrations" in runner


def test_nl2agent_migration_rebuilds_authoritative_schema() -> None:
    migration = (
        ROOT / "deploy/sql/migrations/v2.4.0_0722_add_nl2agent.sql"
    ).read_text(encoding="utf-8")
    assert "DROP TABLE IF EXISTS nexent.nl2agent_catalog_snapshot_t" in migration
    assert "session_catalogs JSONB NOT NULL" in migration
    assert "nl2agent_installation_operation_t" in migration
    assert "conversation_record_t" in migration


def test_fresh_schema_matches_nl2agent_migration_shape() -> None:
    init_sql = (ROOT / "deploy/sql/init.sql").read_text(encoding="utf-8")
    assert '"session_catalogs" jsonb NOT NULL' in init_sql
    assert '"nl2agent_installation_operation_t"' in init_sql
    assert 'CREATE TABLE IF NOT EXISTS "nl2agent_catalog_snapshot_t"' not in init_sql
