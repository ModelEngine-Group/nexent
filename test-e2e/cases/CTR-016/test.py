"""V5 CTR-016 independently collected scenario."""

import pytest
from d3.scenarios import scenario_model_multimodal_scenarios as scenario
from shared.cases import case_params

@pytest.mark.parametrize("case", case_params("D3", ["CTR-016"]))
@pytest.mark.asyncio
async def test_ctr_016(case, tenant_a_admin, tenant_a_user):
    await scenario.execute_model_and_multimodal_scenario(case, tenant_a_admin, tenant_a_user)
