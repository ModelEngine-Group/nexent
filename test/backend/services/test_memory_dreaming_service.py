from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from nexent.memory.dreaming import DreamingThresholds, select_candidates
from services.memory_dreaming_service import (
    DreamingConflictError,
    DreamingRunError,
    MemoryDreamingService,
)


@contextmanager
def lock(value):
    yield value


def test_ac007_lock_busy_skips(monkeypatch):
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.create_audit",
        lambda *_: 41,
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.try_scope_lock",
        lambda *_: lock(False),
    )
    finish = MagicMock()
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.finish_audit", finish
    )
    result = MemoryDreamingService(record_service=MagicMock()).run(
        tenant_id="t", user_id="u", agent_id="a"
    )
    assert result == {"run_id": 41, "status": "skipped", "reason": "lock_busy"}
    finish.assert_called_once()


def test_ac001_ac006_full_run_and_idempotency_key(monkeypatch):
    record = {
        "memory_id": 7,
        "tenant_id": "t",
        "user_id": "u",
        "agent_id": "a",
        "content": "Always prefer stable transaction rollback behavior",
        "recall_count": 3,
        "daily_count": 2,
        "grounded_count": 1,
        "last_recalled_at": datetime.utcnow().isoformat(),
        "query_hashes": ["q1", "q2"],
        "recall_days": ["2026-07-22", "2026-07-23"],
        "light_hits": 2,
        "rem_hits": 2,
        "last_light_at": datetime.utcnow().isoformat(),
        "last_rem_at": datetime.utcnow().isoformat(),
        "concept_tags": [],
    }
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.create_audit",
        lambda *_: 42,
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.try_scope_lock",
        lambda *_: lock(True),
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.update_audit",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.finish_audit",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_retrieval_hit_db.aggregate_dreaming_stats",
        lambda *_args, **_kwargs: [
            {
                "memory_id": 7,
                "hit_count": 4,
                "grounded_count": 1,
                "days": {"2026-07-22", "2026-07-23"},
                "query_hashes": {"q1", "q2"},
                "total_retrieval_score": 3.8,
                "last_recalled_at": datetime.utcnow(),
            }
        ],
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_record_db.list_memory_records",
        lambda *_args, **_kwargs: [record],
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_record_db.find_by_idempotency",
        lambda *_args, **_kwargs: None,
    )
    update_record = MagicMock(return_value=True)
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_record_db.update_memory_record",
        update_record,
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_record_db.apply_dreaming_phase",
        lambda *_args, **_kwargs: True,
    )
    record_service = MagicMock()
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.get_active_version",
        lambda *_args: None,
    )
    create_version = MagicMock(
        return_value={"version_id": 1, "version_no": 1, "is_active": True}
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.create_and_activate_version",
        create_version,
    )
    result = MemoryDreamingService(record_service=record_service).run(
        tenant_id="t",
        user_id="u",
        agent_id="a",
        min_score=0,
        min_recall_count=0,
        min_unique_queries=0,
    )
    assert result["status"] == "completed"
    assert result["light_count"] == 1
    assert result["promoted_count"] == 1
    light_payload = update_record.call_args_list[0].args[2]
    assert light_payload["recall_count"] == 4
    assert light_payload["daily_count"] == 2
    assert light_payload["grounded_count"] == 1
    assert light_payload["query_hashes"] == ["q1", "q2"]
    assert result["version"]["version_no"] == 1
    version_payload = create_version.call_args.kwargs
    assert version_payload["parent_version_id"] is None
    assert version_payload["published_units"][0]["evidence_ids"] == ["7"]
    assert version_payload["source_evidence_ids"] == ["7"]
    assert version_payload["config_snapshot"]["min_score"] == 0
    assert version_payload["config_snapshot"]["source_limit"] == 10


def test_ac006_already_promoted_candidate_is_not_written_again(monkeypatch):
    service = MemoryDreamingService(record_service=MagicMock())
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_record_db.list_memory_records",
        lambda *_args, **_kwargs: [
            {
                "memory_id": 9,
                "tenant_id": "t",
                "user_id": "u",
                "agent_id": "a",
                "content": "Always prefer stable transaction behavior",
                "recall_count": 10,
                "daily_count": 5,
                "grounded_count": 2,
                "last_recalled_at": datetime.utcnow().isoformat(),
                "query_hashes": ["q1", "q2", "q3"],
                "recall_days": ["2026-07-21", "2026-07-22", "2026-07-23"],
                "light_hits": 3,
                "rem_hits": 3,
                "last_light_at": datetime.utcnow().isoformat(),
                "last_rem_at": datetime.utcnow().isoformat(),
                "concept_tags": ["preference", "transaction"],
            }
        ],
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_record_db.find_by_idempotency",
        lambda *_args, **_kwargs: {"memory_id": 99},
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_record_db.update_memory_record",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_record_db.apply_dreaming_phase",
        lambda *_args, **_kwargs: True,
    )
    candidates = service._run_rem("t", "u", "a", {})
    decisions = select_candidates(
        candidates,
        thresholds=DreamingThresholds(
            min_score=0,
            min_recall_count=0,
            min_unique_queries=0,
        ),
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.get_active_version",
        lambda *_args: None,
    )
    result = service._build_version("t", "u", "a", 1, decisions)
    assert result is None
    service.record_service.create_memory.assert_not_called()


def test_ac008_failure_is_audited(monkeypatch):
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.create_audit",
        lambda *_: 43,
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.try_scope_lock",
        lambda *_: lock(True),
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_retrieval_hit_db.aggregate_dreaming_stats",
        MagicMock(side_effect=ValueError("bad data")),
    )
    finish = MagicMock()
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.finish_audit", finish
    )
    service = MemoryDreamingService(record_service=MagicMock())
    with pytest.raises(DreamingRunError):
        service.run(tenant_id="t", user_id="u", agent_id="a")
    assert finish.call_args.kwargs["status"] == "failed"
    assert "ValueError" in finish.call_args.kwargs["error"]


def test_ac022_stale_active_version_switch_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.try_scope_lock",
        lambda *_args: lock(True),
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.get_active_version",
        lambda *_args: {"version_id": 12},
    )
    activate = MagicMock()
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.activate_version",
        activate,
    )

    with pytest.raises(DreamingConflictError):
        MemoryDreamingService(record_service=MagicMock()).activate_version(
            "t",
            "u",
            agent_id="a",
            version_id=10,
            expected_active_version_id=11,
        )

    activate.assert_not_called()
