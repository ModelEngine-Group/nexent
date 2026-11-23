"""V5 REL-03 independently collected scenario."""

import pytest
from d5.scenarios import scenario_reliability_deployment_special as scenario
from shared.cases import special_case_params

@pytest.mark.parametrize("case", special_case_params(["REL-03"]))
@pytest.mark.asyncio
async def test_rel_03(case, tenant_a_admin, tenant_a_user):
    await scenario.execute_d5_reliability_deployment_special(case, tenant_a_admin, tenant_a_user)
