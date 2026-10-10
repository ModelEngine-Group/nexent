"""V5 DEP-06 independently collected scenario."""

import pytest
from d5.scenarios import scenario_reliability_deployment_special as scenario
from shared.cases import special_case_params

@pytest.mark.parametrize("case", special_case_params(["DEP-06"]))
@pytest.mark.asyncio
async def test_dep_06(case):
    # This command-stub contract does not call authenticated product APIs.
    await scenario.execute_d5_reliability_deployment_special(case, None, None)
