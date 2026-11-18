# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Execution identity is internal, validated and stable across preparation retries."""

from types import SimpleNamespace

import pytest
from runtime.identity import ensure_request_run_id, resolve_execution_run_id
from runtime.workspace import create_run_workspace


def test_request_identity_is_stable_and_separate_from_public_identifiers():
    request = SimpleNamespace(conversation_id=123, _debug_run_id='debug-legacy', _runtime_automation_generation='42')
    first = ensure_request_run_id(request)
    assert len(first) == 32
    assert ensure_request_run_id(request) == first
    assert request.conversation_id == 123
    assert request._debug_run_id == 'debug-legacy'
    assert request._runtime_automation_generation == '42'
    assert resolve_execution_run_id(first) == first


def test_new_admission_gets_a_new_identity():
    request = SimpleNamespace()
    first = ensure_request_run_id(request)
    assert ensure_request_run_id(request, new=True) != first
    assert ensure_request_run_id(SimpleNamespace()) != first


@pytest.mark.parametrize('value', ['', '../bad', 'A' * 32, 'x' * 32, 'a' * 33, 123, True])
def test_untrusted_or_invalid_identity_is_rejected(value):
    with pytest.raises(ValueError, match='run_id'):
        resolve_execution_run_id(value)


def test_injected_identity_selects_the_same_workspace_on_retry(tmp_path):
    run_id = resolve_execution_run_id(None)
    first = create_run_workspace('user', resolve_execution_run_id(run_id), workspace_root=str(tmp_path))
    retry = create_run_workspace('user', resolve_execution_run_id(run_id), workspace_root=str(tmp_path))
    assert first == retry
    assert first.endswith(run_id)


def test_distributed_identity_helpers_forward_only_server_owned_reference(monkeypatch):
    from unittest.mock import Mock
    from runtime import identity, sandbox_runtime

    request = SimpleNamespace(conversation_id=7, _runtime_run_reference=SimpleNamespace(conversation_id='trial:owned'))
    assert identity.execution_conversation_id(request) == 'trial:owned'
    assert identity.execution_conversation_id(SimpleNamespace(conversation_id=7)) == 7
    assert identity.reference_options(None) == {}
    monkeypatch.setattr(identity, 'uses_distributed_runtime', lambda: True)
    coordinator = Mock()
    monkeypatch.setattr(sandbox_runtime, 'get_coordinator', lambda: coordinator)
    with pytest.raises(ValueError, match='tenant'):
        identity.current_reference_options('', 'user', 7)
    assert identity.current_reference_options('tenant', 'user', 7) == {
        'run_ref': coordinator.current_reference.return_value}
    bind, associate = Mock(), Mock()
    monkeypatch.setattr(sandbox_runtime, 'bind_request_reservation', bind)
    monkeypatch.setattr(sandbox_runtime, 'associate_request', associate)
    identity.bind_run_reservation(request, 'user')
    identity.associate_run_request(request, assistant_message_id=19)
    bind.assert_called_once_with(request, 'user')
    associate.assert_called_once_with(request, assistant_message_id=19)
    options = identity.distributed_run_options(request, 'tenant', kind='DEBUG')
    assert options['kind'] == 'DEBUG' and options['tenant_id'] == 'tenant'
    assert options['execution_run_id'] == request._runtime_execution_run_id


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['success', 'failed', 'cancelled', 'release_failed'])
async def test_cancelled_admission_cleans_up_late_exact_reservation(monkeypatch, outcome):
    import asyncio
    from concurrent.futures import Future
    from unittest.mock import Mock
    from infrastructure import concurrency
    from runtime import identity

    future = Future()
    manager, thread_manager = Mock(), Mock()
    thread_manager.submit.return_value = SimpleNamespace(future=future)
    monkeypatch.setattr(concurrency, 'runtime_thread_manager', thread_manager)
    if outcome == 'release_failed':
        manager.release_agent_run_reservation.side_effect = OSError('Redis unavailable')
    task = asyncio.create_task(identity.reserve_runtime_run(manager, 7, 'user', tenant_id='tenant'))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    if outcome == 'failed':
        future.set_exception(RuntimeError('reservation rejected'))
    elif outcome == 'cancelled':
        future.cancel()
    else:
        future.set_result('exact-token')
    await asyncio.sleep(0)
    assert manager.release_agent_run_reservation.call_count == int(outcome in {'success', 'release_failed'})
    if outcome in {'success', 'release_failed'}:
        manager.release_agent_run_reservation.assert_called_once_with(7, 'user', 'exact-token')


@pytest.mark.asyncio
async def test_coordination_calls_use_control_lane_and_preserve_local_execution(monkeypatch):
    from unittest.mock import AsyncMock, Mock
    import nexent.core.concurrency as concurrency
    from runtime import identity

    manager = Mock()
    assert await identity.reserve_runtime_run(manager, 7, 'user') is manager.reserve_agent_run.return_value
    function = Mock(return_value='local')
    monkeypatch.setattr(identity, 'uses_distributed_runtime', lambda: False)
    assert await identity.runtime_coordination_call('lookup', function, 7) == 'local'
    monkeypatch.setattr(identity, 'uses_distributed_runtime', lambda: True)
    run = AsyncMock(return_value='distributed')
    monkeypatch.setattr(concurrency, 'run_blocking', run)
    assert await identity.runtime_coordination_call('lookup', function, 7, user='user') == 'distributed'
    run.assert_awaited_once_with('lookup', function, 7, lane='control-io', owner='runtime', user='user')
