"""V5 AGT-063 independently collected scenario."""

import pytest
from d3.scenarios import scenario_evaluation_scenarios as scenario
from shared.cases import case_params

@pytest.mark.parametrize("case", case_params("D3", ["AGT-063"]))
@pytest.mark.asyncio
async def test_agt_063(case, tenant_a_admin):
    await scenario.execute_d3_evaluation(case, tenant_a_admin)
