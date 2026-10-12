"""TPC-D1-001: migrated thinking-prefix regression contract."""
import pytest
from shared.think_prefix_helpers import *

pytestmark = [pytest.mark.case_id("TPC-D1-001"), pytest.mark.stage("D1")]

@pytest.mark.parametrize("prefix", PREFIXES)
@pytest.mark.parametrize("legacy", [False, True])
def test_tpc_d1_001_compatible_prefix(prefix, legacy):
    result = classify_model_output(prefix + envelope(CODE, legacy), protocol="code_action")
    assert result == ExecutableAction(code=CODE, legacy_format=legacy)


@pytest.mark.parametrize("prefix", PREFIXES)
@pytest.mark.parametrize("legacy", [False, True])
def test_tpc_d1_001_component_accepts_exact_action(prefix, legacy):
    agent, step, read_skill = make_agent(prefix + envelope(CODE, legacy))
    outputs = list(agent._step_stream(step))
    agent.python_executor.assert_called_once_with(CODE)
    read_skill.assert_called_once_with(skill_name="general_quality_checker")
    assert "Quality check guide" in step.observations
    assert len(outputs) == 1 and outputs[0].is_final_answer is False
    agent.observer.commit_model_attempt.assert_called_once_with("prefix-attempt", 1)
    agent.observer.rollback_model_attempt.assert_not_called()
