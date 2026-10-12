"""Rejected metadata stays local; invalid persisted credentials fail on the wire."""
import pytest
from shared.a2a import SecretMapping, discovered_agent, mock_asset
from shared.http import assert_status, response_message


@pytest.mark.stage('D2')
@pytest.mark.case_id('CTR-042')
async def test_invalid_authentication_and_metadata(tenant_a_admin):
    async with mock_asset() as mock:
        auth = await mock.auth_fixture('jwt', 'jwt')
        async with discovered_agent(tenant_a_admin, mock, 'CTR-042', profile='jwt', auth=auth) as (api, agent_id, nonce):
            credentials = SecretMapping(auth['security_credentials'])
            credentials['hwBearerJwt'] = credentials['hwBearerJwt'] + '.invalid'
            assert_status(await api.put(f'/a2a/client/agents/{agent_id}/security-credentials', json={
                'security_credentials': credentials, 'selected_security_requirement_index': 0,
            }), 200)
            rejected = await api.post(f'/a2a/client/agents/{agent_id}/chat', json={
                'message': 'Query pedestrian flow', 'metadata': {'test_run': nonce},
            })
            assert_status(rejected, 400)
            assert '401' in response_message(rejected)
            wire = [row for row in await mock.observations(nonce) if row['method'] == 'POST']
            assert len(wire) == 1 and not wire[0]['authenticated']
            invalid = await api.post(f'/a2a/client/agents/{agent_id}/chat', json={
                'message': 'Query pedestrian flow', 'metadata': ['not-an-object'],
            })
            assert_status(invalid, 422)
            assert len([row for row in await mock.observations(nonce) if row['method'] == 'POST']) == 1
