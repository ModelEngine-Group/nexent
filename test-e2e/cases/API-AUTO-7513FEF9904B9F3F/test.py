from __future__ import annotations

import asyncio
import time
import uuid

import pytest

from shared.http import assert_status, client, response_message
from shared.factories.ownership import register_owned_http

CASE_ID = 'API-AUTO-7513FEF9904B9F3F'

_LIST_PAGE_SIZE = 100


def _new_run_id() -> str:
    return uuid.uuid4().hex[:12]


async def _list_visible_kbs(api) -> dict[str, dict]:
    visible: dict[str, dict] = {}
    page = 1
    while True:
        resp = await api.get(
            '/aidp-mgmt/knowledge-bases',
            params={'page': page, 'page_size': _LIST_PAGE_SIZE},
        )
        assert_status(resp, 200)
        payload = resp.json()
        for item in payload.get('value') or []:
            if not isinstance(item, dict):
                continue
            raw_id = item.get('kds_id') or item.get('id')
            if raw_id is not None:
                visible[str(raw_id)] = item
        if not payload.get('has_more'):
            return visible
        page += 1


async def _kb_name(api, kds_id: str) -> str | None:
    resp = await api.get(f'/aidp-mgmt/knowledge-bases/{kds_id}')
    assert_status(resp, 200)
    payload = resp.json() or {}
    return payload.get('kds_name') or payload.get('name') or None


async def _wait_until(desc: str, predicate, timeout: float = 60.0, interval: float = 1.0):
    deadline = time.monotonic() + timeout
    last = None
    while True:
        ok, last = await predicate()
        if ok:
            return last
        if time.monotonic() >= deadline:
            raise AssertionError(f'{desc}: condition not met within {timeout}s; last={last!r}')
        await asyncio.sleep(interval)


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D3')
async def test_aidp_kb_update_delete_core_api_auto_7513fef9904b9f3f(
    tenant_a_admin,
    tenant_a_user,
    tenant_b_admin,
):
    run_id = _new_run_id()
    name = f'aidp-upd-del-{run_id}'
    new_name = f'{name}-新名'
    new_desc = '更新描述'

    kds_id: str | None = None
    deleted = False

    try:
        async with client('config', token=tenant_a_admin.access_token) as api:
            create = await api.post(
                '/aidp-mgmt/knowledge-bases',
                json={
                    'name': name,
                    'description': '初始描述',
                    'ingroup_permission': 'PRIVATE',
                },
            )
            assert_status(create, 200)
            created = create.json() or {}
            kds_id = str(created.get('kds_id') or created.get('id') or '')
            assert kds_id, f'create response missing kds_id: {created}'
            register_owned_http(tenant_a_admin, 'aidp_knowledge_bases', kds_id,
                                f'/aidp-mgmt/knowledge-bases/{kds_id}')

            async def _created_visible():
                visible = await _list_visible_kbs(api)
                return kds_id in visible, visible.get(kds_id)

            await _wait_until('created KB not visible in list', _created_visible)

        async with client('config', token=tenant_a_user.access_token) as api:
            peer_before = await api.get(f'/aidp-mgmt/knowledge-bases/{kds_id}')
            assert_status(peer_before, (403, 404))

        async with client('config', token=tenant_a_admin.access_token) as api:
            upload = await api.post(
                f'/aidp-mgmt/knowledge-bases/{kds_id}/documents',
                files={'files': ('sample.txt', b'hello aidp knowledge base test document', 'text/plain')},
            )
            assert_status(upload, 200)

            docs = await api.get(f'/aidp-mgmt/knowledge-bases/{kds_id}/documents')
            assert_status(docs, 200)

            detail_before = await api.get(f'/aidp-mgmt/knowledge-bases/{kds_id}')
            assert_status(detail_before, 200)

            update = await api.put(
                f'/aidp-mgmt/knowledge-bases/{kds_id}',
                json={'name': new_name, 'description': new_desc},
            )
            assert_status(update, 200)

        async with client('config', token=tenant_a_admin.access_token) as api:
            async def _name_synced():
                visible = await _list_visible_kbs(api)
                item = visible.get(kds_id)
                list_name = (item or {}).get('kds_name') or (item or {}).get('name')
                if list_name != new_name:
                    return False, {'list_name': list_name}
                detail_name = await _kb_name(api, kds_id)
                if detail_name != new_name:
                    return False, {'detail_name': detail_name}
                return True, {'list_name': list_name, 'detail_name': detail_name}

            await _wait_until('updated name not synced to list/detail', _name_synced)

            empty = await api.put(f'/aidp-mgmt/knowledge-bases/{kds_id}', json={})
            assert_status(empty, 400)
            detail_msg = response_message(empty)
            assert 'name or description' in detail_msg, f'unexpected 400 detail: {empty.text}'

            still_name = await _kb_name(api, kds_id)
            assert still_name == new_name, f'empty update overwrote kds_name: {still_name!r}'

            delete = await api.delete(f'/aidp-mgmt/knowledge-bases/{kds_id}')
            assert_status(delete, 200)
            assert (delete.json() or {}).get('success') is True, f'delete not successful: {delete.text}'
            deleted = True

        async with client('config', token=tenant_a_admin.access_token) as api:
            async def _gone():
                visible = await _list_visible_kbs(api)
                return kds_id not in visible, kds_id in visible

            await _wait_until('deleted KB still visible in list', _gone)

            detail_after = await api.get(f'/aidp-mgmt/knowledge-bases/{kds_id}')
            assert_status(detail_after, 404)

            docs_after = await api.get(f'/aidp-mgmt/knowledge-bases/{kds_id}/documents')
            assert_status(docs_after, 404)

        async with client('config', token=tenant_b_admin.access_token) as api:
            cross = await api.get(f'/aidp-mgmt/knowledge-bases/{kds_id}')
            assert_status(cross, (403, 404))

        async with client('config', token=tenant_a_user.access_token) as api:
            peer_after = await api.get(f'/aidp-mgmt/knowledge-bases/{kds_id}')
            assert_status(peer_after, (403, 404))

    finally:
        if kds_id and not deleted:
            try:
                async with client('config', token=tenant_a_admin.access_token) as api:
                    await api.delete(f'/aidp-mgmt/knowledge-bases/{kds_id}')
            except Exception:
                pass
