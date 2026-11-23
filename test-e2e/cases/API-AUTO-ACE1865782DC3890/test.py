'''D2 API contract test for external memory provider configuration CRUD.'''

from __future__ import annotations

import json
import uuid

import pytest

from shared.http import assert_status, client, response_message
from shared.resource_ids import absent_numeric_id
from shared.factories.provider import owned_provider_client

API_KEY = 'sk-1234567890abcdef'
MASKED_API_KEY = 'sk-***cdef'


@pytest.mark.asyncio
@pytest.mark.case_id('API-AUTO-ACE1865782DC3890')
@pytest.mark.stage('D2')
async def test_memory_provider_config_crud(tenant_a_admin):
    token = tenant_a_admin.access_token
    run_id = uuid.uuid4().hex[:8]
    provider_name = f'mem-provider-{run_id}'

    async with owned_provider_client(tenant_a_admin) as api:
        plugins_resp = await api.get('/memory/provider-plugins')
        assert_status(plugins_resp, 200)
        plugins = plugins_resp.json()
        assert 'items' in plugins and 'count' in plugins
        names = {p['name'] for p in plugins['items']}
        assert 'mem0' in names
        mem0 = next(p for p in plugins['items'] if p['name'] == 'mem0')
        api_key_schema = next(f for f in mem0['config_schema'] if f['key'] == 'api_key')
        assert api_key_schema['type'] == 'secret'
        assert api_key_schema['required'] is True

        create_resp = await api.post(
            '/memory/providers',
            json={
                'provider_name': provider_name,
                'connection_type': 'plugin',
                'params': {'plugin.name': 'mem0', 'plugin.api_key': API_KEY},
            },
        )
        assert_status(create_resp, 200)
        created = create_resp.json()
        provider_config_id = created['provider_config_id']
        assert created['provider_name'] == provider_name
        assert created['connection_type'] == 'plugin'
        assert created['enabled'] is False
        assert created['timeout_seconds'] == 30
        assert created['params']['plugin.name'] == 'mem0'
        assert created['params']['plugin.api_key'] == MASKED_API_KEY
        assert API_KEY not in json.dumps(created)

        baseline = (await api.get('/memory/providers')).json()['count']
        bad_type = await api.post(
            '/memory/providers',
            json={
                'provider_name': f'mem-badtype-{run_id}',
                'connection_type': 'http',
                'params': {'plugin.name': 'mem0', 'plugin.api_key': API_KEY},
            },
        )
        assert bad_type.status_code in (400, 422)
        assert (await api.get('/memory/providers')).json()['count'] == baseline

        missing_name = await api.post(
            '/memory/providers',
            json={'provider_name': f'mem-noname-{run_id}', 'params': {'plugin.api_key': API_KEY}},
        )
        assert_status(missing_name, 400)
        assert response_message(missing_name) == "params must contain 'plugin.name'"

        unknown = await api.post(
            '/memory/providers',
            json={'provider_name': f'mem-unknown-{run_id}', 'params': {'plugin.name': 'not_installed'}},
        )
        assert_status(unknown, 400)
        assert 'is not installed' in response_message(unknown)

        missing_key = await api.post(
            '/memory/providers',
            json={'provider_name': f'mem-nokey-{run_id}', 'params': {'plugin.name': 'mem0'}},
        )
        assert_status(missing_key, 400)
        assert "Required parameter 'api_key' is missing" in response_message(missing_key)

        dup = await api.post(
            '/memory/providers',
            json={
                'provider_name': provider_name,
                'params': {'plugin.name': 'mem0', 'plugin.api_key': API_KEY},
            },
        )
        assert_status(dup, 400)
        assert 'may already exist' in response_message(dup)
        assert (await api.get('/memory/providers')).json()['count'] == baseline

        list_resp = await api.get('/memory/providers')
        assert_status(list_resp, 200)
        listing = list_resp.json()
        assert 'items' in listing and 'count' in listing
        assert listing['count'] == len(listing['items'])
        matched = [it for it in listing['items'] if it['provider_config_id'] == provider_config_id]
        assert len(matched) == 1
        assert matched[0]['params']['plugin.api_key'] == MASKED_API_KEY
        assert API_KEY not in json.dumps(listing)

        detail_resp = await api.get(f'/memory/providers/{provider_config_id}')
        assert_status(detail_resp, 200)
        detail = detail_resp.json()
        assert detail['provider_config_id'] == provider_config_id
        assert detail['provider_name'] == provider_name
        assert detail['connection_type'] == 'plugin'
        assert detail['params']['plugin.name'] == 'mem0'
        assert detail['params']['plugin.api_key'] == MASKED_API_KEY

        not_found = await api.get(f'/memory/providers/{absent_numeric_id(__name__)}')
        assert_status(not_found, 404)
        assert response_message(not_found) == 'Provider configuration not found'

        update_resp = await api.put(
            f'/memory/providers/{provider_config_id}',
            json={
                'enabled': True,
                'params': {
                    'plugin.name': 'mem0',
                    'plugin.api_key': 'sk-9999999999abcd',
                    'plugin.org_id': 'org-123456',
                },
            },
        )
        assert_status(update_resp, 200)
        updated = update_resp.json()
        assert updated['enabled'] is True
        assert updated['params']['plugin.org_id'] == 'org-123456'
        assert updated['params']['plugin.api_key'] == 'sk-***abcd'
        assert 'sk-***cdef' not in json.dumps(updated)

        update2_resp = await api.put(
            f'/memory/providers/{provider_config_id}',
            json={'params': {'plugin.name': 'mem0', 'plugin.api_key': 'sk-9999999999abcd'}},
        )
        assert_status(update2_resp, 200)
        updated2 = update2_resp.json()
        assert 'plugin.org_id' not in updated2['params']
        assert updated2['params']['plugin.api_key'] == 'sk-***abcd'
        assert updated2['enabled'] is True

        delete_resp = await api.delete(f'/memory/providers/{provider_config_id}')
        assert_status(delete_resp, 200)
        assert delete_resp.json() == {'success': True}

        assert_status(await api.get(f'/memory/providers/{provider_config_id}'), 404)
        listing_after_del = (await api.get('/memory/providers')).json()
        assert all(it['provider_config_id'] != provider_config_id for it in listing_after_del['items'])

        recreate_resp = await api.post(
            '/memory/providers',
            json={
                'provider_name': provider_name,
                'connection_type': 'plugin',
                'params': {'plugin.name': 'mem0', 'plugin.api_key': API_KEY},
            },
        )
        assert_status(recreate_resp, 200)
        recreated = recreate_resp.json()
        assert recreated['provider_name'] == provider_name
        assert recreated['provider_config_id'] != provider_config_id
        assert recreated['params']['plugin.api_key'] == MASKED_API_KEY
        assert 'plugin.org_id' not in recreated['params']

        recreated_id = recreated['provider_config_id']
        cleanup_resp = await api.delete(f'/memory/providers/{recreated_id}')
        assert_status(cleanup_resp, 200)
