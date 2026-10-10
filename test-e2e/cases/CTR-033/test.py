"""Failed URL discovery reaches the product deadline and leaves no partial Agent."""
import time
import uuid
import pytest
from shared.a2a import discovered_agent, mock_asset
from shared.http import assert_status, client


@pytest.mark.stage('D3')
@pytest.mark.case_id('CTR-033')
async def test_discovery_timeout_and_recovery(tenant_a_admin):
    async with mock_asset() as mock:
        nonce = 'CTR-033-' + uuid.uuid4().hex
        async with client('config', token=tenant_a_admin.access_token, timeout=1050) as api:
            before = await api.get('/a2a/client/agents')
            assert_status(before, 200)
            ids = {row['id'] for row in before.json()['data']}
            async with mock.fault('invocation-timeout'):
                start = time.monotonic()
                failed = await api.post('/a2a/client/discover/url', json={
                    'url': mock.card_url(nonce), 'custom_headers': {'X-Nexent-Test-Run': nonce},
                })
                elapsed = time.monotonic() - start
            wire = await mock.observations(nonce)
            assert len(wire) == 3 and all(row['scenario'] == 'invocation-timeout' for row in wire)
            assert 850 <= elapsed < 1040, 'observe the product retry deadline, not a test-client timeout'
            assert_status(failed, 400)
            after = await api.get('/a2a/client/agents')
            assert_status(after, 200)
            assert {row['id'] for row in after.json()['data']} == ids
        async with discovered_agent(tenant_a_admin, mock, 'CTR-033') as (api, agent_id, recovery_nonce):
            assert await mock.observations(recovery_nonce)
