"""TPC-D1-002: migrated thinking-prefix regression contract."""
import pytest
from shared.think_prefix_helpers import *

pytestmark = [pytest.mark.case_id("TPC-D1-002"), pytest.mark.stage("D1")]

@pytest.mark.parametrize("prefix", PREFIXES)
@pytest.mark.parametrize("prior_errors", [0, 2])
def test_tpc_d1_002_skill_action_executes_once(prefix, prior_errors):
    agent, step, read_skill = make_agent(prefix + envelope(CODE), prior_errors)
    outputs = list(agent._step_stream(step))
    read_skill.assert_called_once_with(skill_name="general_quality_checker")
    agent.python_executor.assert_called_once_with(CODE)
    assert len(outputs) == 1 and outputs[0].is_final_answer is False
    assert "Quality check guide" in step.observations
    assert not hasattr(step, "_final_answer_source")
    assert agent._consecutive_protocol_errors == 0
    agent.observer.commit_model_attempt.assert_called_once_with("prefix-attempt", 1)
    agent.observer.rollback_model_attempt.assert_not_called()
    agent.model.assert_called_once()
