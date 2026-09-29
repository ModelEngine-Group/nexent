"""V5 AGT-038 independently collected scenario."""

import pytest
from d3.scenarios import scenario_agent_runtime_scenarios as scenario
from shared.cases import case_params

@pytest.mark.parametrize("case", case_params("D3", ["AGT-038"]))
@pytest.mark.asyncio
async def test_agt_038(case, tenant_a_user):
    await scenario.execute_agent_runtime_scenario(case, tenant_a_user)
