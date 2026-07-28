from contextlib import contextmanager
from datetime import datetime
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
    finish.assert_called_once()


def test_ac001_ac006_full_run_and_idempotency_key(monkeypatch):
    record = {
        "memory_id": 7,
        "tenant_id": "t",
        "user_id": "u",
        "agent_id": "a",
        "conversation_id": "conversation-7",
        "content": "Always prefer stable transaction rollback behavior",
        "create_time": "2026-07-20T09:00:00",
        "update_time": "2026-07-23T10:30:00",
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
    assert version_payload["published_units"][0]["source_agent_id"] == "a"
    assert (
        version_payload["published_units"][0]["source_conversation_id"]
        == "conversation-7"
    )
    assert (
        version_payload["published_units"][0]["source_created_at"]
        == "2026-07-20T09:00:00"
    )
    assert (
        version_payload["published_units"][0]["source_updated_at"]
        == "2026-07-23T10:30:00"
    )
    assert version_payload["source_evidence_ids"] == ["7"]
    assert version_payload["config_snapshot"]["min_score"] == 0
    assert version_payload["config_snapshot"]["source_limit"] == 10


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


def test_list_versions_delegates(monkeypatch):
    mock_list = MagicMock(return_value=[{"version_id": 2}])
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.list_versions", mock_list
    )

    service = MemoryDreamingService(record_service=MagicMock())
    result = service.list_versions("t", "u", agent_id="a", limit=50)

    assert result == [{"version_id": 2}]
    mock_list.assert_called_once_with("t", "u", agent_id="a", limit=50)


def test_activate_version_lock_busy(monkeypatch):
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.try_scope_lock",
        lambda *_args: lock(False),
    )

    service = MemoryDreamingService(record_service=MagicMock())
    with pytest.raises(DreamingConflictError, match="busy"):
        service.activate_version(
            "t", "u", agent_id="a", version_id=10
        )


def test_activate_version_success(monkeypatch):
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.try_scope_lock",
        lambda *_args: lock(True),
    )
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.get_active_version",
        lambda *_args: {"version_id": 5},
    )
    activate = MagicMock(return_value={"version_id": 10, "is_active": True})
    monkeypatch.setattr(
        "services.memory_dreaming_service.memory_dreaming_db.activate_version",
        activate,
    )

    service = MemoryDreamingService(record_service=MagicMock())
    result = service.activate_version(
        "t", "u",
        agent_id="a",
        version_id=10,
        actor_user_id="admin",
        expected_active_version_id=5,
    )

    assert result["version_id"] == 10
    activate.assert_called_once_with(
        "t", "u", "a", 10, actor_user_id="admin"
    )


def test_get_memory_dreaming_service_singleton(monkeypatch):
    import services.memory_dreaming_service as mod
    monkeypatch.setattr(mod, "_service", None)

    svc1 = mod.get_memory_dreaming_service()
    svc2 = mod.get_memory_dreaming_service()

    assert svc1 is svc2
    assert isinstance(svc1, MemoryDreamingService)

    monkeypatch.setattr(mod, "_service", None)


def test_tenant_compressor_lazy_init(monkeypatch):
    mock_compressor_cls = MagicMock()
    mock_instance = MagicMock(return_value="compressed")
    mock_compressor_cls.return_value = mock_instance

    import sys

    fake_module = MagicMock()
    fake_module.TenantDreamingCompressor = mock_compressor_cls
    monkeypatch.setitem(sys.modules, "services.memory_dreaming_compressor", fake_module)

    service = MemoryDreamingService(record_service=MagicMock())
    compress = service._tenant_compressor("t", "u")

    request = MagicMock()
    result = compress(request)

    assert result == "compressed"
    mock_compressor_cls.assert_called_once_with("t", "u")
    mock_instance.assert_called_once_with(request)

    result2 = compress(request)
    assert mock_compressor_cls.call_count == 1
