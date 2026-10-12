"""V5 API-158 independently collected scenario."""

import pytest
from d3.scenarios import scenario_tenant_northbound_scenarios as scenario
from shared.cases import case_params

@pytest.mark.parametrize("case", case_params("D3", ["API-158"]))
@pytest.mark.asyncio
async def test_api_158(case, tenant_a_admin, northbound_key, tenant_a_user, tenant_b_user):
    await scenario.execute_d3_tenant_northbound(case, tenant_a_admin, northbound_key, tenant_a_user, tenant_b_user)
