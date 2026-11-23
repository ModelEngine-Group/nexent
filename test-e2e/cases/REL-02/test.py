"""V5 REL-02 independently collected scenario."""

import pytest
from d5.scenarios import scenario_reliability_deployment_special as scenario
from shared.cases import special_case_params

@pytest.mark.parametrize("case", special_case_params(["REL-02"]))
@pytest.mark.asyncio
async def test_rel_02(case, tenant_a_admin, tenant_a_user):
    await scenario.execute_d5_reliability_deployment_special(case, tenant_a_admin, tenant_a_user)
