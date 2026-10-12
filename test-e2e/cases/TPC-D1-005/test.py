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
