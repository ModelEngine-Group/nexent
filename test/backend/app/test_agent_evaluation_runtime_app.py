# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Test Runtime's evaluation event collector at the AgentOS boundary."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from contracts.agentos import PreparedEvaluationRun
from infrastructure.agentos_identity import ServicePrincipal
from runtime.agentos import prepared_evaluation


@pytest.mark.asyncio
@pytest.mark.parametrize(("conversation_id", "fails"), [(0, False), (-42, False), (-42, True)])
async def test_evaluation_case_preserves_event_order_and_execution_scope(monkeypatch, tmp_path, conversation_id, fails):
    payload = PreparedEvaluationRun.model_validate({
        "mode": "nexent",
        "resource": {"agent_id": 7, "version_no": 3, "name": "agent", "description": "agent", "prompt_templates": {}},
        "models": {"llm": {"model_id": 11, "alias": "llm", "revision": "revision-1"}},
        "input": {"query": "next question", "history": [{"role": "user", "content": "previous question"}]},
        "conversation_id": conversation_id,
    })
    actor = ServicePrincipal("actor", "tenant")
    observer = Mock()
    observer.get_cached_message.return_value = ['{"type":"stats","content":"cached"}']
    info = SimpleNamespace(observer=observer, workspace_path=str(tmp_path), attempt_outcome=None, thread_future=None)
    prepare = Mock(return_value=info)

    async def run_blocking(_task, function, *args, **_kwargs):
        return function(*args)
    manager = Mock()
    monkeypatch.setattr(prepared_evaluation, "run_blocking", run_blocking)
    monkeypatch.setattr(prepared_evaluation, "prepare_evaluation_run", prepare)
    monkeypatch.setattr(prepared_evaluation, "agent_run_manager", manager)

    async def runner(run_info, *, thread_manager):
        assert run_info is info
        if fails:
            raise RuntimeError("agent failed")
        yield '{"type":"thought","content":"step"}'
        yield "bad JSON"
        yield '{"type":"final_answer","content":"one "}'
        yield '{"type":"final_answer","content":"answer"}'

    monkeypatch.setattr(prepared_evaluation, "agent_run", runner)
    expected = pytest.raises(RuntimeError, match="agent failed") if fails else nullcontext()
    with expected:
        result = await prepared_evaluation.execute_prepared_evaluation(payload, actor)
        assert result.answer == "one answer"
        assert [event["type"] for event in result.events] == ["thought", "final_answer", "final_answer", "stats"]
    prepare.assert_called_once_with(payload, actor)
    manager.register_agent_run.assert_called_once_with(conversation_id, info, "actor")
    manager.unregister_agent_run.assert_called_once_with(
        conversation_id, "actor", status="failed" if fails else "completed", agent_run_info=info,
    )
