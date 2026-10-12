"""TPC-D1-003: migrated thinking-prefix regression contract."""
import pytest
from shared.think_prefix_helpers import *

pytestmark = [pytest.mark.case_id("TPC-D1-003"), pytest.mark.stage("D1")]

@pytest.mark.parametrize("output", INVALID[:7])
def test_tpc_d1_003_invalid_action_remains_error(output):
    with pytest.raises(ModelOutputProtocolError):
        classify_model_output(output, protocol="code_action")
