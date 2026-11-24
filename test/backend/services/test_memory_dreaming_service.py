# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from management.services.memory.dreaming.service import (
    DreamingConflictError,
    DreamingRunError,
    MemoryDreamingService,
)


@contextmanager
def lock(value):
    yield value


def test_ac007_lock_busy_skips(monkeypatch):
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_dreaming_db.create_audit",
        lambda *_: 41,
    )
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_dreaming_db.try_scope_lock",
        lambda *_: lock(False),
    )
    finish = MagicMock()
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_dreaming_db.finish_audit", finish
    )
    result = MemoryDreamingService(record_service=MagicMock()).run(
        tenant_id="t", user_id="u", agent_id="a"
    )
    assert result == {"run_id": 41, "status": "skipped", "reason": "lock_busy"}
    finish.assert_called_once_with(41, status="skipped", reason="lock_busy")


@pytest.mark.parametrize(
    "thresholds, generation_status",
    [
        ({}, "summarized"),
        ({"long_term_length_tolerance_percent": 0}, "mechanical_fallback"),
    ],
)
def test_ac001_ac006_full_run_and_idempotency_key(monkeypatch, thresholds, generation_status):
    now = datetime.utcnow()
    record = {
        "memory_id": 7,
        "tenant_id": "t",
        "user_id": "u",
        "agent_id": "a",
        "conversation_id": "conversation-7",
        "content": "Always prefer stable transaction rollback behavior",
        "create_time": (now - timedelta(days=1)).isoformat(),
        "update_time": now.isoformat(),

        "recall_count": 3,
        "daily_count": 2,
        "grounded_count": 1,
        "last_recalled_at": now.isoformat(),
        "query_hashes": ["q1", "q2"],
        "recall_days": ["2026-07-22", "2026-07-23"],
        "light_hits": 2,
        "rem_hits": 2,
        "last_light_at": now.isoformat(),
        "last_rem_at": now.isoformat(),
        "concept_tags": [],
    }
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_dreaming_db.create_audit",
        lambda *_: 42,
    )
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_dreaming_db.try_scope_lock",
        lambda *_: lock(True),
    )
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_dreaming_db.update_audit",
        lambda *_args, **_kwargs: True,
    )
    finish = MagicMock(return_value=True)
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_dreaming_db.finish_audit",
        finish,
    )
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_dreaming_db.get_thresholds",
        lambda *_args: {"long_term_max_chars": 100, **thresholds},
    )
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_retrieval_hit_db.aggregate_dreaming_stats",
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
        "management.services.memory.dreaming.service.memory_record_db.list_memory_records",
        lambda *_args, **_kwargs: [record],
    )
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_record_db.find_by_idempotency",
        lambda *_args, **_kwargs: None,
    )
    update_record = MagicMock(return_value=True)
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_record_db.update_memory_record",
        update_record,
    )
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_record_db.apply_dreaming_phase",
        lambda *_args, **_kwargs: True,
    )
    record_service = MagicMock()
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_long_term_db.get_active",
        lambda *_args: None,
    )
    create_version = MagicMock(
        return_value={"version_id": 1, "version_no": 1, "is_active": True}
    )
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_long_term_db.create_and_activate",
        create_version,
    )
    text = "## Transaction Preferences\n\n- Always prefer stable transaction rollback behavior"
    summary = text + "x" * (104 - len(text))
    result = MemoryDreamingService(
        record_service=record_service,
        summarizer=lambda _request: __import__(
            "nexent.memory.dreaming", fromlist=["DreamingSummarizationOutput"]
        ).DreamingSummarizationOutput(
            markdown=summary
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
    assert version_payload["generation_audit"]["status"] == generation_status
    finish_payload = finish.call_args.kwargs
    assert finish_payload["published_version_id"] == 1
    assert finish_payload["decisions"] == result["decisions"]
    assert "result_json" not in finish_payload


@pytest.mark.parametrize("failing_read", ["list_memory_records", "aggregate_dreaming_stats"])
def test_ac008_failure_is_audited(monkeypatch, failing_read):
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_dreaming_db.create_audit",
        lambda *_: 43,
    )
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_dreaming_db.try_scope_lock",
        lambda *_: lock(True),
    )
    storage_error = RuntimeError("database unavailable")
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_record_db.list_memory_records",
        MagicMock(return_value=[], side_effect=storage_error if failing_read == "list_memory_records" else None),
    )
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_retrieval_hit_db.aggregate_dreaming_stats",
        MagicMock(return_value=[], side_effect=storage_error if failing_read == "aggregate_dreaming_stats" else None),
    )
    finish = MagicMock()
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_dreaming_db.finish_audit", finish
    )
    service = MemoryDreamingService(record_service=MagicMock())
    publish = MagicMock()
    monkeypatch.setattr(service, "_build_version", publish)
    with pytest.raises(DreamingRunError) as exc_info:
        service.run(tenant_id="t", user_id="u", agent_id="a")
    assert exc_info.value.__cause__ is storage_error
    assert finish.call_args.kwargs["status"] == "failed"
    assert "RuntimeError" in finish.call_args.kwargs["error"]
    publish.assert_not_called()



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
        "management.services.memory.dreaming.service.memory_dreaming_db.update_audit", update
    )
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_dreaming_db.try_scope_lock",
        lambda *_: lock(False),
    )
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_dreaming_db.finish_audit",
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
        "management.services.memory.dreaming.service.memory_dreaming_db.create_audit",
        create_audit,
    )
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_dreaming_db.try_scope_lock",
        lambda *_: lock(False),
    )
    monkeypatch.setattr(
        "management.services.memory.dreaming.service.memory_dreaming_db.finish_audit",
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
        "management.services.memory.dreaming.service.memory_dreaming_db.list_audits", mock_list
    )

    service = MemoryDreamingService(record_service=MagicMock())
    result = service.list_audits("t", "u", agent_id="a", run_id=1, limit=50)

    assert result == [{"run_id": 1}]
    mock_list.assert_called_once_with("t", "u", agent_id="a", run_id=1, limit=50)





def test_get_memory_dreaming_service_singleton(monkeypatch):
    from management.services.memory.dreaming import service as mod
    monkeypatch.setattr(mod, "_service", None)

    svc1 = mod.get_memory_dreaming_service()
    svc2 = mod.get_memory_dreaming_service()

    assert svc1 is svc2
    assert isinstance(svc1, MemoryDreamingService)

    monkeypatch.setattr(mod, "_service", None)


def test_expired_window_evidence_does_not_count_toward_promotion(monkeypatch):
    from management.services.memory.dreaming import service as dreaming

    monkeypatch.setattr(dreaming.memory_record_db, "update_memory_record", MagicMock())
    monkeypatch.setattr(dreaming.memory_record_db, "apply_dreaming_phase", MagicMock())
    record = {
        "memory_id": 1, "tenant_id": "t", "user_id": "u", "agent_id": "1",
        "content": "Use this durable release policy",
        "recall_count": 30, "daily_count": 3, "grounded_count": 3,
        "query_hashes": ["old1", "old2", "old3"], "recall_days": ["2026-08-01"],
    }
    candidate, = MemoryDreamingService(record_service=MagicMock())._run_rem("t", [record], {})
    assert candidate.recall_count == 0
    assert candidate.daily_count == 0
    assert candidate.query_hashes == []
    assert candidate.last_recalled_at is None


@pytest.mark.parametrize(
    ("decision_kind", "reason"),
    [(None, "no_candidates"), (False, "no_eligible_candidates"), (True, "no_new_evidence")],
)
def test_dreaming_no_publication_reports_specific_audit_reason(monkeypatch, decision_kind, reason):
    from management.services.memory.dreaming import service as dreaming

    finish = MagicMock()
    monkeypatch.setattr(dreaming.memory_dreaming_db, "try_scope_lock", lambda *_: lock(True))
    monkeypatch.setattr(dreaming.memory_dreaming_db, "update_audit", MagicMock())
    monkeypatch.setattr(dreaming.memory_dreaming_db, "get_thresholds", lambda *_: {})
    monkeypatch.setattr(dreaming.memory_dreaming_db, "finish_audit", finish)
    service = MemoryDreamingService(record_service=MagicMock())
    candidate = SimpleNamespace(memory_id=1, noise=0)
    decision = SimpleNamespace(
        candidate=candidate, promote=decision_kind, score=1.0, reason="test",
        metrics=SimpleNamespace(signal_count=1, context_diversity=1), archive_suggested=False,
    )
    release = MagicMock(return_value=None)
    monkeypatch.setattr(service, "_source_records", lambda *_: [])
    monkeypatch.setattr(service, "_run_light", lambda *_: {})
    monkeypatch.setattr(service, "_run_rem", lambda *_: [] if decision_kind is None else [candidate])
    monkeypatch.setattr(service, "_build_version", release)
    monkeypatch.setattr(dreaming, "select_candidates", lambda *_args, **_kwargs: [] if decision_kind is None else [decision])

    result = service.run(tenant_id="t", user_id="u", agent_id="__user__", run_id=5)
    assert result["status"] == "completed"
    assert result["reason"] == reason
    assert result["version"] is None
    assert finish.call_args.kwargs["reason"] == reason
    assert finish.call_args.kwargs["published_version_id"] is None
    assert release.called is (decision_kind is True)
