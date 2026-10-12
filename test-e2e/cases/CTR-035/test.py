"""A real Nacos network timeout is rejected and discovery recovers after fault removal."""
import time
import pytest
from shared.a2a import mock_asset, nacos_config
from shared.http import assert_status


@pytest.mark.stage('D2')
@pytest.mark.case_id('CTR-035')
async def test_nacos_timeout_and_recovery(tenant_a_admin):
    async with mock_asset() as mock:
        async with nacos_config(tenant_a_admin, mock, 'CTR-035', through_proxy=True) as (api, config_id, nonce, discover):
            before = await api.get('/a2a/client/agents')
            assert_status(before, 200)
            ids = {row['id'] for row in before.json()['data']}
            async with mock.nacos_latency(nonce):
                start = time.monotonic()
                failed = await discover()
                elapsed = time.monotonic() - start
                assert_status(failed, 400)
                assert 25 <= elapsed < 85, 'the product must reach its Nacos timeout, not the test client timeout'
            after = await api.get('/a2a/client/agents')
            assert_status(after, 200)
            assert {row['id'] for row in after.json()['data']} == ids
            recovered = await discover()
            assert_status(recovered, 200)
            assert len(recovered.json()['data']) == 1
