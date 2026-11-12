# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Legacy feedback distinguishes invalid Python and mixed action/final responses."""
import pytest
from test_pr4005_continuation import _agent_with_responses, core_agent_module


class ExecutionError(Exception):
    def __init__(self, message, logger=None):
        super().__init__(message)


@pytest.fixture(autouse=True)
def exception_types(monkeypatch):
    monkeypatch.setattr(core_agent_module, "AgentExecutionError", ExecutionError)
    monkeypatch.setattr(core_agent_module, "AgentGenerationError", ExecutionError)


def test_mixed_code_and_final_is_rejected_with_actionable_feedback(monkeypatch):
    output = '<code>print("done")</code><final_answer>done</final_answer>'
    agent, _, _ = _agent_with_responses([output], strict=False, monkeypatch=monkeypatch)
    list(agent._run_stream("task", max_steps=1))
    agent.python_executor.assert_not_called()
    assert "Do not combine" in str(agent.memory.steps[0].error)


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


def test_mixed_action_recovers_on_next_step_without_executing_it_twice(monkeypatch):
    agent, _, _ = _agent_with_responses(
        ['<code>print("unsafe mixed")</code><final_answer>done</final_answer>',
         '<code>print("confirmed action")</code>', '<final_answer>done</final_answer>'],
        strict=False,
        monkeypatch=monkeypatch,
    )
    agent.python_executor.return_value.is_final_answer = False
    outputs = list(agent._run_stream("task", max_steps=3))
    agent.python_executor.assert_called_once_with('print("confirmed action")')
    assert outputs[-1].output == "done"
