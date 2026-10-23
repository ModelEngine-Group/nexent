"""V5 API-074 independently collected scenario."""

import pytest
from d3.scenarios import scenario_market_skill_mcp_a2a_scenarios as scenario
from shared.cases import case_params

@pytest.mark.parametrize("case", case_params("D3", ["API-074"]))
@pytest.mark.asyncio
async def test_api_074(case, tenant_a_user):
    await scenario.execute_market_skill_mcp_a2a_scenario(case, tenant_a_user)
