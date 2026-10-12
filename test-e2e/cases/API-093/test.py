"""Foreign tenant access must not expose, refresh or delete an owned A2A row."""
import pytest
from shared.a2a import discovered_agent, mock_asset
from shared.http import assert_status, client, response_message


@pytest.mark.stage('D2')
@pytest.mark.case_id('API-093')
async def test_external_agent_tenant_isolation(tenant_a_admin, tenant_b_admin):
    assert tenant_a_admin.tenant_id != tenant_b_admin.tenant_id
    async with mock_asset() as mock:
        async with discovered_agent(tenant_a_admin, mock, 'API-093') as (owner, agent_id, nonce):
            async with client('config', token=tenant_b_admin.access_token) as foreign:
                listed = await foreign.get('/a2a/client/agents')
                assert_status(listed, 200)
                assert all(int(row.get('id') or row.get('external_agent_id') or 0) != agent_id
                           for row in listed.json()['data'])
                assert_status(await foreign.get(f'/a2a/client/agents/{agent_id}'), 404)
                refreshed = await foreign.post(f'/a2a/client/agents/{agent_id}/refresh')
                # Refresh wraps an undiscoverable Agent in AgentDiscoveryError
                # (400), while detail/delete expose absence directly (404).
                assert_status(refreshed, 400)
                assert 'not found' in response_message(refreshed).lower()
                assert_status(await foreign.delete(f'/a2a/client/agents/{agent_id}'), 404)
            assert_status(await owner.get(f'/a2a/client/agents/{agent_id}'), 200)
            assert len(await mock.observations(nonce)) == 1, 'foreign refresh must not reach the upstream'
