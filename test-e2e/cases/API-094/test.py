"""Owned local/external Agent relationship add, duplicate, list, get and remove."""
import pytest
from shared.a2a import discovered_agent, mock_asset
from shared.factories.agent import _draft_agent
from shared.http import assert_status
from shared.asset_registry import register_asset, mark_asset_state


@pytest.mark.stage('D3')
@pytest.mark.case_id('API-094')
async def test_external_sub_agent_relationship(tenant_a_admin):
    async with mock_asset() as mock:
        async with discovered_agent(tenant_a_admin, mock, 'API-094') as (api, external_id, nonce):
            async with _draft_agent(tenant_a_admin, name_prefix='a2a-relation') as (local_id, _):
                pair = {'local_agent_id': local_id, 'external_agent_id': external_id}
                added = await api.post('/a2a/client/relations', json=pair)
                assert_status(added, 200)
                try:
                    register_asset('owned_a2a_relations', str(local_id), pair, owner_case_id='API-094',
                                   cleanup={'service': 'config', 'identity': tenant_a_admin.id, 'method': 'DELETE',
                                            'path': '/a2a/client/relations', 'params': pair, 'allowed_statuses': [200, 404]})
                    assert added.json()['data']['local_agent_id'] == local_id
                    assert added.json()['data']['external_agent_id'] == external_id
                    assert_status(await api.post('/a2a/client/relations', json=pair), 409)
                    for path in ('relations', 'sub-agents'):
                        listed = await api.get(f'/a2a/client/{path}/{local_id}')
                        assert_status(listed, 200)
                        assert [row['external_agent_id'] for row in listed.json()['data']] == [external_id]
                finally:
                    assert_status(await api.delete('/a2a/client/relations', params=pair), (200, 404))
                    mark_asset_state('owned_a2a_relations', str(local_id), 'DELETED')
                for path in ('relations', 'sub-agents'):
                    removed = await api.get(f'/a2a/client/{path}/{local_id}')
                    assert_status(removed, 200)
                    assert removed.json()['data'] == []
                assert_status(await api.delete('/a2a/client/relations', params=pair), 404)
                assert await mock.observations(nonce)
