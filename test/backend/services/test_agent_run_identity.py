# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Preparation retries propagate admission identity without changing public run keys."""

import sys
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from runtime.identity import ensure_request_run_id

from . import test_agent_service as legacy


@pytest.mark.asyncio
async def test_prepare_reuses_admission_identity_on_retry(monkeypatch):
    module = sys.modules[legacy.prepare_agent_run.__module__]
    request = legacy.AgentRequest(agent_id=1, conversation_id=123, query='q', is_debug=True)
    run_id = ensure_request_run_id(request)
    info = MagicMock()
    info.agent_config.context_manager_config = None
    create = AsyncMock(return_value=info)
    registry = MagicMock()
    monkeypatch.setattr(module, 'create_agent_run_info', create)
    monkeypatch.setattr(module, 'agent_run_manager', registry)
    monkeypatch.setattr(module, 'build_memory_context', MagicMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(module, 'build_authorized_context_input', MagicMock(return_value=SimpleNamespace()))
    for _ in range(2):
        await legacy.prepare_agent_run(request, 'user', 'tenant', reservation_token='reservation')
    assert [call.kwargs['execution_run_id'] for call in create.await_args_list] == [run_id, run_id]
    assert all(call.kwargs['conversation_id'] == 123 for call in create.await_args_list)
    assert registry.register_agent_run.call_args.args[0] == 123


@pytest.mark.asyncio
async def test_background_admissions_keep_automation_generation_separate(monkeypatch):
    module = sys.modules[legacy.prepare_agent_run.__module__]
    request = legacy.AgentRequest(agent_id=1, conversation_id=123, query='q', is_debug=False)
    seen = []

    async def source(current, **_kwargs):
        seen.append(current.__dict__['_runtime_execution_run_id'])
        yield '{}'

    monkeypatch.setattr(module, 'agent_run_manager', MagicMock())
    monkeypatch.setattr(module, 'generate_stream', source)
    monkeypatch.setattr(module, 'save_messages', MagicMock())
    monkeypatch.setattr(module, 'build_agent_run_context', MagicMock(return_value=SimpleNamespace(metadata={}, enable_memory=False)))
    monkeypatch.setattr(module, 'agent_monitoring_context', lambda *_: nullcontext())
    monkeypatch.setattr(module.runtime_state_service, 'reset_stream_async', AsyncMock())
    state = SimpleNamespace(runtime_generation='automation-42', is_active=None, result=dict)
    for _ in range(2):
        await module.run_agent_background(request, 'user', 'tenant', execution_state=state)
    assert len(set(seen)) == 2
    assert all(len(run_id) == 32 and run_id != 'automation-42' for run_id in seen)
    assert request.__dict__['_runtime_automation_generation'] == 'automation-42'


@pytest.mark.asyncio
async def test_pre_admitted_background_run_reuses_worker_and_releases_exact_reservation(monkeypatch):
    from runtime.sandbox_runtime import PreparedRuntimeRun

    module = sys.modules[legacy.prepare_agent_run.__module__]
    request = legacy.AgentRequest(agent_id=1, conversation_id=123, query='q', is_debug=True)
    execution, deferred = MagicMock(), MagicMock()
    admission = PreparedRuntimeRun('a' * 32, 'owned-token', 123, 'tenant', 'user', object(), deferred, execution)
    manager = MagicMock()
    monkeypatch.setattr(module, 'agent_run_manager', manager)
    monkeypatch.setattr(module, 'uses_distributed_runtime', lambda: True)
    associate = MagicMock()
    monkeypatch.setattr(module, 'associate_run_request', associate)
    monkeypatch.setattr(module, 'bind_run_reservation', MagicMock())
    async def coordinate(_name, function, *args, **kwargs):
        return function(*args, **kwargs)
    monkeypatch.setattr(module, 'runtime_coordination_call', coordinate)
    seen = {}
    async def source(current, **kwargs):
        seen.update(kwargs)
        yield '{}'
    monkeypatch.setattr(module, 'generate_stream', source)
    monkeypatch.setattr(module, 'build_agent_run_context', MagicMock(return_value=SimpleNamespace(metadata={}, enable_memory=False)))
    monkeypatch.setattr(module, 'agent_monitoring_context', lambda *_: nullcontext())
    monkeypatch.setattr(module.runtime_state_service, 'reset_stream_async', AsyncMock())
    state = SimpleNamespace(runtime_generation='42', is_active=None, result=dict)
    result = await module.run_agent_background(request, 'user', 'tenant', execution_state=state, runtime_admission=admission)
    assert result['chunks'] == 1
    assert seen['execution'] is execution and seen['deferred_run'] is deferred
    assert seen['reservation_token'] == 'owned-token'
    assert request._runtime_execution_run_id == admission.run_id
    assert request._runtime_execution_future is execution.future
    associate.assert_called_once_with(request, automation_run_id='42')
    manager.reserve_agent_run.assert_not_called()
    manager.release_agent_run_reservation.assert_called_once_with(123, 'user', 'owned-token')
    with pytest.raises(ValueError, match='Invalid pre-admitted'):
        await module.run_agent_background(request, 'foreign', 'tenant', execution_state=state, runtime_admission=admission)


@pytest.mark.parametrize('phase,expected', [(None, False), ('TERMINAL', False), ('ACTIVE', True)])
def test_running_lookup_uses_current_generation_in_distributed_mode(monkeypatch, phase, expected):
    module = sys.modules[legacy.prepare_agent_run.__module__]
    reference = SimpleNamespace(phase=phase) if phase is not None else None
    monkeypatch.setattr(module, 'current_reference_options', lambda *args: {'run_ref': reference})
    assert module.is_agent_running(123, 'user', tenant_id='tenant') is expected
