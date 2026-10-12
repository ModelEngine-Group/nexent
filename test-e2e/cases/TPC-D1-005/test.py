"""TPC-D1-005: migrated thinking-prefix regression contract."""
import pytest
from shared.think_prefix_helpers import *

pytestmark = [pytest.mark.case_id("TPC-D1-005"), pytest.mark.stage("D1")]

@pytest.mark.parametrize("prefix", PREFIXES)
def test_tpc_d1_005_ordinary_final_prefix(prefix):
    payload = "Checked **quality**."
    output = prefix + f"<final_answer>{payload}</final_answer>"
    assert classify_model_output(output, protocol="code_action") == ExplicitFinalAnswer(answer=payload)
    with pytest.raises(ModelOutputProtocolError):
        classify_model_output(output, protocol="final_envelope")


@pytest.mark.parametrize("output", INVALID[7:10])
def test_tpc_d1_005_final_boundaries_remain_strict(output):
    with pytest.raises(ModelOutputProtocolError):
        classify_model_output(output, protocol="code_action")


@pytest.mark.parametrize("prefix", PREFIXES)
def test_tpc_d1_005_component_final_preserves_payload(prefix):
    payload = "Checked **quality**."
    agent, step, read_skill = make_agent(prefix + f"<final_answer>{payload}</final_answer>")
    outputs = list(agent._step_stream(step))
    assert len(outputs) == 1 and outputs[0].is_final_answer is True
    assert outputs[0].output == payload
    assert step.action_output == payload
    agent.python_executor.assert_not_called()
    read_skill.assert_not_called()
    assert agent._consecutive_protocol_errors == 0


@pytest.mark.parametrize("output,protocol", [
    *[(value, "code_action") for value in INVALID[7:10]],
    *[(prefix + "<final_answer>Checked.</final_answer>", "final_envelope") for prefix in PREFIXES],
])
def test_tpc_d1_005_component_final_rejects_boundaries(output, protocol):
    agent, step, read_skill = make_agent(output)
    agent.output_protocol = protocol
    with pytest.raises(ModelOutputProtocolError):
        list(agent._step_stream(step))
    read_skill.assert_not_called()
    agent.python_executor.assert_not_called()
    agent.observer.commit_model_attempt.assert_not_called()
    assert not hasattr(step, "_final_answer_source")
