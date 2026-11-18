# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Legacy actions use runtime results and preserve invalid-Python feedback."""
from types import SimpleNamespace

import pytest
from test_pr4005_continuation import _agent_with_responses, core_agent_module


class ExecutionError(Exception):
    def __init__(self, message, logger=None):
        super().__init__(message)


@pytest.fixture(autouse=True)
def exception_types(monkeypatch):
    monkeypatch.setattr(core_agent_module, "AgentExecutionError", ExecutionError)
    monkeypatch.setattr(core_agent_module, "AgentGenerationError", ExecutionError)


def test_mixed_code_and_final_executes_as_a_nonfinal_action(monkeypatch):
    output = '<code>print("done")</code><final_answer>UNCONFIRMED_CANDIDATE</final_answer>'
    agent, _, _ = _agent_with_responses([output], strict=False, monkeypatch=monkeypatch)
    agent.python_executor.return_value.output = "ACTUAL_RESULT"
    agent.python_executor.return_value.is_final_answer = False
    step = SimpleNamespace(step_number=1, model_output=None, model_output_message=None,
                           token_usage=None, model_input_messages=None, tool_calls=None,
                           observations=None, error=None)
    outputs = list(agent._step_stream(step))
    agent.python_executor.assert_called_once_with('print("done")')
    # Execution is accepted, but the candidate cannot bypass confirmation.
    assert outputs[-1].output == "ACTUAL_RESULT"
    assert outputs[-1].is_final_answer is False
    agent.observer.commit_model_attempt.assert_any_call("attempt-0", 1)
    agent.observer.rollback_model_attempt.assert_not_called()
    assert agent.model.call_count == 1


def test_shell_syntax_gets_python_feedback_before_execution(monkeypatch):
    output = '<code>import sys\nsys.executable -m pip install python-docx</code>'
    agent, _, _ = _agent_with_responses([output], strict=False, monkeypatch=monkeypatch)
    agent.clarification_tool_name = "ask_user"
    list(agent._run_stream("task", max_steps=1))
    agent.python_executor.assert_not_called()
    assert "Invalid Python action" in str(agent.memory.steps[0].error)
    assert "subprocess.run" in str(agent.memory.steps[0].error)


def test_valid_action_still_executes_with_optional_clarification(monkeypatch):
    agent, _, _ = _agent_with_responses(['<code>print("done")</code>'], strict=False, monkeypatch=monkeypatch)
    agent.clarification_tool_name = "ask_user"
    list(agent._run_stream("task", max_steps=1))
    agent.python_executor.assert_called_once()


def test_final_answer_may_contain_nonexecutable_markdown_code(monkeypatch):
    answer = 'Example:\n```python\nprint("example")\n```'
    agent, _, _ = _agent_with_responses(
        [f"<final_answer>{answer}</final_answer>"], strict=False, monkeypatch=monkeypatch
    )
    outputs = list(agent._run_stream("task", max_steps=1))
    agent.python_executor.assert_not_called()
    assert outputs[-1].output == answer


def test_mixed_action_waits_for_next_response_without_replaying_execution(monkeypatch):
    agent, _, _ = _agent_with_responses(
        ['<code>print("run once")</code><final_answer>UNCONFIRMED_CANDIDATE</final_answer>',
         '<final_answer>Confirmed ACTUAL_RESULT</final_answer>'],
        strict=False,
        monkeypatch=monkeypatch,
    )
    agent.python_executor.return_value.output = "ACTUAL_RESULT"
    agent.python_executor.return_value.is_final_answer = False
    outputs = list(agent._run_stream("task", max_steps=2))
    agent.python_executor.assert_called_once_with('print("run once")')
    assert agent.model.call_count == 2
    assert outputs[-1].output == "Confirmed ACTUAL_RESULT"
