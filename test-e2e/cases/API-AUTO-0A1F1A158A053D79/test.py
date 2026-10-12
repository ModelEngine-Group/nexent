'''D2 契约测试：USER 角色知识库隐私边界。

验证 USER 创建知识库被强制为 PRIVATE 且清空 group_ids；USER 仅能管理
PRIVATE 个人知识库，不可转共享、不可分配组、不可越权更新他人共享 KB。
'''

import os
import uuid

import pytest

from d3.assets import model_id
from shared.http import assert_status, client
from shared.factories.ownership import register_owned_http
from shared.asset_registry import mark_asset_state

CASE_ID = 'API-AUTO-0A1F1A158A053D79'

_PROBE_GROUP_ID = 9_999_999_999

_MSG_ONLY_PRIVATE = 'USER role can only manage PRIVATE personal knowledge bases'
_MSG_TURN_SHARED = 'USER role cannot turn a personal knowledge base into a shared knowledge base'
_MSG_ASSIGN_GROUP = 'USER role cannot assign groups to a personal knowledge base'
_MSG_NO_PERMISSION = 'No permission to modify this knowledge base'


def _run_id() -> str:
    return os.environ.get('RUN_ID') or os.environ.get('TEST_BATCH') or uuid.uuid4().hex[:12]


def _find_stat(payload, index_name):
    for info in payload.get('indices_info', []):
        if info.get('name') == index_name:
            return info
    return None


async def _read_kb_stat(token, index_name):
    async with client('config', token=token) as api:
        response = await api.get('/indices', params={'include_stats': 'true'})
    assert_status(response, 200)
    return _find_stat(response.json(), index_name)


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D2')
@pytest.mark.asyncio
async def test_user_kb_privacy_forced_and_restricted(tenant_a_user, tenant_a_admin):
    user = tenant_a_user
    admin = tenant_a_admin
    assert user.role == 'USER', f'tenant_a_user 不是 USER 角色: {user.role!r}'
    assert admin.role in ('ADMIN', 'SU'), f'tenant_a_admin 不是管理员角色: {admin.role!r}'

    embedding_model_id = await model_id('embedding', admin)
    run_suffix = f'{_run_id()}-{uuid.uuid4().hex[:8]}'
    user_kb_name = f'kb-user-{run_suffix}'
    shared_kb_name = f'kb-shared-{run_suffix}'

    user_kb_index = None
    shared_kb_index = None
    try:
        async with client('config', token=user.access_token) as api:
            create_user = await api.post(
                f'/indices/{user_kb_name}',
                json={
                    'ingroup_permission': 'EDIT',
                    'group_ids': [_PROBE_GROUP_ID],
                    'embedding_model_id': embedding_model_id,
                },
            )
        assert_status(create_user, 200)
        payload = create_user.json()
        user_kb_index = payload.get('id') or payload.get('index_name')
        assert user_kb_index, f'USER 创建响应缺少内部 index_name: {payload!r}'
        register_owned_http(user, 'owned_indices', str(user_kb_index), f'/indices/{user_kb_index}')

        stat = await _read_kb_stat(user.access_token, user_kb_index)
        assert stat is not None, f'USER 创建的知识库 {user_kb_index} 对创建者不可见'
        assert str(stat.get('ingroup_permission') or '').upper() == 'PRIVATE'
        assert _PROBE_GROUP_ID not in (stat.get('group_ids') or [])

        async with client('config', token=user.access_token) as api:
            turn_shared = await api.patch(
                f'/indices/{user_kb_index}', json={'ingroup_permission': 'EDIT'}
            )
        assert turn_shared.status_code >= 400, f'转共享未按预期被拒绝: {turn_shared.text!r}'
        assert _MSG_TURN_SHARED in turn_shared.text
        stat = await _read_kb_stat(user.access_token, user_kb_index)
        assert str(stat.get('ingroup_permission') or '').upper() == 'PRIVATE'

        async with client('config', token=user.access_token) as api:
            assign_group = await api.patch(
                f'/indices/{user_kb_index}', json={'group_ids': [_PROBE_GROUP_ID]}
            )
        assert assign_group.status_code >= 400, f'分配组未按预期被拒绝: {assign_group.text!r}'
        assert _MSG_ASSIGN_GROUP in assign_group.text
        stat = await _read_kb_stat(user.access_token, user_kb_index)
        assert _PROBE_GROUP_ID not in (stat.get('group_ids') or [])

        async with client('config', token=admin.access_token) as api:
            create_admin = await api.post(
                f'/indices/{shared_kb_name}',
                json={'ingroup_permission': 'EDIT', 'embedding_model_id': embedding_model_id},
            )
        assert_status(create_admin, 200)
        payload = create_admin.json()
        shared_kb_index = payload.get('id') or payload.get('index_name')
        assert shared_kb_index, f'Admin 创建响应缺少内部 index_name: {payload!r}'
        register_owned_http(admin, 'owned_indices', str(shared_kb_index), f'/indices/{shared_kb_index}')

        async with client('config', token=user.access_token) as api:
            update_other = await api.patch(
                f'/indices/{shared_kb_index}', json={'ingroup_permission': 'READ_ONLY'}
            )
        assert update_other.status_code >= 400, f'越权更新共享 KB 未按预期被拒绝: {update_other.text!r}'
        assert _MSG_NO_PERMISSION in update_other.text
        stat = await _read_kb_stat(admin.access_token, shared_kb_index)
        assert stat is not None, f'Admin 创建的知识库 {shared_kb_index} 对 Admin 不可见'
        assert str(stat.get('ingroup_permission') or '').upper() == 'EDIT'
    finally:
        for token, index_name in ((user.access_token, user_kb_index), (admin.access_token, shared_kb_index)):
            if index_name is None:
                continue
            try:
                async with client('config', token=token) as api:
                    cleanup = await api.delete(f'/indices/{index_name}')
                assert_status(cleanup, (200, 404))
                mark_asset_state('owned_indices', str(index_name), 'DELETED')
            except Exception:
                pass
