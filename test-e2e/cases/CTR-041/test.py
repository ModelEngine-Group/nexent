"""Verify idkey/JWT/alternative credentials and metadata over real A2A transport."""
import hashlib
import json
import pytest
from shared.a2a import discovered_agent, mock_asset
from shared.http import assert_status


async def _check_authentication_wire(tenant_a_admin, profile, mode):
    async with mock_asset() as mock:
        auth = await mock.auth_fixture(profile, mode)
        async with discovered_agent(tenant_a_admin, mock, 'CTR-041', profile=profile, auth=auth) as (api, agent_id, nonce):
            assert_status(await api.put(f'/a2a/client/agents/{agent_id}/security-credentials', json={
                'security_credentials': auth['security_credentials'],
                'selected_security_requirement_index': auth['requirement_index'],
            }), 200)
            called = await api.post(f'/a2a/client/agents/{agent_id}/chat', json={
                'message': 'Query pedestrian flow', 'metadata': {'test_run': nonce},
            })
            assert_status(called, 200)
            assert 'total=1283' in called.text
            wire = [row for row in await mock.observations(nonce) if row['method'] == 'POST']
            assert len(wire) == 1 and wire[0]['authenticated']
            expected = hashlib.sha256(json.dumps({'test_run': nonce}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            assert wire[0]['payload_summary']['metadata_sha256'] == expected
            for header in ('authorization', 'x-hw-appkey'):
                if header in auth['header_fingerprints']:
                    assert wire[0]['headers'][header]['sha256'] == auth['header_fingerprints'][header]


@pytest.mark.stage('D2')
@pytest.mark.case_id('CTR-041')
async def test_authentication_and_metadata_wire(tenant_a_admin):
    for profile, mode in [('idkey', 'appkey'), ('jwt', 'jwt'), ('both', 'appkey'), ('both', 'jwt')]:
        await _check_authentication_wire(tenant_a_admin, profile, mode)
