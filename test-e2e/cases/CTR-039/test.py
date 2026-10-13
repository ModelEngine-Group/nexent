"""Advertised protocols use real wire; GRPC configuration is saved without wire certification."""
import pytest
from shared.a2a import discovered_agent, mock_asset
from shared.http import assert_status


@pytest.mark.stage('D2')
@pytest.mark.case_id('CTR-039')
async def test_advertised_protocol_switching(tenant_a_admin):
    async with mock_asset() as mock:
        async with discovered_agent(tenant_a_admin, mock, 'CTR-039') as (api, agent_id, nonce):
            path = f'/a2a/client/agents/{agent_id}'
            for protocol, suffix in [('JSONRPC', '/basic/v1'), ('HTTP+JSON', '/basic/message:send')]:
                switched = await api.put(path + '/protocol', json={'protocol_type': protocol})
                assert_status(switched, 200)
                assert switched.json()['data']['protocol_type'] == protocol
                refreshed = await api.post(path + '/refresh')
                assert_status(refreshed, 200)
                detail = await api.get(path)
                assert_status(detail, 200)
                assert detail.json()['data']['protocol_type'] == protocol
                called = await api.post(path + '/chat', json={
                    'message': 'Query pedestrian flow', 'metadata': {'test_run': nonce},
                })
                assert_status(called, 200)
                assert 'total=1283' in called.text
                wire = [row for row in await mock.observations(nonce) if row['method'] == 'POST']
                assert wire[-1]['path'].endswith(suffix)
            # The current API persists GRPC without checking advertised support.
            # Saving this configuration does not prove gRPC wire interoperability.
            configured = await api.put(path + '/protocol', json={'protocol_type': 'GRPC'})
            assert_status(configured, 200)
            assert configured.json()['data']['protocol_type'] == 'GRPC'
            detail = await api.get(path)
            assert_status(detail, 200)
            assert detail.json()['data']['protocol_type'] == 'GRPC'
