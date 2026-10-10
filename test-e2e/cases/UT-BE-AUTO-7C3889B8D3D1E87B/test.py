import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexent.memory.models import MemoryIngestResult, MemoryIngestUnit
from services.memory_backend_adapter import (
    _backend_store_hook,
    _fanout_external_ingest,
)
from services.memory_ingestion_event_service import MemoryIngestionEventService


CASE_ID = 'UT-BE-AUTO-7C3889B8D3D1E87B'


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D1')
def test_ut_be_auto_7c3889b8d3d1e87b(caplog):
    caplog.set_level(logging.INFO, logger='memory_backend_adapter')

    payload = {
        'tenant_id': 'tenant-a',
        'user_id': 'user-1',
        'content': 'hello world',
        'layer': 'agent',
    }
    result = {'memory_id': 'mem-1'}

    caplog.clear()
    provider_service = MagicMock()
    provider_service._config_service.get_enabled_providers.return_value = []
    with patch(
        'services.memory_backend_adapter.get_memory_external_provider_service',
        return_value=provider_service,
    ), patch.object(
        MemoryIngestionEventService,
        'send_ingest_all_enabled',
        new_callable=AsyncMock,
    ) as send_mock:
        assert _run(_fanout_external_ingest(payload, result)) is None
        send_mock.assert_not_awaited()
    assert 'external_memory_ingest_skipped' in caplog.text
    assert 'reason=no_enabled_providers' in caplog.text

    caplog.clear()
    provider_service = MagicMock()
    provider_service._config_service.get_enabled_providers.return_value = [
        {'provider_name': 'p1', 'params': {'plugin.api_key': 'sk-LEAK-p1-1234567890'}},
        {'provider_name': 'p2', 'params': {'plugin.api_key': 'sk-LEAK-p2-1234567890'}},
    ]
    with patch(
        'services.memory_backend_adapter.get_memory_external_provider_service',
        return_value=provider_service,
    ), patch.object(
        MemoryIngestionEventService,
        'send_ingest_all_enabled',
        new_callable=AsyncMock,
    ) as send_mock:
        send_mock.return_value = [
            MemoryIngestResult(provider='p1', status='ok'),
            MemoryIngestResult(provider='p2', status='ok'),
        ]
        _run(_fanout_external_ingest(payload, result))
        send_mock.assert_awaited_once()
        call_kwargs = send_mock.await_args.kwargs
        assert call_kwargs['event_type'] == 'memory_stored'
        assert call_kwargs['event_id'] == 'mem-1'
        units = call_kwargs['units']
        assert len(units) == 1
        unit = units[0]
        assert isinstance(unit, MemoryIngestUnit)
        assert unit.event_id == 'mem-1'
        assert unit.event_type == 'memory_stored'
        assert unit.unit_type == 'agent'
        assert unit.unit_content == 'hello world'
    assert 'external_memory_ingest_completed' in caplog.text
    assert 'success_count=2' in caplog.text
    assert 'failure_count=0' in caplog.text
    assert 'sk-LEAK' not in caplog.text

    caplog.clear()
    provider_service = MagicMock()
    provider_service._config_service.get_enabled_providers.return_value = [
        {'provider_name': 'p1'},
        {'provider_name': 'p2'},
        {'provider_name': 'p3'},
    ]
    with patch(
        'services.memory_backend_adapter.get_memory_external_provider_service',
        return_value=provider_service,
    ), patch.object(
        MemoryIngestionEventService,
        'send_ingest_all_enabled',
        new_callable=AsyncMock,
    ) as send_mock:
        send_mock.return_value = [
            MemoryIngestResult(provider='p1', status='ok'),
            MemoryIngestResult(provider='p2', status='degraded'),
            MemoryIngestResult(provider='p3', status='failed'),
        ]
        _run(_fanout_external_ingest(payload, result))
    assert 'success_count=2' in caplog.text
    assert 'failure_count=1' in caplog.text

    caplog.clear()
    record_service = MagicMock()
    record_service.create_memory.return_value = {
        'memory_id': 'mem-1',
        'content': 'hello world',
    }
    provider_service = MagicMock()
    provider_service._config_service.get_enabled_providers.return_value = [
        {'provider_name': 'p1'}
    ]
    with patch(
        'services.memory_backend_adapter.get_memory_record_service',
        return_value=record_service,
    ), patch(
        'services.memory_backend_adapter.get_memory_external_provider_service',
        return_value=provider_service,
    ), patch.object(
        MemoryIngestionEventService,
        'send_ingest_all_enabled',
        new_callable=AsyncMock,
    ) as send_mock:
        send_mock.side_effect = RuntimeError('provider boom')
        stored = _run(
            _backend_store_hook(
                {
                    'tenant_id': 'tenant-a',
                    'user_id': 'user-1',
                    'content': 'hello world',
                    'layer': 'agent',
                    'embedding': [0.1, 0.2],
                }
            )
        )
        assert stored['memory_id'] == 'mem-1'
        record_service.create_memory.assert_called_once()
    assert 'external_memory_ingest_failed' in caplog.text
