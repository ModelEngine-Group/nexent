# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Completed-action echoes must never replay recorded NL2Agent saves."""

from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest
from test_pr4005_continuation import _agent_with_responses, core_agent_module


SAVE_CODE = 'saved = nl2a_save_agent_draft_fields(agent_id=172, fields={"description": "saved"})\nprint(saved)'
HISTORY = (
    '<completed_action_history read_only="true">\n'
    'This is an already completed action record. Use it only as historical evidence.\n'
    '<completed_action>\nindex: 1\ntool: python_interpreter\n'
    f'input:\n{SAVE_CODE}\noutcome:\nExecution logs: {{"status":"success"}}\n'
    'recorded_error: None\nrecorded_result: None\n'
    '</completed_action>\n</completed_action_history>'
)
ECHOES = [HISTORY, f'<code>{SAVE_CODE}</code>\n{HISTORY}', f'{HISTORY}\n<code>{SAVE_CODE}</code>']


@pytest.mark.parametrize("echo", ECHOES, ids=["history", "action_then_history", "history_then_action"])
def test_history_echo_repairs_without_replaying_completed_save(echo, monkeypatch):
    agent, _, _ = _agent_with_responses(
        [f'<code>{SAVE_CODE}</code>', echo, '<code>print("next")</code>', '<final_answer>done</final_answer>'],
        strict=True,
        monkeypatch=monkeypatch,
    )
    agent.python_executor.return_value = SimpleNamespace(output="saved", logs="success", is_final_answer=False)

    outputs = list(agent._run_stream("task", max_steps=4))

    assert outputs[-1].output == "done"
    assert agent.model.call_count == 4
    assert agent.python_executor.call_count == 2
    assert [item.args[0].strip() for item in agent.python_executor.call_args_list] == [SAVE_CODE, 'print("next")']
    agent.observer.rollback_model_attempt.assert_called_once_with("attempt-1", 1)
    assert agent.observer.commit_model_attempt.call_args_list == [
        call("attempt-0", 1), call("attempt-2", 1), call("attempt-3", 1),
    ]


@pytest.mark.parametrize("echo", ECHOES, ids=["history", "action_then_history", "history_then_action"])
def test_history_echo_exhaustion_never_executes_or_becomes_raw_answer(echo, monkeypatch):
    agent, _, _ = _agent_with_responses([echo] * 3, strict=True, monkeypatch=monkeypatch)
    agent._handle_max_steps_reached = MagicMock()

    with pytest.raises(core_agent_module.ModelOutputProtocolExhaustedError):
        list(agent._run_stream("task", max_steps=4))

    assert agent.model.call_count == 3
    assert agent.observer.rollback_model_attempt.call_args_list == [
        call("attempt-0", 1), call("attempt-1", 1), call("attempt-2", 1),
    ]
    agent.observer.commit_model_attempt.assert_not_called()
    agent.python_executor.assert_not_called()
    agent._handle_max_steps_reached.assert_not_called()
