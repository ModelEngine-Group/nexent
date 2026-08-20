from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

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
    finish.assert_called_once_with(41, status="skipped", reason="lock_busy")


def test_ac001_ac006_full_run_and_idempotency_key(monkeypatch):
    reference_now = datetime(2026, 7, 24, 12, 0, 0)
    monkeypatch.setattr(
        "services.memory_dreaming_service._utcnow", lambda: reference_now
    )
    record = {
        "memory_id": 7,
        "tenant_id": "t",
        "user_id": "u",
        "agent_id": "a",
        "conversation_id": "conversation-7",
        "content": "Always prefer stable transaction rollback behavior",
        "create_time": (reference_now - timedelta(days=4)).isoformat(),
        "update_time": (reference_now - timedelta(days=1)).isoformat(),
        "recall_count": 3,
        "daily_count": 2,
        "grounded_count": 1,
        "last_recalled_at": reference_now.isoformat(),
        "query_hashes": ["q1", "q2"],
        "recall_days": ["2026-07-22", "2026-07-23"],
        "light_hits": 2,
        "rem_hits": 2,
        "last_light_at": reference_now.isoformat(),
        "last_rem_at": reference_now.isoformat(),
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
    finish = MagicMock(return_value=True)
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.finish_audit",
        finish,
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.get_thresholds",
        lambda *_args: {},
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
                "last_recalled_at": reference_now,
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
        "services.memory_dreaming_service.memory_long_term_db.get_active",
        lambda *_args: None,
    )
    create_version = MagicMock(
        return_value={"version_id": 1, "version_no": 1, "is_active": True}
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_long_term_db.create_and_activate",
        create_version,
    )
    result = MemoryDreamingService(
        record_service=record_service,
        summarizer=lambda _request: __import__(
            "nexent.memory.dreaming", fromlist=["DreamingSummarizationOutput"]
        ).DreamingSummarizationOutput(
            markdown="## Transaction Preferences\n\n- Always prefer stable transaction rollback behavior"
        ),
    ).run(
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
    assert version_payload["expected_active_version_id"] is None
    assert version_payload["evidence_ids"] == ["7"]
    assert version_payload["source"] == "dreaming"
    assert version_payload["generation_audit"]["status"] == "summarized"
    finish_payload = finish.call_args.kwargs
    assert finish_payload["published_version_id"] == 1
    assert finish_payload["decisions"] == result["decisions"]
    assert "result_json" not in finish_payload


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



def test_run_rejects_empty_ids():
    service = MemoryDreamingService(record_service=MagicMock())
    with pytest.raises(DreamingRunError, match="required"):
        service.run(tenant_id="", user_id="u", agent_id="a")
    with pytest.raises(DreamingRunError, match="required"):
        service.run(tenant_id="t", user_id="", agent_id="a")
    with pytest.raises(DreamingRunError, match="required"):
        service.run(tenant_id="t", user_id="u", agent_id="")


def test_run_with_preexisting_run_id(monkeypatch):
    update = MagicMock(return_value=True)
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.update_audit", update
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.try_scope_lock",
        lambda *_: lock(False),
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.finish_audit",
        lambda *_args, **_kwargs: True,
    )

    service = MemoryDreamingService(record_service=MagicMock())
    result = service.run(
        tenant_id="t", user_id="u", agent_id="a", run_id=100
    )

    assert result["status"] == "skipped"
    update.assert_called_once_with(
        100, {"status": "running", "current_phase": "light"}
    )


def test_run_non_manual_trigger_creates_audit(monkeypatch):
    create_audit = MagicMock(return_value=55)
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.create_audit",
        create_audit,
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.try_scope_lock",
        lambda *_: lock(False),
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.finish_audit",
        lambda *_args, **_kwargs: True,
    )

    service = MemoryDreamingService(record_service=MagicMock())
    service.run(
        tenant_id="t", user_id="u", agent_id="a", trigger_source="scheduler"
    )

    create_audit.assert_called_once_with(
        "t", "u", "a", trigger_source="scheduler"
    )


def test_list_audits_delegates(monkeypatch):
    mock_list = MagicMock(return_value=[{"run_id": 1}])
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.list_audits", mock_list
    )

    service = MemoryDreamingService(record_service=MagicMock())
    result = service.list_audits("t", "u", agent_id="a", run_id=1, limit=50)

    assert result == [{"run_id": 1}]
    mock_list.assert_called_once_with("t", "u", agent_id="a", run_id=1, limit=50)





def test_get_memory_dreaming_service_singleton(monkeypatch):
    import services.memory_dreaming_service as mod
    monkeypatch.setattr(mod, "_service", None)

    svc1 = mod.get_memory_dreaming_service()
    svc2 = mod.get_memory_dreaming_service()

    assert svc1 is svc2
    assert isinstance(svc1, MemoryDreamingService)

    monkeypatch.setattr(mod, "_service", None)
