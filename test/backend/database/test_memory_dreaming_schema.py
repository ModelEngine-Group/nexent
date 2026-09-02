import re
from pathlib import Path

from database.db_models import (
    MemoryDreamingAudit,
    MemoryDreamingDecision,
    MemoryDreamingSchedule,
    MemoryLongTermVersion,
    TableBase,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB


DREAMING_SOURCE_MARKER = (
    "-- Source migration: v2.5.0_0813_versioned_markdown_long_term_memory.sql"
)


def _read_dreaming_migration(root: Path) -> str:
    merged = (root / "deploy/sql/migrations/v2.5.0_merged_migrations.sql").read_text()
    assert DREAMING_SOURCE_MARKER in merged
    dreaming_and_later = merged.split(DREAMING_SOURCE_MARKER, maxsplit=1)[1]
    next_source_marker = "\n-- Source migration:"
    assert next_source_marker in dreaming_and_later
    return dreaming_and_later.split(next_source_marker, maxsplit=1)[0]


def test_final_orm_contract_has_only_shared_long_term_versions():
    assert MemoryDreamingAudit.__tablename__ == "memory_dreaming_audit_t"
    assert MemoryDreamingDecision.__tablename__ == "memory_dreaming_decision_t"
    assert MemoryDreamingSchedule.__tablename__ == "memory_dreaming_schedule_t"
    assert MemoryLongTermVersion.__tablename__ == "memory_long_term_version_t"
    assert "nexent.memory_long_term_activation_audit_t" not in TableBase.metadata.tables
    audit_columns = MemoryDreamingAudit.__table__.columns
    assert "result_json" not in audit_columns
    assert "decisions" not in audit_columns
    assert {"published_version_id", "reason"} <= set(audit_columns.keys())
    assert {
        "run_id", "decision_order", "memory_id", "score", "noise",
        "signal_count", "context_diversity", "evidence_ids", "event",
        "reason", "archive_suggested",
    } <= set(MemoryDreamingDecision.__table__.columns.keys())
    evidence_ids = MemoryDreamingDecision.__table__.columns["evidence_ids"]
    assert isinstance(evidence_ids.type, ARRAY)
    assert evidence_ids.type.item_type.length == 100
    long_term_evidence_ids = MemoryLongTermVersion.__table__.columns["evidence_ids"]
    assert isinstance(long_term_evidence_ids.type, JSONB)


def test_final_migration_is_the_only_dreaming_schema_source():
    root = Path(__file__).resolve().parents[3]
    migrations = root / "deploy/sql/migrations"
    final = _read_dreaming_migration(root)
    init_sql = (root / "deploy/sql/init.sql").read_text()
    for token in (
        "memory_dreaming_audit_t", "memory_dreaming_decision_t", "memory_dreaming_schedule_t",
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
    assert "result_json" not in final
    assert "compression_max_attempts" not in final
    assert "CREATE TABLE IF NOT EXISTS nexent.memory_dreaming_decision_t" in final
    assert "ON DELETE CASCADE" in final
    assert "published_version_id BIGINT" in final
    assert "reason VARCHAR(100)" in final

    created_tables = re.findall(
        r"CREATE TABLE IF NOT EXISTS nexent\.(\w+)", final, flags=re.IGNORECASE
    )
    assert created_tables
    for table_name in created_tables:
        assert not re.search(
            rf"ALTER TABLE\s+(?:ONLY\s+)?nexent\.{re.escape(table_name)}\b",
            final,
            flags=re.IGNORECASE,
        )


def test_final_migration_upgrades_v24_without_intermediate_v25_schema():
    root = Path(__file__).resolve().parents[3]
    migrations = root / "deploy/sql/migrations"
    v24 = (migrations / "v2.4_merged_migrations.sql").read_text()
    final = _read_dreaming_migration(root)

    assert "CREATE TABLE IF NOT EXISTS nexent.memory_records_t" in v24
    for table_name in (
        "memory_dreaming_audit_t",
        "memory_dreaming_decision_t",
        "memory_dreaming_schedule_t",
        "memory_long_term_version_t",
    ):
        assert f"nexent.{table_name}" not in v24

    assert "DELETE FROM nexent.memory_records_t WHERE layer IN ('tenant', 'user')" in final
    assert "ALTER TABLE nexent.memory_records_t" in final
    assert "result_json" not in final
    assert "compression_max_attempts" not in final
