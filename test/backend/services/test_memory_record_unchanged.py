# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from management.services.memory import records
from nexent.memory.embedding_model import EmbeddingModelInfo


def test_create_memory_exact_idempotency_match_is_unchanged(monkeypatch):
    fake_db = MagicMock()
    fake_db.find_by_idempotency.return_value = {
        "memory_id": 7,
        "content": "existing preference",
    }
    monkeypatch.setattr(records, "memory_record_db", fake_db)
    monkeypatch.setattr(
        records,
        "_resolve_tenant_embedding_model_info",
        lambda _tenant_id: None,
    )

    service = records.MemoryRecordService()
    service.index_service = MagicMock()

    fake_embedding_model_info = MagicMock()
    fake_embedding_model_info.get_index_name = MagicMock(
        return_value="test_index"
    )

    result = service.create_memory(
        tenant_id="t1",
        user_id="u1",
        content="existing preference",
        layer="agent",
        memory_type="short_term",
        agent_id="a1",
        idempotency_key="same-key",
        embedding_model_info=fake_embedding_model_info,
    )

    assert result["event"] == "UNCHANGED"
    assert result["memory_id"] == 7
    fake_db.upsert_memory_record_by_idempotency.assert_not_called()
    service.index_service.index_record.assert_not_called()


from management.services.memory import access

@pytest.mark.parametrize(
    "tenant_value, user_settings, agent_setting, expected",
    [
        (None, {"MEMORY_SWITCH": "Y"}, None, True),
        ("N", {"MEMORY_SWITCH": "Y"}, True, False),
        ("Y", {"MEMORY_SWITCH": "N"}, True, False),
        ("Y", {"MEMORY_SWITCH": "Y", "DISABLE_AGENT_ID": ["12"]}, True, False),
        ("Y", {"MEMORY_SWITCH": "Y", "DISABLE_USERAGENT_ID": ["12"]}, True, False),
        ("Y", {"MEMORY_SWITCH": "Y"}, False, False),
    ],
)
def test_automatic_write_enforces_persisted_policy(monkeypatch, tenant_value, user_settings, agent_setting, expected):
    from_db = {"config_value": tenant_value} if tenant_value is not None else {}
    monkeypatch.setattr(access, "get_single_config_info", lambda *_: from_db)
    monkeypatch.setattr(access, "get_user_configs", lambda *_: user_settings)
    lookup = Mock(return_value={"enable_memory": agent_setting})
    monkeypatch.setattr(access, "search_agent_info_by_agent_id", lookup)
    assert access.can_write_automatic_memory("t", "u", "12", 3) is expected
    if lookup.called:
        lookup.assert_called_once_with(12, "t", 3)


def test_source_agent_policy_uses_released_version_and_denies_missing_agent(monkeypatch):
    query_version = Mock(return_value=7)
    lookup = Mock(side_effect=[{"enable_memory": False}, access.AgentNotFoundError("missing")])
    monkeypatch.setattr(access, "query_current_version_no", query_version)
    monkeypatch.setattr(access, "search_agent_info_by_agent_id", lookup)
    assert access.source_agent_allows_memory("tenant", "1") is False
    lookup.assert_called_once_with(1, "tenant", 7)
    assert access.source_agent_allows_memory("tenant", 2, 99) is False
    assert access.source_agent_allows_memory("tenant", "unknown") is False
    query_version.assert_called_once_with(1, "tenant")
