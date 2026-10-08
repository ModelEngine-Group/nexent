"""V5 PERF-06 independently collected scenario."""

import pytest
from d5.scenarios import scenario_performance_special as scenario
from shared.cases import special_case_params

@pytest.mark.parametrize("case", special_case_params(["PERF-06"]))
@pytest.mark.asyncio
async def test_perf_06(case, tenant_a_admin):
    # Evaluation preparation and report reads only use the administrator.
    await scenario.execute_d5_performance_special(case, None, tenant_a_admin)
