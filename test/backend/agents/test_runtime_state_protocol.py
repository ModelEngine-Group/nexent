# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Public runtime state calls keep immutable generations through the Redis adapter."""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from management.services.agent.run_state import RuntimeStateService
from runtime.sandbox_coordination import SandboxRunReference
from runtime.sandbox_journal import SandboxCoordinationUnknown
from runtime.sandbox_stream_state import SandboxStreamState


@pytest.fixture
def protocol():
    coordinator = Mock()
    coordinator.redis_key.side_effect = lambda key: 'runtime:ksm:lease:' + key
    coordinator.client.eval.return_value = 1
    adapter = SandboxStreamState(coordinator, run_ttl=60, completed_ttl=20, stream_ttl=30,
                                cancel_ttl=10, max_stream_length=100)
    service = RuntimeStateService()
    service.configure_distributed(adapter)
    ref = SandboxRunReference('a' * 32, 'b' * 64, 'tenant', 'user', 7, 'uid', 'epoch', 'c' * 64, 'ACTIVE')
    return service, adapter, coordinator.client, ref


@pytest.mark.asyncio
async def test_stream_turn_runs_through_public_service_with_generation_scoped_keys(protocol):
    service, adapter, client, ref = protocol
    assert service.distributed_enabled
    service.configure_distributed(adapter)
    with pytest.raises(RuntimeError, match='immutable'):
        service.configure_distributed(object())
    await service.reset_stream_async('user', 7, generation='automation-42', run_ref=ref)
    service.register_run('user', 7, message_id=19, run_ref=ref)
    client.hgetall.return_value = {'status': 'running', 'generation': ref.run_id}
    assert (await service.get_run_state_async('user', 7, run_ref=ref))['generation'] == ref.run_id
    client.eval.return_value = '1-0'
    assert await service.append_stream_event_async('user', 7, 'chunk', run_ref=ref) == '1-0'
    client.eval.return_value = 0
    assert await service.append_stream_event_async('user', 7, 'stale', run_ref=ref) is None
    client.eval.return_value = 1
    assert service.set_cancel_signal('user', 7, expected_generation='automation-42', run_ref=ref)
    assert not service.set_cancel_signal('user', 7)
    client.get.return_value = ref.run_id
    assert await service.is_cancelled_async('user', 7, run_ref=ref)
    client.get.return_value = 'older-generation'
    assert not await service.is_cancelled_async('user', 7, run_ref=ref)
    client.xrange.return_value = [('1-0', {'chunk': 'first'}), ('2-0', {})]
    assert await service.read_stream_events_async('user', 7, run_ref=ref) == [('1-0', 'first'), ('2-0', '')]
    await service.read_stream_events_async('user', 7, after_id='1-0', run_ref=ref)
    assert client.xrange.call_args.kwargs['min'] == '(1-0'
    client.xread.return_value = [(adapter.keys(ref)[2], [('2-0', {'chunk': 'next'})])]
    assert await service.wait_for_stream_events_async('user', 7, '1-0', run_ref=ref) == [('2-0', 'next')]
    await service.mark_stream_completed_async('user', 7, status='failed', error='interrupted', run_ref=ref)
    service.mark_run_finished('user', 7, 'failed', generation='automation-42', run_ref=ref)
    client.hgetall.return_value = {'status': 'failed'}
    assert await service.get_stream_status_async('user', 7, run_ref=ref) == {'status': 'failed'}
    keys = [arg for call in client.mock_calls for arg in call.args
            if isinstance(arg, str) and arg.startswith('runtime:')]
    assert keys and all(key.startswith('runtime:ksm:') for key in keys)
    before = len(client.mock_calls)
    with pytest.raises(SandboxCoordinationUnknown):
        await service.append_stream_event_async('foreign-user', 7, 'forbidden', run_ref=ref)
    assert len(client.mock_calls) == before


def test_missing_active_state_is_unknown_while_terminal_and_unbound_reads_are_empty(protocol):
    service, adapter, client, ref = protocol
    client.hgetall.return_value = {}
    assert service.get_run_state('user', 7) == {}
    with pytest.raises(SandboxCoordinationUnknown, match='ownership remains unknown'):
        service.get_run_state('user', 7, run_ref=ref)
    assert service.get_run_state('user', 7, run_ref=replace(ref, phase='TERMINAL')) == {}
    assert service.get_stream_status('user', 7, run_ref=ref) == {}


@pytest.mark.parametrize('value', [0, -1, True, 1.5])
def test_stream_retention_requires_positive_integer_policy(value):
    with pytest.raises(ValueError):
        SandboxStreamState(Mock(), run_ttl=value, completed_ttl=20, stream_ttl=30,
                           cancel_ttl=10, max_stream_length=100)
