from pathlib import Path
from datetime import datetime

from database import memory_retrieval_hit_db
from database.db_models import (
    MemoryDreamingActivationAudit,
    MemoryDreamingAudit,
    MemoryDreamingVersion,
    MemoryRecord,
    MemoryRetrievalHit,
)
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


def test_ac023_ac026_version_orm_contract():
    columns = MemoryDreamingVersion.__table__.columns
    for name in (
        "version_id",
        "version_no",
        "parent_version_id",
        "run_id",
        "is_active",
        "raw_content",
        "published_content",
        "published_units",
        "source_evidence_ids",
        "config_snapshot",
        "compression_status",
        "compression_audit",
        "omitted_evidence_ids",
    ):
        assert name in columns
    activation_columns = MemoryDreamingActivationAudit.__table__.columns
    for name in (
        "activation_id",
        "actor_user_id",
        "from_version_id",
        "to_version_id",
        "reason",
    ):
        assert name in activation_columns


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

    version_migration = (
        root / "deploy/sql/migrations/v2.4.0_0723_add_memory_dreaming_version.sql"
    ).read_text()
    for token in (
        "memory_dreaming_version_t",
        "parent_version_id",
        "raw_content",
        "published_units",
        "source_evidence_ids",
        "config_snapshot",
        "compression_audit",
        "uq_memory_dreaming_version_active_scope",
        "memory_dreaming_activation_audit_t",
        "DREAMING",
        "VIEW_TENANT",
        "EDIT_TENANT",
        "prevent_memory_dreaming_version_content_update",
        "trg_memory_dreaming_version_immutable",
    ):
        assert token in version_migration
        assert token in init_sql


def test_ac012_dreaming_scheduler_is_wired_for_deployment():
    root = Path(__file__).resolve().parents[3]
    scheduler_module = (root / "backend/services/memory_dreaming_scheduler.py").read_text()
    config_app = (root / "backend/apps/config_app.py").read_text()
    dreaming_app = (root / "backend/apps/memory_dreaming_app.py").read_text()
    const_py = (root / "backend/consts/const.py").read_text()

    assert "DreamingLeaseStore" in scheduler_module
    assert "DreamingScheduler" in scheduler_module
    assert "dreaming_scheduler" in scheduler_module
    assert "start_dreaming_scheduler" in config_app
    assert "stop_dreaming_scheduler" in config_app
    assert "_enqueue_dreaming" not in dreaming_app
    assert "data_process" not in dreaming_app
    assert "DREAMING_SCHEDULER_POLL_SECONDS" in const_py
    assert "DREAMING_SCHEDULER_ENABLED" in const_py
    assert "dreaming_q" not in const_py.split("QUEUES")[1].split("\n")[0]


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
