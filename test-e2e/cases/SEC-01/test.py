"""V5 SEC-01 independently collected scenario."""

import pytest
from d5.scenarios import scenario_security_special as scenario
from shared.cases import special_case_params

@pytest.mark.parametrize("case", special_case_params(["SEC-01"]))
@pytest.mark.asyncio
async def test_sec_01(case, tenant_a_user, tenant_b_user, tenant_a_admin, tenant_b_admin, northbound_key):
    await scenario.execute_d5_security_special(case, tenant_a_user, tenant_b_user, tenant_a_admin, tenant_b_admin, northbound_key)
