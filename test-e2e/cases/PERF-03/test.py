"""V5 PERF-03 independently collected scenario."""

import pytest
from d5.scenarios import scenario_performance_special as scenario
from shared.cases import special_case_params

@pytest.mark.parametrize("case", special_case_params(["PERF-03"]))
@pytest.mark.asyncio
async def test_perf_03(case, tenant_a_user, tenant_a_admin):
    await scenario.execute_d5_performance_special(case, tenant_a_user, tenant_a_admin)
