from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from consts.const import EXTERNAL_MEMORY_DEFAULT_ALLOWED_UNIT_TYPES
from nexent.memory.models import MemoryIngestResult, MemoryIngestUnit
from services.memory_ingestion_event_service import MemoryIngestionEventService


ALLOWED_TYPE = next(iter(EXTERNAL_MEMORY_DEFAULT_ALLOWED_UNIT_TYPES))
DISALLOWED_TYPE = "not_in_global_whitelist"


def _unit(event_id, unit_type):
    return MemoryIngestUnit(
        event_id=event_id,
        event_type="message",
        unit_type=unit_type,
        unit_content="content-" + event_id,
    )


@pytest.mark.asyncio
@pytest.mark.case_id("UT-BE-AUTO-92A31CE48AF8724C")
@pytest.mark.stage("D1")
async def test_external_memory_ingestion_orchestration(monkeypatch):
    log_calls = []
    params = {"plugin.name": "fake_plugin", "plugin.api_key": "super-secret-value"}

    monkeypatch.setattr(
        "services.memory_ingestion_event_service.memory_provider_config_param_db.get_params",
        lambda provider_config_id: params,
    )
    monkeypatch.setattr(
        "services.memory_ingestion_event_service.memory_external_ingest_event_log_db.insert_event_log",
        lambda data: log_calls.append(data) or 101,
    )

    config_service = MagicMock()
    provider_service = MagicMock()
    provider_service.ingest = AsyncMock(
        return_value=MemoryIngestResult(provider="p1", status="ok", accepted_count=2)
    )

    service = MemoryIngestionEventService(config_service, provider_service)

    tenant_id = "tenant-a"
    agent_id = "agent-a"
    user_id = "user-a"
    conversation_id = "conv-a"
    event_type = "message"
    event_id = "evt-1"
    expected_key = (
        "nexent:" + tenant_id + ":" + agent_id + ":" + user_id + ":"
        + conversation_id + ":" + event_type + ":" + event_id
    )

    enabled_config = {
        "provider_config_id": 1,
        "provider_name": "p1",
        "enabled": True,
    }

    config_service.get_provider.return_value = enabled_config
    units = [
        _unit("u1", ALLOWED_TYPE),
        _unit("u2", DISALLOWED_TYPE),
        _unit("u3", ALLOWED_TYPE),
    ]

    result = await service.send_ingest(
        1, tenant_id, user_id, agent_id, conversation_id, event_type, event_id, units
    )

    assert result.status == "ok"
    assert result.accepted_count == 2
    provider_service.ingest.assert_awaited_once()
    request = provider_service.ingest.call_args.args[2]
    assert [u.event_id for u in request.units] == ["u1", "u3"]
    assert request.idempotency_key == expected_key

    assert len(log_calls) == 1
    log = log_calls[0]
    assert log["idempotency_key"] == expected_key
    assert log["event_id"] == event_id
    assert log["unit_ids"] == "u1,u3"
    assert log["response_status"] == "ok"
    assert log["response_summary"] == "status=ok"
    assert "api_key" not in str(log)
    assert "super-secret-value" not in str(log)

    assert (
        MemoryIngestionEventService._build_idempotency_key("T", "AG", "US", "CV", "ET", "EI")
        == "nexent:T:AG:US:CV:ET:EI"
    )
    assert (
        MemoryIngestionEventService._build_idempotency_key("T", "AG", "US", "CV", "ET", "EI")
        == "nexent:T:AG:US:CV:ET:EI"
    )
    filtered = MemoryIngestionEventService._filter_units(
        units, list(EXTERNAL_MEMORY_DEFAULT_ALLOWED_UNIT_TYPES)
    )
    assert [u.event_id for u in filtered] == ["u1", "u3"]

    provider_service.ingest.reset_mock()
    log_calls.clear()
    result = await service.send_ingest(
        1, tenant_id, user_id, agent_id, conversation_id, event_type, event_id,
        [_unit("u9", DISALLOWED_TYPE), _unit("u10", "another_disallowed")],
    )
    assert result.status == "ok"
    assert result.accepted_count == 0
    provider_service.ingest.assert_not_awaited()
    assert log_calls == []

    config_service.get_provider.return_value = None
    provider_service.ingest.reset_mock()
    log_calls.clear()
    result = await service.send_ingest(
        1, tenant_id, user_id, agent_id, conversation_id, event_type, event_id, units
    )
    assert result.status == "disabled"
    assert result.provider == "unknown"
    provider_service.ingest.assert_not_awaited()
    assert log_calls == []

    config_service.get_provider.return_value = {
        "provider_config_id": 1,
        "provider_name": "p1",
        "enabled": False,
    }
    provider_service.ingest.reset_mock()
    log_calls.clear()
    result = await service.send_ingest(
        1, tenant_id, user_id, agent_id, conversation_id, event_type, event_id, units
    )
    assert result.status == "disabled"
    assert result.provider == "p1"
    provider_service.ingest.assert_not_awaited()
    assert log_calls == []

    config_service.get_provider.return_value = enabled_config
    provider_service.ingest.reset_mock()
    provider_service.ingest.return_value = MemoryIngestResult(
        provider="p1", status="error", message="provider exploded"
    )
    log_calls.clear()
    result = await service.send_ingest(
        1, tenant_id, user_id, agent_id, conversation_id, event_type, event_id, units
    )
    assert result.status == "error"
    assert len(log_calls) == 1
    log = log_calls[0]
    assert log["response_status"] == "error"
    assert log["response_summary"] == "provider exploded"
    assert log["idempotency_key"] == expected_key

    provider_service.ingest.reset_mock()
    provider_service.ingest.return_value = MemoryIngestResult(
        provider="p1", status="degraded", accepted_count=1
    )
    log_calls.clear()
    result = await service.send_ingest(
        1, tenant_id, user_id, agent_id, conversation_id, event_type, event_id, units
    )
    assert result.status == "degraded"
    assert log_calls[0]["response_summary"] == "status=degraded"

    provider_service.ingest.reset_mock()
    provider_service.ingest.side_effect = RuntimeError("provider down")
    log_calls.clear()
    with pytest.raises(RuntimeError):
        await service.send_ingest(
            1, tenant_id, user_id, agent_id, conversation_id, event_type, event_id, units
        )
    assert log_calls == []
