"""TPC-D1-004: migrated thinking-prefix regression contract."""
import pytest
from shared.think_prefix_helpers import *

pytestmark = [pytest.mark.case_id("TPC-D1-004"), pytest.mark.stage("D1")]

@pytest.mark.parametrize("output", INVALID)
def test_tpc_d1_004_marked_output_never_raw_final(output):
    agent, step, read_skill = make_agent(output, 2)
    with pytest.raises(ModelOutputProtocolError):
        list(agent._step_stream(step))
    read_skill.assert_not_called()
    agent.python_executor.assert_not_called()
    assert not hasattr(step, "_final_answer_source")
    agent.observer.rollback_model_attempt.assert_called_once_with("prefix-attempt", 1)
    agent.observer.commit_model_attempt.assert_not_called()


def test_tpc_d1_004_plain_exhaustion_remains_compatible():
    agent, step, read_skill = make_agent("A complete plain answer.", 2)
    outputs = list(agent._step_stream(step))
    assert outputs[0].is_final_answer is True
    assert outputs[0].output == "A complete plain answer."
    assert step._final_answer_source == "protocol_exhausted_raw_output"
    read_skill.assert_not_called()
    agent.python_executor.assert_not_called()
