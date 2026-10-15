"""Exercise the full owned external Agent list/filter/detail/refresh/delete lifecycle."""
import pytest
from shared.a2a import discovered_agent, mock_asset
from shared.http import assert_status


@pytest.mark.stage('D2')
@pytest.mark.case_id('API-092')
async def test_external_agent_lifecycle(tenant_a_admin):
    async with mock_asset() as mock:
        async with discovered_agent(tenant_a_admin, mock, 'API-092') as (api, agent_id, nonce):
            for params in ({}, {'source_type': 'url'}, {'is_available': True}):
                listed = await api.get('/a2a/client/agents', params=params)
                assert_status(listed, 200)
                assert any(int(row.get('id') or row.get('external_agent_id') or 0) == agent_id
                           for row in listed.json()['data'])
            other_source = await api.get('/a2a/client/agents', params={'source_type': 'nacos'})
            assert_status(other_source, 200)
            assert all(int(row.get('id') or row.get('external_agent_id') or 0) != agent_id
                       for row in other_source.json()['data'])
            detail = await api.get(f'/a2a/client/agents/{agent_id}')
            assert_status(detail, 200)
            assert detail.json()['data']['source_type'] == 'url'
            refreshed = await api.post(f'/a2a/client/agents/{agent_id}/refresh')
            assert_status(refreshed, 200)
            assert len(await mock.observations(nonce)) >= 2
