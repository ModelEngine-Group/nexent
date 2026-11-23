# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Repository filters against owned, tenant-scoped Agent/tag fixtures."""
from __future__ import annotations

import json
import math
import uuid
from contextlib import AsyncExitStack, asynccontextmanager

import pytest

from shared.asset_registry import mark_asset_state, register_asset
from shared.factories.agent import _draft_agent
from shared.http import assert_status, client, response_message

CASE_ID = 'API-AUTO-D6C1BBC6199D63C0'
JSON_ERROR = 'tag_predicates must be valid JSON'
LIST_ERROR = 'tag_predicates must be a list'


def _enc(predicates):
    return json.dumps(predicates, separators=(',', ':'))


async def _all(api, path, **params):
    out = []
    page = 1
    while True:
        resp = await api.get(path, params={'page': page, 'page_size': 100, **params})
        assert_status(resp, 200)
        payload = resp.json()
        items = payload['items']
        out.extend(items)
        if not items or len(out) >= int(payload['pagination']['total']):
            return out
        page += 1


def _ids(items):
    return {int(item['agent_id']) for item in items if item.get('agent_id') is not None}


@asynccontextmanager
async def _owned_repository(identity):
    """Journal each owned write and clean only this fixture's resources."""
    token = uuid.uuid4().hex[:8]
    tags = [f'Filter{token}A', f'Filter{token}B']
    definitions = []
    async with client('config', token=identity.access_token) as api:
        response = await api.get('/tag-libraries')
        assert_status(response, 200)
        bucket = next(row for row in response.json() if row['bucket_key'] == 'default_resource')['bucket_id']
        try:
            for index in range(2):
                response = await api.post(f'/tag-libraries/{bucket}/definitions', json={
                    'definition_name': f'{CASE_ID}-{token}-{index}',
                    'selection_mode': 'single_select', 'initial_values': [f'value-{token}-{index}'],
                })
                assert_status(response, 200)
                definition = response.json()
                definitions.append(definition)
                did = definition['definition_id']
                for section, resource_id, path in [
                    ('tag_definitions', did, f'/tag-libraries/{bucket}/definitions/{did}'),
                    *[('tag_values', value['value_id'],
                       f'/tag-libraries/{bucket}/definitions/{did}/values/{value["value_id"]}')
                      for value in definition['values']],
                ]:
                    register_asset(section, str(resource_id), resource_id, owner_case_id=CASE_ID,
                                   cleanup={'service': 'config', 'identity': identity.id, 'method': 'DELETE',
                                            'path': path, 'allowed_statuses': [200, 404]})
            async with AsyncExitStack() as stack:
                agents, listings = [], []
                try:
                    for index, value_indices in enumerate(([0], [1], [0, 1])):
                        agent_id, payload = await stack.enter_async_context(
                            _draft_agent(identity, name_prefix=f'filter-{token}-{index}', model_ids=[]))
                        agents.append(agent_id)
                        value_ids = [definitions[i]['values'][0]['value_id'] for i in value_indices]
                        assigned = await api.put(f'/tag-libraries/assignments/agent/{agent_id}', json={'value_ids': value_ids})
                        assert_status(assigned, 200)
                        readback = await api.get(f'/tag-libraries/assignments/agent/{agent_id}')
                        assert_status(readback, 200)
                        assert {row['value_id'] for row in readback.json()['assignments']} == set(value_ids)
                        published = await api.post(f'/agent/{agent_id}/publish', json={
                            'version_name': f'filter-{token}', 'release_note': 'Owned filter fixture'})
                        assert_status(published, 200)
                        created = await api.post(
                            f'/repository/agent/{agent_id}/versions/{published.json()["version_no"]}',
                            json={'icon': 'automation-agent', 'tags': [tags[i] for i in value_indices],
                                  'content': payload['name']})
                        assert_status(created, 200)
                        listing_id = created.json()['agent_repository_id']
                        listings.append(listing_id)
                        register_asset('owned_agent_listings', str(listing_id), listing_id, owner_case_id=CASE_ID,
                                       cleanup={'service': 'config', 'identity': identity.id, 'method': 'PATCH',
                                                'path': f'/repository/agent/{listing_id}/status',
                                                'json': {'status': 'not_shared'}, 'allowed_statuses': [200, 404]})
                        reviewed = await api.patch(f'/repository/agent/{listing_id}/status', json={'status': 'shared'})
                        assert_status(reviewed, 200)
                    # Listing search uses the user-visible display name, not
                    # the separately normalized internal Agent identifier.
                    yield api, agents, listings, tags, definitions, payload['display_name']
                finally:
                    # Withdraw before Agent cleanup removes its assignments.
                    for listing_id in listings:
                        withdrawn = await api.patch(f'/repository/agent/{listing_id}/status', json={'status': 'not_shared'})
                        assert_status(withdrawn, (200, 404))
                        mark_asset_state('owned_agent_listings', str(listing_id), 'DELETED')
        finally:
            for definition in reversed(definitions):
                did = definition['definition_id']
                for value in definition['values']:
                    vid = value['value_id']
                    removed = await api.delete(f'/tag-libraries/{bucket}/definitions/{did}/values/{vid}')
                    assert_status(removed, (200, 404))
                    mark_asset_state('tag_values', str(vid), 'DELETED')
                removed = await api.delete(f'/tag-libraries/{bucket}/definitions/{did}')
                assert_status(removed, (200, 404))
                mark_asset_state('tag_definitions', str(did), 'DELETED')


@pytest.mark.stage('D2')
@pytest.mark.case_id(CASE_ID)
@pytest.mark.asyncio
async def test_api_auto_d6c1bbc6199d63c0(tenant_a_admin, tenant_a_user, tenant_b_admin, tenant_b_user):
    async with client('config', token=tenant_a_user.access_token) as api:
        response = await api.get('/repository/agent', params={'status': 'shared', 'page': 1, 'page_size': 10})
        assert_status(response, 200)
        payload = response.json()
        assert isinstance(payload['items'], list)
        pagination = payload['pagination']
        assert pagination['total_pages'] == math.ceil(pagination['total'] / pagination['page_size'])
        for item in payload['items']:
            assert {'agent_repository_id', 'agent_id', 'tags'} <= item.keys()
            assert isinstance(item['tags'], list)
        for path in ('/repository/agent', '/repository/agent/mine'):
            for param in ('tag_predicates', 'search_tag_predicates'):
                for invalid, detail in [('not-json', JSON_ERROR), (json.dumps({'a': 1}), LIST_ERROR)]:
                    response = await api.get(path, params={param: invalid})
                    assert_status(response, 400)
                    assert response_message(response) == detail
    for credential in (None, 'invalid-token-value'):
        async with client('config', token=credential) as api:
            for path in ('/repository/agent', '/repository/agent/mine'):
                assert_status(await api.get(path), 401)

    async with _owned_repository(tenant_a_admin) as (api, agents, listings, tags, definitions, search):
        predicates = [{'definition_id': d['definition_id'], 'value_ids': [d['values'][0]['value_id']]}
                      for d in definitions]
        assert _ids(await _all(api, '/repository/agent', status='shared', tag_predicates=_enc(predicates))) == {agents[2]}
        # Text hits only the last fixture; OR predicates must add the other two.
        assert _ids(await _all(api, '/repository/agent', status='shared', search=search,
                              search_tag_predicates=_enc(predicates))) == set(agents)
        assert _ids(await _all(api, '/repository/agent', status='shared', search=search)) == {agents[2]}
        assert _ids(await _all(api, '/repository/agent', status='shared', tag=tags[0])) == {agents[0], agents[2]}
        for wrong in (tags[0][:-1], tags[0].lower()):
            assert _ids(await _all(api, '/repository/agent', status='shared', tag=wrong)) == set()
        mine = await _all(api, '/repository/agent/mine', new_agent_padding='true', tag_predicates=_enc(predicates))
        assert _ids(mine) == {agents[2]}
        assert not any(item.get('new_agent_padding') is True for item in mine)
        # Public official Agents can legitimately appear in both tenants.
        # Cross-tenant denial is asserted against owned IDs only.
        for identity in (tenant_b_admin, tenant_b_user):
            async with client('config', token=identity.access_token) as other:
                assert not _ids(await _all(other, '/repository/agent', status='shared')).intersection(agents)
                assert not _ids(await _all(other, '/repository/agent/mine')).intersection(agents)
                for listing_id, agent_id in zip(listings, agents):
                    assert_status(await other.get(f'/repository/agent/{listing_id}'), 404)
                    assert_status(await other.get(f'/tag-libraries/assignments/agent/{agent_id}'), 404)
