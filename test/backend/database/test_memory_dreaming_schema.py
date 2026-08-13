from pathlib import Path

from database.db_models import (
    MemoryDreamingAudit,
    MemoryDreamingSchedule,
    MemoryLongTermVersion,
    TableBase,
)


def test_final_orm_contract_has_only_shared_long_term_versions():
    assert MemoryDreamingAudit.__tablename__ == "memory_dreaming_audit_t"
    assert MemoryDreamingSchedule.__tablename__ == "memory_dreaming_schedule_t"
    assert MemoryLongTermVersion.__tablename__ == "memory_long_term_version_t"
    assert "nexent.memory_long_term_activation_audit_t" not in TableBase.metadata.tables
    audit_columns = MemoryDreamingAudit.__table__.columns
    assert "result_json" not in audit_columns
    assert {"decisions", "published_version_id", "reason"} <= set(audit_columns.keys())


def test_final_migration_is_the_only_dreaming_schema_source():
    root = Path(__file__).resolve().parents[3]
    migrations = root / "deploy/sql/migrations"
    final = (migrations / "v2.5.0_0813_versioned_markdown_long_term_memory.sql").read_text()
    init_sql = (root / "deploy/sql/init.sql").read_text()
    for token in (
        "memory_dreaming_audit_t", "memory_dreaming_schedule_t",
        "memory_long_term_version_t",
        "lock_owner", "summarization_max_attempts",
    ):
        assert token in final
        assert token not in init_sql
    assert "CREATE TABLE IF NOT EXISTS nexent.memory_long_term_activation_audit_t" not in final
    assert "DROP TABLE IF EXISTS nexent.memory_long_term_activation_audit_t" in final
    assert not list(migrations.glob("v2.4.0_*dreaming*.sql"))
    assert not list(migrations.glob("v2.5.0_072*_*dreaming*.sql"))
    assert "current_phase = 'compression'" not in final
    assert "DROP COLUMN result_json" in final
    assert "decisions JSONB" in final
    assert "published_version_id BIGINT" in final
    assert "reason VARCHAR(100)" in final
