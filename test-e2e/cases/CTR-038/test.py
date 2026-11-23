"""Agent Card refresh timeout preserves credentials and selection, then recovers."""
import time
import pytest
from shared.a2a import discovered_agent, mock_asset
from shared.http import assert_status


@pytest.mark.stage('D3')
@pytest.mark.case_id('CTR-038')
async def test_authenticated_refresh_timeout(tenant_a_admin):
    async with mock_asset() as mock:
        auth = await mock.auth_fixture('idkey', 'appkey')
        async with discovered_agent(tenant_a_admin, mock, 'CTR-038', profile='idkey', auth=auth,
                                    timeout=1050) as (api, agent_id, nonce):
            path = f'/a2a/client/agents/{agent_id}'
            assert_status(await api.put(path + '/security-credentials', json={
                'security_credentials': auth['security_credentials'], 'selected_security_requirement_index': 0,
            }), 200)
            async with mock.fault('invocation-timeout'):
                start = time.monotonic()
                failed = await api.post(path + '/refresh')
                elapsed = time.monotonic() - start
            wire = [row for row in await mock.observations(nonce) if row['scenario'] == 'invocation-timeout']
            assert len(wire) == 3 and all(row['authenticated'] for row in wire)
            assert 850 <= elapsed < 1040
            detail = await api.get(path)
            assert_status(detail, 200)
            saved = detail.json()['data']
            assert saved['selected_security_requirement_index'] == 0
            assert set(saved['configured_security_scheme_ids']) == set(auth['security_credentials'])
            assert 'security_credentials' not in saved
            assert_status(await api.post(path + '/refresh'), 200)
            recovered = await api.post(path + '/chat', json={
                'message': 'Query pedestrian flow', 'metadata': {'test_run': nonce},
            })
            assert_status(recovered, 200)
            assert 'total=1283' in recovered.text
            # The current refresh API maps exhausted timeout errors to 500.
            assert_status(failed, 500)
            assert failed.json()['message'] == 'Failed to refresh agent'
