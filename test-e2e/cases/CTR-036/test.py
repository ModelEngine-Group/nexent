"""Agent Card requirements are persisted and credentials reach the actual wire."""
import pytest
from shared.a2a import discovered_agent, mock_asset
from shared.http import assert_status


@pytest.mark.stage('D3')
@pytest.mark.case_id('CTR-036')
async def test_security_requirements_and_selected_index(tenant_a_admin):
    async with mock_asset() as mock:
        auth = await mock.auth_fixture('jwt', 'jwt')
        async with discovered_agent(tenant_a_admin, mock, 'CTR-036', profile='jwt', auth=auth) as (api, agent_id, nonce):
            configured = await api.put(f'/a2a/client/agents/{agent_id}/security-credentials', json={
                'security_credentials': auth['security_credentials'],
                'selected_security_requirement_index': auth['requirement_index'],
            })
            assert_status(configured, 200)
            assert set(configured.json()['data']['configured_security_scheme_ids']) == set(auth['security_credentials'])
            detail = await api.get(f'/a2a/client/agents/{agent_id}')
            assert_status(detail, 200)
            saved = detail.json()['data']
            assert saved['selected_security_requirement_index'] == auth['requirement_index']
            assert 'security_credentials' not in saved, 'detail must not expose credential values'
            assert saved['security_requirements'] and saved['security_schemes']
            refreshed = await api.post(f'/a2a/client/agents/{agent_id}/refresh')
            assert_status(refreshed, 200)
            called = await api.post(f'/a2a/client/agents/{agent_id}/chat', json={
                'message': 'Query pedestrian flow', 'metadata': {'test_run': nonce},
            })
            assert_status(called, 200)
            assert 'total=1283' in called.text
            observations = await mock.observations(nonce)
            assert any(row['method'] == 'POST' and row['authenticated'] for row in observations)
            assert sum(row['method'] == 'GET' and row['authenticated'] for row in observations) >= 2
