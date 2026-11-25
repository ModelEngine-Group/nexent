# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unparsed provider tool markup must never become a CodeAgent answer."""

from types import SimpleNamespace
from unittest.mock import call

import pytest
from test_pr4005_continuation import _agent_with_responses, core_agent_module

from nexent.core.agents.cores.smolagents.output_protocol import (
    ModelOutputProtocolError,
    classify_model_output,
)


DSML = (
    '<｜｜DSML｜｜ calls><｜｜DSML｜｜ invoke name="run_skill_script">'
    '<｜｜DSML｜｜ parameter name="script_path" string="true">scripts/check_state.py'
    '</｜｜DSML｜｜ parameter></｜｜DSML｜｜ invoke></｜｜DSML｜｜ calls>'
)
FIRST_ACTION = 'print("completed_once")'
RECOVERED_ACTION = 'print("remaining_work")'


@pytest.mark.parametrize("reply", [
    DSML,
    f"<final_answer>{DSML}</final_answer>",
    f"<code>{FIRST_ACTION}</code>{DSML}",
])
def test_legacy_dsml_recovery_rejects_markup_without_replaying_first_action(reply, monkeypatch):
    agent, _, _ = _agent_with_responses(
        [f"<code>{FIRST_ACTION}</code>", reply, f"<code>{RECOVERED_ACTION}</code>",
         "<final_answer>actual result</final_answer>"],
        strict=False,
        monkeypatch=monkeypatch,
    )
    agent.python_executor.return_value = SimpleNamespace(output="observed", logs="", is_final_answer=False)

    steps = list(agent._run_stream("Complete both actions in order.", max_steps=4))

    assert steps[-1].output == "actual result"
    assert [item.args[0] for item in agent.python_executor.call_args_list] == [FIRST_ACTION, RECOVERED_ACTION]
    agent.observer.rollback_model_attempt.assert_called_once_with("attempt-1", 1)
    assert agent.observer.commit_model_attempt.call_args_list == [
        call("attempt-0", 1), call("attempt-2", 1), call("attempt-3", 1),
    ]


def test_repeated_legacy_dsml_fails_after_one_corrective_generation(monkeypatch):
    agent, _, _ = _agent_with_responses([DSML, DSML], strict=False, monkeypatch=monkeypatch)

    with pytest.raises(core_agent_module.ModelOutputProtocolExhaustedError):
        list(agent._run_stream("Use the script tool.", max_steps=4))

    assert agent.model.call_count == 2
    agent.python_executor.assert_not_called()
    agent.observer.commit_model_attempt.assert_not_called()
    assert agent.observer.rollback_model_attempt.call_args_list == [call("attempt-0", 1), call("attempt-1", 1)]


@pytest.mark.parametrize("reply", [
    f"<final_answer>{DSML}</final_answer>",
    '<final_answer><｜DSML｜tool_calls></｜DSML｜tool_calls></final_answer>',
    '<final_answer><|DSML|function_calls></|DSML|function_calls></final_answer>',
    '<final_answer><｜DSML｜inv',
])
def test_terminal_classifier_rejects_provider_tool_markup(reply):
    with pytest.raises(ModelOutputProtocolError):
        classify_model_output(reply, protocol="final_envelope")
