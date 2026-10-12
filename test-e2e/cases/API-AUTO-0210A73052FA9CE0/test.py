import os
import uuid

import pytest

from shared.http import assert_status, client
from shared.factories.ownership import register_owned_http
from shared.asset_registry import mark_asset_state

_CASE_ID = 'API-AUTO-0210A73052FA9CE0'
_AIDP = '/aidp-mgmt'


def _run_id():
    return os.environ.get('RUN_ID') or uuid.uuid4().hex[:12]


def _kb_name(prefix):
    return f'{prefix}-{_CASE_ID.lower()}-{_run_id()}-{uuid.uuid4().hex[:8]}'


def _multimodal_matches_caption(item):
    caption = item.get('caption_enable')
    return item.get('is_multimodal') == (caption in (1, '1', True))


async def _create_private_kb(identity, name):
    async with client('config', token=identity.access_token) as api:
        response = await api.post(
            f'{_AIDP}/knowledge-bases',
            json={'name': name, 'description': name, 'ingroup_permission': 'PRIVATE'},
        )
    assert_status(response, 200)
    payload = response.json()
    kds_id = payload.get('kds_id') or payload.get('id')
    assert kds_id, f'create returned no kds_id: {payload!r}'
    register_owned_http(identity, 'owned_aidp_knowledge_bases', str(kds_id),
                        f'{_AIDP}/knowledge-bases/{kds_id}')
    return str(kds_id)


async def _delete_kb(identity, kds_id):
    async with client('config', token=identity.access_token) as api:
        response = await api.delete(f'{_AIDP}/knowledge-bases/{kds_id}')
    assert_status(response, (200, 404))
    mark_asset_state('owned_aidp_knowledge_bases', str(kds_id), 'DELETED')


async def _list(api, page, page_size):
    response = await api.get(
        f'{_AIDP}/knowledge-bases', params={'page': page, 'page_size': page_size}
    )
    assert_status(response, 200)
    return response.json()


async def _collect_all(api, page_size=100):
    ids = []
    total = None
    page = 1
    while True:
        body = await _list(api, page, page_size)
        for key in ('value', 'total_count', 'has_more', 'total_reliable'):
            assert key in body, f'list response missing {key}'
        if total is None:
            total = body['total_count']
        assert body['total_count'] == total
        assert body['total_reliable'] is True
        assert body['has_more'] == (page * page_size < total)
        value = body['value']
        assert isinstance(value, list)
        assert len(value) <= page_size
        for item in value:
            assert isinstance(item.get('kds_id'), str)
            assert item.get('resource_status') in {'ACTIVE', 'UNAVAILABLE'}
            assert isinstance(item.get('is_multimodal'), bool)
            assert _multimodal_matches_caption(item)
            ids.append(item['kds_id'])
        if not body['has_more']:
            break
        page += 1
    return ids, total


@pytest.mark.stage('D2')
@pytest.mark.case_id('API-AUTO-0210A73052FA9CE0')
async def test_aidp_kb_list_count_intersection_pagination(tenant_a_admin, tenant_a_user):
    admin = tenant_a_admin
    user = tenant_a_user

    async with client('config') as anon:
        no_auth_list = await anon.get(f'{_AIDP}/knowledge-bases')
        no_auth_count = await anon.get(f'{_AIDP}/knowledge-bases/count')
    assert no_auth_list.status_code == 401
    assert no_auth_count.status_code == 401

    async with client('config', token=admin.access_token) as api:
        page_zero = await api.get(f'{_AIDP}/knowledge-bases', params={'page': 0})
        size_zero = await api.get(f'{_AIDP}/knowledge-bases', params={'page_size': 0})
        size_over = await api.get(f'{_AIDP}/knowledge-bases', params={'page_size': 101})
    assert page_zero.status_code == 422
    assert size_zero.status_code == 422
    assert size_over.status_code == 422

    async with client('config', token=admin.access_token) as api:
        size_one = await api.get(f'{_AIDP}/knowledge-bases', params={'page': 1, 'page_size': 1})
        size_max = await api.get(f'{_AIDP}/knowledge-bases', params={'page': 1, 'page_size': 100})
    assert size_one.status_code == 200
    assert size_max.status_code == 200

    admin_kb = await _create_private_kb(admin, _kb_name('aidp-kb-a'))
    user_kb = await _create_private_kb(user, _kb_name('aidp-kb-u'))
    try:
        async with client('config', token=admin.access_token) as api:
            admin_ids, admin_total = await _collect_all(api, page_size=100)
        assert admin_kb in admin_ids
        assert user_kb not in admin_ids
        assert len(set(admin_ids)) == len(admin_ids)

        async with client('config', token=admin.access_token) as api:
            count_resp = await api.get(f'{_AIDP}/knowledge-bases/count')
        assert_status(count_resp, 200)
        count_body = count_resp.json()
        assert isinstance(count_body.get('total_count'), int)
        assert count_body['total_count'] == admin_total

        async with client('config', token=user.access_token) as api:
            user_ids, _ = await _collect_all(api, page_size=100)
        assert user_kb in user_ids
        assert admin_kb not in user_ids
        assert len(set(user_ids)) == len(user_ids)

        async with client('config', token=admin.access_token) as api:
            page_one = await _list(api, 1, 1)
        assert len(page_one['value']) <= 1
        assert page_one['has_more'] == (1 * 1 < admin_total)

        async with client('config', token=admin.access_token) as api:
            far = await api.get(f'{_AIDP}/knowledge-bases', params={'page': 9999, 'page_size': 10})
        assert_status(far, 200)
        assert far.json()['value'] == []
        assert far.json()['has_more'] is False
    finally:
        await _delete_kb(admin, admin_kb)
        await _delete_kb(user, user_kb)
