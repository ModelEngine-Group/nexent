"""Authenticated invocation timeout has bounded retries and keeps metadata intact."""
import time
import pytest
from shared.a2a import discovered_agent, mock_asset
from shared.http import assert_status


@pytest.mark.stage('D2')
@pytest.mark.case_id('CTR-043')
async def test_wire_timeout_and_recovery(tenant_a_admin):
    async with mock_asset() as mock:
        auth = await mock.auth_fixture('idkey', 'appkey')
        async with discovered_agent(tenant_a_admin, mock, 'CTR-043', profile='idkey', auth=auth,
                                    timeout=1050) as (api, agent_id, nonce):
            path = f'/a2a/client/agents/{agent_id}'
            assert_status(await api.put(path + '/security-credentials', json={
                'security_credentials': auth['security_credentials'], 'selected_security_requirement_index': 0,
            }), 200)
            message = {'message': 'Query pedestrian flow', 'metadata': {'test_run': nonce}}
            async with mock.fault('invocation-timeout'):
                start = time.monotonic()
                failed = await api.post(path + '/chat', json=message)
                elapsed = time.monotonic() - start
            wire = [row for row in await mock.observations(nonce)
                    if row['method'] == 'POST' and row['scenario'] == 'invocation-timeout']
            assert len(wire) == 3 and all(row['authenticated'] for row in wire)
            assert len({row['payload_summary']['metadata_sha256'] for row in wire}) == 1
            assert 850 <= elapsed < 1040
            recovered = await api.post(path + '/chat', json=message)
            assert_status(recovered, 200)
            assert 'total=1283' in recovered.text
            # Compatibility contract: exhausted TimeoutError reaches the generic
            # HTTP error handler. This does not prescribe all A2A errors as 500.
            assert_status(failed, 500)
            assert failed.json()['message'] == 'Failed to chat with external agent'
