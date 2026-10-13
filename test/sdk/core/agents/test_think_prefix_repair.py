"""Unit regressions for the actual repair loop, with execution substituted."""

from types import SimpleNamespace
from unittest.mock import call

import pytest
from test_pr4005_continuation import _agent_with_responses, core_agent_module

CODE = 'skill_content = read_skill_md(skill_name="general_quality_checker")\nprint(skill_content)'
REJECTED = [
    '</think><code>read_skill_md(',
    '<think>Read the guide.<code>read_skill_md(</code>',
    '<code></code>',
    '<code>print(1)</code>explanation<code>print(2)</code>',
    '<code>print(1)</code>suffix',
    '<analysis>reason</analysis><code>print(1)</code>',
    '<|channel|>analysis<code>print(1)</code>',
    '<final_answer>partial',
    '<final_answer>one</final_answer><final_answer>two</final_answer>',
    '<final_answer>done</final_answer>suffix',
    '<think>Only think.</think>',
    'Only think.</think>',
    '<think>Only think.',
]


def _finish_reasons(agent, responses, reasons):
    attempts = iter(zip(responses, reasons))

    def generate(*_args, **_kwargs):
        response, reason = next(attempts)
        agent.model.last_finish_reason = reason
        return response

    agent.model.side_effect = generate


@pytest.mark.parametrize('last,finish_reason', [(text, 'stop') for text in REJECTED] + [
    ('</think><code>' + CODE + '</code>', 'length'),
])
def test_rejected_outputs_exhaust_without_effects(monkeypatch, last, finish_reason):
    agent, responses, _ = _agent_with_responses(
        ['<code></code>', '<code>broken(</code>', last], strict=True, monkeypatch=monkeypatch,
    )
    _finish_reasons(agent, responses, ['stop', 'stop', finish_reason])
    with pytest.raises(core_agent_module.ModelOutputProtocolExhaustedError):
        list(agent._run_stream('task', max_steps=2))
    assert agent.model.call_count == 3
    agent.python_executor.assert_not_called()
    agent.observer.commit_model_attempt.assert_not_called()
    assert agent.observer.rollback_model_attempt.call_args_list == [call(f'attempt-{i}', 1) for i in range(3)]
    assert agent.memory.steps == []
    assert agent._consecutive_protocol_errors == 3


@pytest.mark.parametrize('legacy', [False, True])
def test_valid_third_action_is_not_replayed(monkeypatch, legacy):
    action = f'```<run>\n{CODE}\n```' if legacy else f'<code>{CODE}</code>'
    agent, responses, _ = _agent_with_responses(
        ['<code></code>', '<code>broken(</code>', '</think>' + action,
         '<final_answer>Checked.</final_answer>'], strict=True, monkeypatch=monkeypatch,
    )
    agent.python_executor.return_value = SimpleNamespace(
        output='Quality check guide', is_final_answer=False, logs='Quality check guide',
    )
    outputs = list(agent._run_stream('task', max_steps=2))
    assert outputs[-1].output == 'Checked.'
    agent.python_executor.assert_called_once_with(CODE)
    assert agent.observer.commit_model_attempt.call_args_list == [
        call('attempt-2', 1), call('attempt-3', 1),
    ]
    assert agent.observer.rollback_model_attempt.call_args_list == [
        call('attempt-0', 1), call('attempt-1', 1),
    ]
    assert agent.model.call_count == 4
    assert len(agent.memory.steps) == 2
    assert agent.memory.steps[0].action_output == 'Quality check guide'
    assert all(not hasattr(step, '_final_answer_source') for step in agent.memory.steps)
    assert agent._consecutive_protocol_errors == 0
