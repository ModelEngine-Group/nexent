"""TPC-D1-003: migrated thinking-prefix regression contract."""
import pytest

from nexent.core.agents.output_protocol import ProtocolErrorReason
from shared.think_prefix_helpers import *

pytestmark = [pytest.mark.case_id("TPC-D1-003"), pytest.mark.stage("D1")]

@pytest.mark.parametrize("output", INVALID[:7])
def test_tpc_d1_003_invalid_action_remains_error(output):
    with pytest.raises(ModelOutputProtocolError) as exc:
        classify_model_output(output, protocol="code_action")
    assert exc.value.reason == ProtocolErrorReason.MALFORMED_ACTION


@pytest.mark.parametrize("output,finish_reason,reason", [
    *[(value, "stop", ProtocolErrorReason.MALFORMED_ACTION) for value in INVALID[:7]],
    ("</think>" + envelope(CODE), "length", ProtocolErrorReason.TRUNCATED_GENERATION),
])
def test_tpc_d1_003_component_rejects_without_execution(output, finish_reason, reason):
    agent, step, read_skill = make_agent(output, finish_reason=finish_reason)
    with pytest.raises(ModelOutputProtocolError) as exc:
        list(agent._step_stream(step))
    assert exc.value.reason == reason
    read_skill.assert_not_called()
    agent.python_executor.assert_not_called()
    agent.observer.commit_model_attempt.assert_not_called()
    agent.observer.rollback_model_attempt.assert_called_once_with("prefix-attempt", 1)
    assert not hasattr(step, "_final_answer_source")
