"""V5 API-118 independently collected scenario."""

import pytest
from d3.scenarios import scenario_memory_title_automation_scenarios as scenario
from shared.cases import case_params

@pytest.mark.parametrize("case", case_params("D3", ["API-118"]))
@pytest.mark.asyncio
async def test_api_118(case, tenant_a_admin, tenant_a_user):
    await scenario.execute_d3_memory_title_automation(case, tenant_a_admin, tenant_a_user)
