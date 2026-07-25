from unittest.mock import MagicMock

from backend.services import memory_record_service


def test_create_memory_exact_idempotency_match_is_unchanged(monkeypatch):
    fake_db = MagicMock()
    fake_db.find_by_idempotency.return_value = {
        "memory_id": 7,
        "content": "existing preference",
    }
    monkeypatch.setattr(memory_record_service, "memory_record_db", fake_db)
    monkeypatch.setattr(
        memory_record_service,
        "_resolve_tenant_embedding_model_info",
        lambda _tenant_id: None,
    )

    service = memory_record_service.MemoryRecordService()
    service.index_service = MagicMock()

    result = service.create_memory(
        tenant_id="t1",
        user_id="u1",
        content="existing preference",
        layer="agent",
        memory_type="short_term",
        agent_id="a1",
        idempotency_key="same-key",
    )

    assert result["event"] == "UNCHANGED"
    assert result["memory_id"] == 7
    fake_db.upsert_memory_record_by_idempotency.assert_not_called()
    service.index_service.index_record.assert_not_called()
