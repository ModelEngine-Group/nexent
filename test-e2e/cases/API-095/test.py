"""Reject foreign parents and mixed-tenant child bindings through both write APIs."""
from contextlib import AsyncExitStack

import pytest
from shared.a2a import discovered_agent, mock_asset
from shared.factories.agent import _draft_agent
from shared.factories.model import owned_configured_model
from shared.http import assert_status


@pytest.mark.stage('D3')
@pytest.mark.case_id('API-095')
async def test_external_relationship_tenant_boundary(tenant_a_admin, tenant_b_admin):
    assert tenant_a_admin.tenant_id != tenant_b_admin.tenant_id
    async with AsyncExitStack() as stack:
        mock = await stack.enter_async_context(mock_asset())
        owner_a, external_a, nonce_a = await stack.enter_async_context(
            discovered_agent(tenant_a_admin, mock, 'API-095-A'))
        owner_b, external_b, nonce_b = await stack.enter_async_context(
            discovered_agent(tenant_b_admin, mock, 'API-095-B'))
        model_a = await stack.enter_async_context(owned_configured_model(tenant_a_admin, 'API-095'))
        model_b = await stack.enter_async_context(owned_configured_model(tenant_b_admin, 'API-095'))
        local_a, payload_a = await stack.enter_async_context(
            _draft_agent(tenant_a_admin, name_prefix='a2a-isolation-a',
                         owner_case_id='API-095', model_ids=[model_a]))
        local_b, payload_b = await stack.enter_async_context(
            _draft_agent(tenant_b_admin, name_prefix='a2a-isolation-b',
                         owner_case_id='API-095', model_ids=[model_b]))

        for path in ('relations', 'sub-agents'):
            listed = await owner_b.get(f'/a2a/client/{path}/{local_a}')
            assert_status(listed, 200)
            assert listed.json()['data'] == []

        for local_id, external_id in (
            (local_a, external_a), (local_b, external_a), (local_a, external_b),
        ):
            pair = {'local_agent_id': local_id, 'external_agent_id': external_id}
            try:
                forbidden = await owner_b.post('/a2a/client/relations', json=pair)
                assert_status(forbidden, (400, 403, 404))
                forbidden_update = await owner_b.post('/agent/update', json={
                    'agent_id': local_id,
                    'name': 'forbidden_cross_tenant_update',
                    'related_external_agent_ids': [external_id],
                })
                assert_status(forbidden_update, (400, 403, 404))
            finally:
                # Clean any incorrectly accepted binding before releasing its resources.
                assert_status(await owner_b.delete('/a2a/client/relations', params=pair), (200, 404))

        for api, local_id, payload in (
            (owner_a, local_a, payload_a), (owner_b, local_b, payload_b),
        ):
            for path in ('relations', 'sub-agents'):
                unchanged = await api.get(f'/a2a/client/{path}/{local_id}')
                assert_status(unchanged, 200)
                assert unchanged.json()['data'] == []
            unchanged_agent = await api.post('/agent/search_info', json={'agent_id': local_id})
            assert_status(unchanged_agent, 200)
            assert unchanged_agent.json()['name'] == payload['name']
        assert len(await mock.observations(nonce_a)) == 1
        assert len(await mock.observations(nonce_b)) == 1
