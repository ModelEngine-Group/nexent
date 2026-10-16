"""V5 AGT-043 independently collected scenario."""

import pytest
from d3.scenarios import scenario_knowledge_file_retrieval_scenarios as scenario
from shared.cases import case_params

@pytest.mark.parametrize("case", case_params("D3", ["AGT-043"]))
@pytest.mark.asyncio
async def test_agt_043(case, tenant_a_admin, tenant_a_user):
    await scenario.execute_d3_knowledge_file_retrieval(case, tenant_a_admin, tenant_a_user)
