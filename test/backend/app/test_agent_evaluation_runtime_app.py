# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Test Runtime's evaluation event collector at the AgentOS boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from contracts.agentos import EvaluationAgentRun
from infrastructure.agentos_identity import ServicePrincipal
from runtime.agentos.evaluation import _collect_case_events


@pytest.mark.asyncio
@pytest.mark.parametrize("conversation_id", [0, -42])
async def test_evaluation_case_preserves_event_order_and_execution_scope(conversation_id):
    payload = EvaluationAgentRun(
        agent_id=7,
        version_no=3,
        query="next question",
        history=[{"role": "user", "content": "previous question"}],
        conversation_id=conversation_id,
    )
    actor = ServicePrincipal("actor", "tenant")
    observer = Mock()
    observer.get_cached_message.return_value = ['{"type":"stats","content":"cached"}']
    info = SimpleNamespace(observer=observer)
    prepare = AsyncMock(return_value=(info, None))
    manager = Mock()
    thread_manager = object()

    async def runner(run_info, *, thread_manager):
        assert run_info is info
        yield '{"type":"thought","content":"step"}'
        yield "bad JSON"
        yield '{"type":"final_answer","content":"one "}'
        yield '{"type":"final_answer","content":"answer"}'

    result = await _collect_case_events(payload, actor, prepare, runner, manager, thread_manager)

    assert result.answer == "one answer"
    assert [event["type"] for event in result.events] == ["thought", "final_answer", "final_answer", "stats"]
    args = prepare.await_args.kwargs
    assert args["user_id"] == "actor"
    assert args["tenant_id"] == "tenant"
    assert args["allow_memory_search"] is False
    assert args["agent_request"].conversation_id == conversation_id
    assert [message.model_dump(exclude_none=True) for message in args["agent_request"].history] == payload.history
    manager.unregister_agent_run.assert_called_once_with(
        conversation_id, "actor", status="completed", agent_run_info=info,
    )
