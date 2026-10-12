"""Discover and refresh an owned A2A Agent through Nexent, not the Mock API."""
import pytest
from shared.a2a import discovered_agent, mock_asset
from shared.http import assert_status


@pytest.mark.stage('D3')
@pytest.mark.case_id('CTR-031')
async def test_url_discovery_preserves_custom_headers_on_refresh(tenant_a_admin):
    async with mock_asset() as mock:
        async with discovered_agent(tenant_a_admin, mock, 'CTR-031') as (api, agent_id, nonce):
            detail = await api.get(f'/a2a/client/agents/{agent_id}')
            assert_status(detail, 200)
            row = detail.json()['data']
            assert row['name'] and row['supported_interfaces']
            refreshed = await api.post(f'/a2a/client/agents/{agent_id}/refresh')
            assert_status(refreshed, 200)
            observations = await mock.observations(nonce)
            assert len(observations) >= 2, 'discovery and refresh must both reach the actual wire'
            assert all(item['method'] == 'GET' and item['authenticated'] for item in observations)
