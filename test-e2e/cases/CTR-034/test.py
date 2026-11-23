"""Owned Nacos configuration CRUD, activation and real registered Agent discovery."""
import pytest
from shared.a2a import mock_asset, nacos_config
from shared.http import assert_status


@pytest.mark.stage('D2')
@pytest.mark.case_id('CTR-034')
async def test_nacos_configuration_lifecycle(tenant_a_admin):
    async with mock_asset() as mock:
        async with nacos_config(tenant_a_admin, mock, 'CTR-034') as (api, config_id, nonce, discover):
            path = f'/a2a/client/nacos-configs/{config_id}'
            detail = await api.get(path)
            assert_status(detail, 200)
            assert detail.json()['data']['name'] == nonce
            assert_status(await api.put(path, json={'name': nonce + '-updated', 'is_active': False}), 200)
            listed = await api.get('/a2a/client/nacos-configs', params={'is_active': False})
            assert_status(listed, 200)
            assert any(row['config_id'] == config_id for row in listed.json()['data'])
            assert_status(await discover(), 400)
            assert_status(await api.put(path, json={'is_active': True}), 200)
            active = await api.get('/a2a/client/nacos-configs', params={'is_active': True})
            assert_status(active, 200)
            assert any(row['config_id'] == config_id for row in active.json()['data'])
            discovered = await discover()
            assert_status(discovered, 200)
            rows = discovered.json()['data']
            assert len(rows) == 1 and rows[0]['source_type'] == 'nacos'
            second = await discover()
            assert_status(second, 200)
            assert second.json()['data'][0]['id'] == rows[0]['id'], 'same config/name must not create duplicate Agents'
