"""V5 CTR-028 independently collected scenario."""

import pytest
from d3.scenarios import scenario_market_skill_mcp_a2a_scenarios as scenario
from shared.cases import case_params

@pytest.mark.parametrize("case", case_params("D3", ["CTR-028"]))
@pytest.mark.asyncio
async def test_ctr_028(case, tenant_a_user):
    await scenario.execute_market_skill_mcp_a2a_scenario(case, tenant_a_user)
