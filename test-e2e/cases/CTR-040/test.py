"""Both supported transports propagate upstream errors and recover without corrupting selection."""
import pytest
from shared.a2a import discovered_agent, mock_asset
from shared.http import assert_status, response_message


@pytest.mark.stage('D2')
@pytest.mark.case_id('CTR-040')
async def test_protocol_outage_and_recovery(tenant_a_admin):
    async with mock_asset() as mock:
        async with discovered_agent(tenant_a_admin, mock, 'CTR-040') as (api, agent_id, nonce):
            path = f'/a2a/client/agents/{agent_id}'
            for protocol, suffix in [('JSONRPC', '/basic/v1'), ('HTTP+JSON', '/basic/message:send')]:
                assert_status(await api.put(path + '/protocol', json={'protocol_type': protocol}), 200)
                async with mock.fault('server-error'):
                    failed = await api.post(path + '/chat', json={
                        'message': 'Query pedestrian flow', 'metadata': {'test_run': nonce},
                    })
                    assert_status(failed, 400)
                    assert '500' in response_message(failed)
                wire = [row for row in await mock.observations(nonce)
                        if row['scenario'] == 'server-error' and row['path'].endswith(suffix)]
                assert len(wire) == 3, 'transient upstream failures must use the bounded retry contract'
                detail = await api.get(path)
                assert_status(detail, 200)
                assert detail.json()['data']['protocol_type'] == protocol
                recovered = await api.post(path + '/chat', json={
                    'message': 'Query pedestrian flow', 'metadata': {'test_run': nonce},
                })
                assert_status(recovered, 200)
                assert 'total=1283' in recovered.text
