"""Reject unknown, missing and out-of-range Agent Card security choices."""
import pytest
from shared.a2a import discovered_agent, mock_asset
from shared.http import assert_status, client


@pytest.mark.stage('D3')
@pytest.mark.case_id('CTR-037')
async def test_security_requirement_validation_and_isolation(tenant_a_admin, tenant_b_admin):
    async with mock_asset() as mock:
        auth = await mock.auth_fixture('jwt', 'jwt')
        async with discovered_agent(tenant_a_admin, mock, 'CTR-037', profile='jwt', auth=auth) as (api, agent_id, nonce):
            path = f'/a2a/client/agents/{agent_id}/security-credentials'
            for payload in (
                {'security_credentials': {}, 'selected_security_requirement_index': 0},
                {'security_credentials': {'undeclared': 'synthetic-invalid'}},
                {'security_credentials': auth['security_credentials'], 'selected_security_requirement_index': 99},
                {'security_credentials': auth['security_credentials'], 'selected_security_requirement_index': -1},
            ):
                assert_status(await api.put(path, json=payload), (400, 422))
            async with client('config', token=tenant_b_admin.access_token) as foreign:
                assert_status(await foreign.put(path, json={'security_credentials': auth['security_credentials']}), 404)
            detail = await api.get(f'/a2a/client/agents/{agent_id}')
            assert_status(detail, 200)
            assert detail.json()['data']['configured_security_scheme_ids'] == []
            assert 'security_credentials' not in detail.json()['data']
            assert len(await mock.observations(nonce)) == 1
