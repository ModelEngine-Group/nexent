# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from contracts.agent import AgentRequest
from management.services.agent import run


@pytest.mark.asyncio
async def test_old_generator_cancellation_passes_its_bound_generation_not_conversation_only(monkeypatch):
    request = AgentRequest(agent_id=1, conversation_id=7, query='old run')
    reference = SimpleNamespace(run_id='a' * 32, conversation_id=7)
    request.__dict__['_runtime_run_reference'] = reference
    old_info = SimpleNamespace()
    manager = Mock()
    monkeypatch.setattr(run, 'agent_run_manager', manager)
    monkeypatch.setattr(run, 'uses_distributed_runtime', lambda: True)
    monkeypatch.setattr(run, 'prepare_agent_run', AsyncMock(return_value=(old_info, None)))
    monkeypatch.setattr(run, '_cancel_task_on_runtime_signal', AsyncMock())
    unregister = Mock()
    monkeypatch.setattr(run, '_unregister_agent_run_after_execution', unregister)

    async def cancelled(**kwargs):
        raise asyncio.CancelledError
        yield ''

    monkeypatch.setattr(run, '_stream_agent_chunks', cancelled)
    with pytest.raises(asyncio.CancelledError):
        async for _ in run.generate_stream(request, 'user', 'tenant'):
            pass
    manager.stop_agent_run.assert_called_once_with(7, 'user', expected_generation='a' * 32, run_ref=reference)
    assert unregister.call_args.kwargs['agent_run_info'] is old_info
