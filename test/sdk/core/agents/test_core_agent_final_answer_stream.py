"""Terminal answer regressions through the CoreAgent loop."""

import pytest

from test_pr4005_continuation import _agent_with_responses


@pytest.mark.parametrize("prefix", ["", "Reasoning. "])
def test_legacy_final_envelope_takes_precedence_over_answer_code_fences(monkeypatch, prefix):
    answer = "Example:\n```python\nprint('example')\n```"
    agent, _, _ = _agent_with_responses(
        [prefix + "<final_answer>" + answer + "</final_answer>"],
        strict=False, monkeypatch=monkeypatch,
    )
    output = list(agent._run_stream("task", max_steps=1))[-1]
    assert output.output == answer
    agent.python_executor.assert_not_called()
    agent.observer.mark_direct_final_answer.assert_not_called()


@pytest.mark.parametrize("has_hook", [True, False])
def test_exhausted_protocol_error_accepts_raw_answer_without_executing_code(monkeypatch, has_hook):
    agent, _, _ = _agent_with_responses(
        ["<code></code>", "<code>broken(</code>", "Code: Completed result."],
        strict=True, monkeypatch=monkeypatch,
    )
    if not has_hook:
        agent.observer.mark_direct_final_answer = None
    assert list(agent._run_stream("task", max_steps=1))[-1].output == "Code: Completed result."
    agent.python_executor.assert_not_called()


def test_legacy_answer_preserves_content_without_optional_reclassification_hook(monkeypatch):
    agent, _, _ = _agent_with_responses(["Plain answer"], strict=False, monkeypatch=monkeypatch)
    agent.observer.mark_direct_final_answer = None
    assert list(agent._run_stream("task", max_steps=1))[-1].output == "Plain answer"
    agent.python_executor.assert_not_called()
