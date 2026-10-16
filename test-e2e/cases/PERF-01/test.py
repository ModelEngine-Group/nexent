"""V5 PERF-01 independently collected scenario."""

import pytest
from d5.scenarios import scenario_performance_special as scenario
from shared.cases import special_case_params

@pytest.mark.parametrize("case", special_case_params(["PERF-01"]))
@pytest.mark.asyncio
async def test_perf_01(case, tenant_a_user, tenant_a_admin):
    await scenario.execute_d5_performance_special(case, tenant_a_user, tenant_a_admin)
