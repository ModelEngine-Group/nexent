"""V5 API-051 independently collected scenario."""

import pytest
from d3.scenarios import scenario_model_multimodal_scenarios as scenario
from shared.cases import case_params

@pytest.mark.parametrize("case", case_params("D3", ["API-051"]))
@pytest.mark.asyncio
async def test_api_051(case, tenant_a_admin, tenant_a_user):
    await scenario.execute_model_and_multimodal_scenario(case, tenant_a_admin, tenant_a_user)
