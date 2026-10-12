"""TPC-D1-006: migrated thinking-prefix regression contract."""
import pytest
from shared.think_prefix_helpers import *

pytestmark = [pytest.mark.case_id("TPC-D1-006"), pytest.mark.stage("D1")]

def test_tpc_d1_006_python_protocol_data_is_preserved():
    code = 'value = "<think>data</think><code>example</code>"\n# </think> comment\nprint(value)'
    assert classify_model_output("</think>" + envelope(code), protocol="code_action") == ExecutableAction(code=code)


def test_tpc_d1_006_component_python_data_is_preserved():
    payload = "<think>data</think><code>example</code>"
    code = f'value = {payload!r}\n# </think> comment\nprint(value)'
    agent, step, read_skill = make_agent("</think>" + envelope(code))
    outputs = list(agent._step_stream(step))
    agent.python_executor.assert_called_once_with(code)
    assert payload in step.observations
    assert len(outputs) == 1 and outputs[0].is_final_answer is False
    read_skill.assert_not_called()


@pytest.mark.parametrize("protocol,prefix", [("code_action", "</think>"), ("final_envelope", "")])
def test_tpc_d1_006_component_final_data_is_preserved(protocol, prefix):
    payload = "Literal <think>data</think> and </think> text."
    agent, step, read_skill = make_agent(prefix + f"<final_answer>{payload}</final_answer>")
    agent.output_protocol = protocol
    outputs = list(agent._step_stream(step))
    assert len(outputs) == 1 and outputs[0].is_final_answer is True
    assert outputs[0].output == payload
    assert step.action_output == payload
    read_skill.assert_not_called()
    agent.python_executor.assert_not_called()
