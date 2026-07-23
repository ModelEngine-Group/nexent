from pathlib import Path
from datetime import datetime

from database import memory_retrieval_hit_db
from database.db_models import MemoryDreamingAudit, MemoryRecord, MemoryRetrievalHit
from database.memory_dreaming_db import advisory_lock_key


def test_ac010_orm_contract():
    assert MemoryRecord.__tablename__ == "memory_records_t"
    assert MemoryRetrievalHit.__tablename__ == "memory_retrieval_hits_t"
    columns = MemoryDreamingAudit.__table__.columns
    for name in (
        "run_id",
        "tenant_id",
        "user_id",
        "agent_id",
        "status",
        "current_phase",
        "result_json",
        "error",
    ):
        assert name in columns


def test_ac007_lock_key_is_stable_and_scope_specific():
    key = advisory_lock_key("tenant", "user", "agent")
    assert key == advisory_lock_key("tenant", "user", "agent")
    assert key != advisory_lock_key("tenant", "user", "other-agent")
    assert -(2**63) <= key < 2**63


def test_ac010_migration_and_fresh_install_match():
    root = Path(__file__).resolve().parents[3]
    migration = (
        root / "deploy/sql/migrations/v2.4.0_0723_add_memory_dreaming_audit.sql"
    ).read_text()
    init_sql = (root / "deploy/sql/init.sql").read_text()
    for token in (
        "memory_dreaming_audit_t",
        "idx_memory_dreaming_audit_scope",
        "result_json",
        "promoted_count",
    ):
        assert token in migration
        assert token in init_sql
    assert "CREATE TABLE IF NOT EXISTS" in migration
    assert "CREATE INDEX IF NOT EXISTS" in migration


def test_ac002_dreaming_stats_filter_agent_scope(monkeypatch):
    monkeypatch.setattr(
        memory_retrieval_hit_db,
        "list_hits_for_user",
        lambda *_args, **_kwargs: [
            {
                "agent_id": "agent-1",
                "memory_id": 1,
                "day": "2026-07-22",
                "query_hash": "q1",
                "retrieval_score": 0.75,
                "grounded": True,
                "occurred_at": datetime(2026, 7, 22, 12),
            },
            {
                "agent_id": "agent-2",
                "memory_id": 2,
                "day": "2026-07-22",
                "query_hash": "q2",
                "retrieval_score": 1.0,
                "grounded": True,
                "occurred_at": datetime(2026, 7, 22, 13),
            },
        ],
    )
    rows = memory_retrieval_hit_db.aggregate_dreaming_stats(
        "tenant",
        "user",
        "agent-1",
        since=datetime(2026, 7, 20),
    )
    assert len(rows) == 1
    assert rows[0]["memory_id"] == 1
    assert rows[0]["total_retrieval_score"] == 0.75
