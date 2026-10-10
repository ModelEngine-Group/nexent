"""TPC-D5-001: exhaustion never finalizes or executes rejected marked output."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nexent.core.agents.output_protocol import ModelOutputProtocolError
from test.automation.d1.test_think_prefix_compatibility import CODE, envelope, make_agent


@pytest.mark.parametrize("last,finish_reason,valid", [
    ("</think><code>read_skill_md(", "stop", False),
    ("</think>" + envelope(CODE), "length", False),
    ("</think>" + envelope(CODE), "stop", True),
])
def test_tpc_d5_001_rejections_do_not_execute_or_finalize(monkeypatch, last, finish_reason, valid):
    monkeypatch.setattr("nexent.core.agents.core_agent.get_monitoring_manager", lambda: MagicMock())
    agent, _, read_skill = make_agent("unused")
    agent.model.side_effect = [
        SimpleNamespace(content=content, token_usage=None, model_attempt_id=f"risk-{i}",
                        model_attempt_number=i, model_attempt_commit_deferred=True)
        for i, content in enumerate(["<code></code>", "<code>broken(</code>", last], 1)
    ]
    for index in range(3):
        step = SimpleNamespace(step_number=1, model_output=None, model_output_message=None,
                               token_usage=None, tool_calls=None, observations=None)
        agent.model.last_finish_reason = finish_reason if index == 2 else "stop"
        if index == 2 and valid:
            result = list(agent._step_stream(step))
            assert len(result) == 1 and result[0].is_final_answer is False
            read_skill.assert_called_once_with(skill_name="general_quality_checker")
            assert agent._consecutive_protocol_errors == 0
        else:
            with pytest.raises(ModelOutputProtocolError):
                list(agent._step_stream(step))
            agent._consecutive_protocol_errors += 1
            read_skill.assert_not_called()
        assert not hasattr(step, "_final_answer_source")
    assert agent.model.call_count == 3
    assert agent.python_executor.call_count == int(valid)
    assert agent.observer.rollback_model_attempt.call_count == (2 if valid else 3)
    assert agent.observer.commit_model_attempt.call_count == int(valid)
