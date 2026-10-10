"""Foreign tenant must not attach an owner's local and external Agent IDs."""
import pytest
from shared.a2a import discovered_agent, mock_asset
from shared.factories.agent import _draft_agent
from shared.http import assert_status, client


@pytest.mark.stage('D3')
@pytest.mark.case_id('API-095')
async def test_external_relationship_tenant_boundary(tenant_a_admin, tenant_b_admin):
    assert tenant_a_admin.tenant_id != tenant_b_admin.tenant_id
    async with mock_asset() as mock:
        async with discovered_agent(tenant_a_admin, mock, 'API-095') as (owner, external_id, nonce):
            async with _draft_agent(tenant_a_admin, name_prefix='a2a-isolation') as (local_id, _):
                pair = {'local_agent_id': local_id, 'external_agent_id': external_id}
                async with client('config', token=tenant_b_admin.access_token) as foreign:
                    for path in ('relations', 'sub-agents'):
                        listed = await foreign.get(f'/a2a/client/{path}/{local_id}')
                        assert_status(listed, 200)
                        assert listed.json()['data'] == []
                    try:
                        forbidden = await foreign.post('/a2a/client/relations', json=pair)
                        assert_status(forbidden, (400, 403, 404))
                    finally:
                        # Clean up even if the product incorrectly accepts foreign IDs.
                        assert_status(await foreign.delete('/a2a/client/relations', params=pair), (200, 404))
                for path in ('relations', 'sub-agents'):
                    unchanged = await owner.get(f'/a2a/client/{path}/{local_id}')
                    assert_status(unchanged, 200)
                    assert unchanged.json()['data'] == []
                assert len(await mock.observations(nonce)) == 1
