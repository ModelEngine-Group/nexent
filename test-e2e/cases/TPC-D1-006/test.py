"""TPC-D1-006: migrated thinking-prefix regression contract."""
import pytest
from shared.think_prefix_helpers import *

pytestmark = [pytest.mark.case_id("TPC-D1-006"), pytest.mark.stage("D1")]

def test_tpc_d1_006_python_protocol_data_is_preserved():
    code = 'value = "<think>data</think><code>example</code>"\n# </think> comment\nprint(value)'
    assert classify_model_output("</think>" + envelope(code), protocol="code_action") == ExecutableAction(code=code)
