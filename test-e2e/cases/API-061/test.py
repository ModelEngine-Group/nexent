"""V5 API-061 independently collected scenario."""

import pytest
from d3.scenarios import scenario_agent_configuration_scenarios as scenario
from shared.cases import case_params

@pytest.mark.parametrize("case", case_params("D3", ["API-061"]))
@pytest.mark.asyncio
async def test_api_061(case, tenant_a_admin, tenant_a_user, tenant_b_user):
    await scenario.execute_agent_configuration_scenario(case, tenant_a_admin, tenant_a_user, tenant_b_user)
