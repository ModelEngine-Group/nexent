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


@pytest.mark.parametrize(
    "echo",
    [*ECHOES, f"<final_answer>{HISTORY}</final_answer>"],
    ids=["history", "action_then_history", "history_then_action", "final_envelope"],
)
def test_repeated_legacy_history_echo_stops_without_committing_or_replaying(echo, monkeypatch):
    agent, _, _ = _agent_with_responses(
        [f"<code>{SAVE_CODE}</code>", echo, echo],
        strict=False,
        monkeypatch=monkeypatch,
    )
    agent.python_executor.return_value = SimpleNamespace(output="saved", logs="success", is_final_answer=False)

    with pytest.raises(core_agent_module.ModelOutputProtocolExhaustedError):
        list(agent._run_stream("task", max_steps=4))

    agent.python_executor.assert_called_once()
    assert agent.python_executor.call_args.args[0] == SAVE_CODE
    agent.observer.commit_model_attempt.assert_called_once_with("attempt-0", 1)
    assert agent.observer.rollback_model_attempt.call_args_list == [call("attempt-1", 1), call("attempt-2", 1)]


def test_final_envelope_parser_rejects_history_during_max_steps_fallback():
    from nexent.core.agents.cores.smolagents.output_protocol import (
        ModelOutputProtocolError,
        ProtocolErrorReason,
        classify_model_output,
    )

    with pytest.raises(ModelOutputProtocolError) as error:
        classify_model_output(f"<final_answer>{HISTORY}</final_answer>", protocol="final_envelope")
    assert error.value.reason == ProtocolErrorReason.UNSUPPORTED_OR_TAG_ONLY_OUTPUT


def test_legacy_history_echo_recovers_from_a_failed_prerequisite(monkeypatch):
    followup = 'print("prerequisite fixed")'
    agent, _, _ = _agent_with_responses(
        [f"<code>{SAVE_CODE}</code>", HISTORY, f"<code>{followup}</code>", "<final_answer>done</final_answer>"],
        strict=False,
        monkeypatch=monkeypatch,
    )
    agent.python_executor.side_effect = [
        FileNotFoundError("doubled.txt"), SimpleNamespace(output="accepted", logs="", is_final_answer=False),
    ]

    output = list(agent._run_stream("task", max_steps=4))

    assert output[-1].output == "done"
    assert [item.args[0] for item in agent.python_executor.call_args_list] == [SAVE_CODE, followup]
    agent.observer.rollback_model_attempt.assert_called_once_with("attempt-1", 1)
