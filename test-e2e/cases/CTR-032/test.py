"""Invalid Agent Cards and missing discovery authentication cannot create records."""
import uuid
import pytest
from shared.a2a import mock_asset
from shared.http import assert_status, client


@pytest.mark.stage('D3')
@pytest.mark.case_id('CTR-032')
async def test_discovery_failure_does_not_persist(tenant_a_admin):
    async with mock_asset() as mock:
        async with client('config', token=tenant_a_admin.access_token) as api:
            before = await api.get('/a2a/client/agents')
            assert_status(before, 200)
            ids = {row['id'] for row in before.json()['data']}
            nonce = 'CTR-032-' + uuid.uuid4().hex
            missing = await api.post('/a2a/client/discover/url', json={
                'url': mock.card_url(nonce, 'idkey'), 'custom_headers': {'X-Nexent-Test-Run': nonce},
            })
            assert_status(missing, 400)
            rows = await mock.observations(nonce)
            assert rows and not any(row['authenticated'] for row in rows)
            async with mock.fault('malformed-card'):
                broken = await api.post('/a2a/client/discover/url', json={
                    'url': mock.card_url(nonce), 'custom_headers': {'X-Nexent-Test-Run': nonce},
                })
                assert_status(broken, 400)
            after = await api.get('/a2a/client/agents')
            assert_status(after, 200)
            assert {row['id'] for row in after.json()['data']} == ids
