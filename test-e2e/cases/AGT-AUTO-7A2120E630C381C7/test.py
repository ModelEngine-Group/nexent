'''D3 AGENT-IT: ENABLE_AIDP_KNOWLEDGE 开启时 nl2agent 装配 aidp_search 工具并注入 kds 白名单，权限变更下次 run 生效(无缓存)。'''

from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio

from shared.asset_registry import register_asset, resolve_asset, mark_asset_state
from shared.factories.ownership import register_owned_http
from shared.http import assert_status, client

CASE_ID = 'AGT-AUTO-7A2120E630C381C7'
DEV_IDENTITY = 'tenant_a_dev'
ADMIN_IDENTITY = 'tenant_a_admin'
AIDP_TOOL_NAME = 'aidp_search'


def _run_suffix() -> str:
    return uuid.uuid4().hex[:8]


def _resolve_dev_group_ids(dev_identity_id: str) -> list:
    if dev_identity_id != DEV_IDENTITY:
        raise ValueError('unexpected developer identity alias')
    return [int(resolve_asset('groups', 'aidp_dev_group', consumer_case_id=CASE_ID))]


@pytest_asyncio.fixture(autouse=True)
async def aidp_dev_group(tenant_a_admin, tenant_a_dev):
    """Create this case's permission group instead of reading users.yaml."""
    async with client('config', token=tenant_a_admin.access_token) as api:
        created = await api.post('/groups', json={
            'tenant_id': tenant_a_admin.tenant_id,
            'group_name': f'aidp-dev-{uuid.uuid4().hex[:10]}',
            'group_description': 'owned AIDP whitelist probe',
        })
    assert_status(created, 201)
    group_id = int((created.json().get('data') or {})['group_id'])
    register_owned_http(tenant_a_admin, 'owned_groups', group_id, f'/groups/{group_id}')
    try:
        async with client('config', token=tenant_a_admin.access_token) as api:
            added = await api.post(f'/groups/{group_id}/members', json={'user_id': tenant_a_dev.user_id})
        assert_status(added, 200)
        register_asset('groups', 'aidp_dev_group', group_id, owner_case_id=CASE_ID)
        yield
    finally:
        async with client('config', token=tenant_a_admin.access_token) as api:
            deleted = await api.delete(f'/groups/{group_id}')
        assert_status(deleted, (200, 404))
        mark_asset_state('owned_groups', str(group_id), 'DELETED')


def _extract_kds_id(payload) -> str:
    raw = payload.get('kds_id') or payload.get('id')
    if not raw:
        raise AssertionError(f'create response missing kds_id: {payload!r}')
    return str(raw)


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D3')
@pytest.mark.asyncio
async def test_aidp_search_whitelist_recomputed_every_run(tenant_a_admin, tenant_a_dev):
    suffix = _run_suffix()
    kb_name = f'KB-A-{suffix}'
    dev_group_ids = _resolve_dev_group_ids(DEV_IDENTITY)

    # 1. Admin creates KB-A shared to DevUserA's group (READ_ONLY).
    async with client('config', token=tenant_a_admin.access_token) as api:
        created = await api.post(
            '/aidp-mgmt/knowledge-bases',
            json={
                'name': kb_name,
                'description': kb_name,
                'ingroup_permission': 'READ_ONLY',
                'group_ids': dev_group_ids,
            },
        )
    assert_status(created, 200)
    created_body = created.json()
    kds_id = _extract_kds_id(created_body)
    assert 'api_key' not in json.dumps(created_body, ensure_ascii=False).lower()

    register_asset(
        'aidp_kb',
        kds_id,
        value=kds_id,
        owner_case_id=CASE_ID,
        cleanup={
            'identity': ADMIN_IDENTITY,
            'service': 'config',
            'method': 'DELETE',
            'path': f'/aidp-mgmt/knowledge-bases/{kds_id}',
            'allowed_statuses': [200, 404],
        },
    )

    # 2/3. First run: the nl2agent whitelist (accessible_id_set) contains KB-A.
    async with client('config', token=tenant_a_dev.access_token) as api:
        listing = await api.get(
            '/aidp-mgmt/knowledge-bases', params={'page': 1, 'page_size': 100}
        )
    assert_status(listing, 200)
    accessible_ids = {str(item.get('kds_id')) for item in listing.json().get('value', [])}
    assert kds_id in accessible_ids, (
        f'KB-A should be in DevUserA whitelist after first run: {accessible_ids}'
    )

    # 4. Admin switches KB-A to PRIVATE (permissions saved before metadata sync).
    async with client('config', token=tenant_a_admin.access_token) as api:
        patched = await api.patch(
            f'/aidp-mgmt/aidp-permissions/{kds_id}',
            json={'ingroup_permission': 'PRIVATE'},
        )
    assert_status(patched, 200)
    patched_body = patched.json()
    assert patched_body.get('permissions_saved') is True
    assert 'api_key' not in json.dumps(patched_body, ensure_ascii=False).lower()

    # 5. Second run: whitelist recomputed, KB-A no longer visible (no cache).
    async with client('config', token=tenant_a_dev.access_token) as api:
        listing2 = await api.get(
            '/aidp-mgmt/knowledge-bases', params={'page': 1, 'page_size': 100}
        )
    assert_status(listing2, 200)
    accessible_ids2 = {str(item.get('kds_id')) for item in listing2.json().get('value', [])}
    assert kds_id not in accessible_ids2, (
        f'KB-A must be removed from DevUserA whitelist after PRIVATE: {accessible_ids2}'
    )

    # 6. Fallback: an installed-but-empty whitelist blocks every kds via
    #    AidpSearchTool._filter_by_whitelist (no cross-KB escalation).
    from nexent.core.ext_components.aidp.aidp_search_tool import AidpSearchTool

    assert AidpSearchTool.name == AIDP_TOOL_NAME

    tool = AidpSearchTool(
        server_url='http://127.0.0.1:1',
        api_key='ak-test',
        tenant_id='aidp',
        kds_list='[]',
    )
    assert tool._whitelist_installed is False
    tool.set_allowed_kds([kds_id])
    assert tool._filter_by_whitelist([kds_id, 'other-kb']) == [kds_id]
    tool.set_allowed_kds([])
    assert tool._whitelist_installed is True
    assert tool._filter_by_whitelist([kds_id, 'other-kb']) == []
