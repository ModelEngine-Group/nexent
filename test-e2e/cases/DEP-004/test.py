"""V5 DEP-004 independently collected scenario."""

import pytest
from d5.scenarios import scenario_security_reliability_deployment as scenario
from shared.cases import case_params

@pytest.mark.parametrize("case", case_params("D5", ["DEP-004"]))
@pytest.mark.asyncio
async def test_dep_004(case, tenant_a_admin, tenant_a_user, tenant_b_user):
    await scenario.execute_d5_main(case, tenant_a_admin, tenant_a_user, tenant_b_user)
