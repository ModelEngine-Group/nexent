"""V5 CTR-030 independently collected scenario."""

import pytest
from d3.scenarios import scenario_market_skill_mcp_a2a_scenarios as scenario
from shared.cases import case_params

@pytest.mark.parametrize("case", case_params("D3", ["CTR-030"]))
@pytest.mark.asyncio
async def test_ctr_030(case, tenant_a_admin):
    await scenario.execute_market_skill_mcp_a2a_scenario(case, tenant_a_admin)
