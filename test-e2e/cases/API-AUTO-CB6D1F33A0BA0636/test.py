from __future__ import annotations

import json
import uuid

import pytest

from shared.http import assert_status, client, response_message
from shared.asset_registry import register_asset
from shared.factories.tags import register_tag_definition

CASE_ID = 'API-AUTO-CB6D1F33A0BA0636'
TAG_A = 'tag-a'
TAG_B = 'tag-b'


async def _create_skill(api, name, tags):
    # A fresh name prevents soft-deleted Skills from earlier batches from
    # colliding with this case's independently owned resources.
    name = f'{name}-{uuid.uuid4().hex[:8]}'
    # Current product contract is the plural /skills resource.  /skill was an
    # obsolete generated path and made this case fail before exercising tags.
    resp = await api.post('/skills', json={'name': name, 'description': name, 'content': name, 'tags': tags})
    assert_status(resp, (200, 201))
    payload = resp.json()
    body = payload.get('data') if isinstance(payload, dict) else None
    body = body if isinstance(body, dict) else payload
    skill_id = body.get('skill_id') or body.get('id')
    assert skill_id is not None, payload
    register_asset('owned_skills', name, name, owner_case_id=CASE_ID, cleanup={
        'service': 'config', 'identity': 'tenant_a_admin', 'method': 'DELETE',
        'path': f'/skills/{name}', 'allowed_statuses': [200, 404],
    })
    return int(skill_id)


async def _create_listing(api, skill_id, tags):
    resp = await api.post(f'/repository/skill/{skill_id}', json={'tags': tags})
    assert_status(resp, 200)
    payload = resp.json()
    body = payload.get('data') if isinstance(payload, dict) else None
    body = body if isinstance(body, dict) else payload
    rid = body.get('skill_repository_id') or body.get('id')
    assert rid is not None, payload
    register_asset('owned_skill_listings', str(rid), int(rid), owner_case_id=CASE_ID, cleanup={
        'service': 'config', 'identity': 'tenant_a_admin', 'method': 'PATCH',
        'path': f'/repository/skill/{rid}/status', 'json': {'status': 'not_shared'},
        'allowed_statuses': [200, 404],
    })
    return int(rid)


async def _assign_tags(api, skill_id, value_ids):
    resp = await api.put(f'/tag-libraries/assignments/skill/{skill_id}', json={'value_ids': value_ids})
    assert_status(resp, 200)


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D2')
@pytest.mark.asyncio
async def test_tag_filter_and_tag_predicates(tenant_a_admin, tenant_b_admin, tag_asset_guard):
    async with client('config', token=tenant_a_admin.access_token) as api:
        libs = await api.get('/tag-libraries')
        assert_status(libs, 200)
        bucket = next(b for b in libs.json() if 'skill' in (b.get('resource_types') or []))
        bucket_id = bucket['bucket_id']

        created = await api.post(
            f'/tag-libraries/{bucket_id}/definitions',
            json={'definition_name': f'repo-tags-{CASE_ID}-{uuid.uuid4().hex[:8]}', 'selection_mode': 'multi_select', 'initial_values': [TAG_A, TAG_B]},
        )
        assert_status(created, 200)
        definition = created.json()
        definition_id = definition['definition_id']
        register_tag_definition(tenant_a_admin, bucket_id, definition)
        value_ids = {v['display_value']: v['value_id'] for v in definition['values']}
        id_a = value_ids[TAG_A]
        id_b = value_ids[TAG_B]

        s1 = await _create_skill(api, f'repo-s1-{CASE_ID}', [TAG_A])
        s2 = await _create_skill(api, f'repo-s2-{CASE_ID}', [TAG_B])
        s3 = await _create_skill(api, f'repo-s3-{CASE_ID}', [TAG_A, TAG_B])
        await _assign_tags(api, s1, [id_a])
        await _assign_tags(api, s2, [id_b])
        await _assign_tags(api, s3, [id_a, id_b])

        await _create_listing(api, s1, [TAG_A])
        await _create_listing(api, s2, [TAG_B])
        await _create_listing(api, s3, [TAG_A, TAG_B])

        resp = await api.get('/repository/skill', params={'tag': TAG_A})
        assert_status(resp, 200)
        payload = resp.json()
        assert 'items' in payload and 'pagination' in payload
        hit_ids = {item['skill_id'] for item in payload['items']}
        assert all(TAG_A in item['tags'] for item in payload['items'])
        assert {s1, s3} <= hit_ids

        resp = await api.get('/repository/skill', params={'tag': 'not-exist'})
        assert_status(resp, 200)
        payload = resp.json()
        miss_ids = {item['skill_id'] for item in payload['items']}
        assert not ({s1, s2, s3} & miss_ids)

        predicate = json.dumps([{'definition_id': definition_id, 'value_ids': [id_a]}])
        resp = await api.get('/repository/skill', params={'tag_predicates': predicate})
        assert_status(resp, 200)
        payload = resp.json()
        assert {item['skill_id'] for item in payload['items']} == {s1, s3}

        resp = await api.get('/repository/skill', params={'tag_predicates': '{invalid'})
        assert resp.status_code == 400
        assert response_message(resp) == 'tag_predicates must be valid JSON'

        resp = await api.get('/repository/skill', params={'tag_predicates': json.dumps({'a': 1})})
        assert resp.status_code == 400
        assert response_message(resp) == 'tag_predicates must be a list'

        resp = await api.get('/repository/skill/mine', params={'tag_predicates': predicate})
        assert_status(resp, 200)
        payload = resp.json()
        assert 'items' in payload and 'counts' in payload and 'pagination' in payload
        assert {item.get('skill_id') for item in payload['items']} == {s1, s3}
        assert payload['counts']['all'] == 2

        resp = await api.get('/repository/skill/mine', params={'tag_predicates': '{invalid'})
        assert resp.status_code == 400

    async with client('config', token=tenant_b_admin.access_token) as api:
        tenant_a_ids = {s1, s2, s3}
        resp = await api.get('/repository/skill')
        assert_status(resp, 200)
        assert not (tenant_a_ids & {item['skill_id'] for item in resp.json()['items']})

        resp = await api.get('/repository/skill', params={'tag': TAG_A})
        assert_status(resp, 200)
        assert not (tenant_a_ids & {item['skill_id'] for item in resp.json()['items']})

        resp = await api.get('/repository/skill/mine')
        assert_status(resp, 200)
        assert not (tenant_a_ids & {item.get('skill_id') for item in resp.json()['items']})
