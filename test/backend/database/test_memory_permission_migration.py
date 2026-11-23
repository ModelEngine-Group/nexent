from pathlib import Path


def test_memory_permission_migration_renames_and_restricts_create():
    migration = (
        Path(__file__).resolve().parents[3]
        / "deploy"
        / "sql"
        / "migrations"
        / "v2.4_merged_migrations.sql"
    ).read_text(encoding="utf-8")

    assert "SET permission_type = 'MEM.TENANT'" in migration
    assert "WHERE permission_type = 'MEM.AGENT'" in migration
