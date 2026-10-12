"""TPC-D1-001: migrated thinking-prefix regression contract."""
import pytest
from shared.think_prefix_helpers import *

pytestmark = [pytest.mark.case_id("TPC-D1-001"), pytest.mark.stage("D1")]

@pytest.mark.parametrize("prefix", PREFIXES)
@pytest.mark.parametrize("legacy", [False, True])
def test_tpc_d1_001_compatible_prefix(prefix, legacy):
    result = classify_model_output(prefix + envelope(CODE, legacy), protocol="code_action")
    assert result == ExecutableAction(code=CODE, legacy_format=legacy)
