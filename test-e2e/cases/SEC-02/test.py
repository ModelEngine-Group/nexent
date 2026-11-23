"""V5 SEC-02 independently collected scenario."""

import pytest
from d5.scenarios import scenario_security_special as scenario
from shared.cases import special_case_params

@pytest.mark.parametrize("case", special_case_params(["SEC-02"]))
@pytest.mark.asyncio
async def test_sec_02(case, tenant_a_user, tenant_b_user, tenant_a_admin, tenant_b_admin, northbound_key):
    await scenario.execute_d5_security_special(case, tenant_a_user, tenant_b_user, tenant_a_admin, tenant_b_admin, northbound_key)
