"""V5 REL-002 independently collected scenario."""

import pytest
from d5.scenarios import scenario_security_reliability_deployment as scenario
from shared.cases import case_params

@pytest.mark.parametrize("case", case_params("D5", ["REL-002"]))
@pytest.mark.asyncio
async def test_rel_002(case, tenant_a_admin, tenant_a_user, tenant_b_user):
    await scenario.execute_d5_main(case, tenant_a_admin, tenant_a_user, tenant_b_user)
