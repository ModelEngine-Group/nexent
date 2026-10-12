from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from shared.auth import sign_in
from shared.config import load_yaml
from shared.http import assert_status, client, response_message
from database import group_db
from ext_components.aidp.database import aidp_permission_db
from shared.factories.aidp_permission import create_owned_permission, delete_owned_permission
from shared.factories.tenant import isolated_accounts
from shared.asset_registry import AssetDependencyError

CASE_ID = 'API-AUTO-3B8A8FB947806F0E'
_MANAGEMENT_ROLES = ('SU', 'ADMIN')
_DATA_LEAK_KEYS = ('value', 'total_count', 'permissions', 'kds_id', 'group_ids')


@pytest_asyncio.fixture
async def isolated_aidp_users():
    async with client('config') as api:
        contract = await api.get('/openapi.json')
    assert_status(contract, 200)
    if '/aidp-mgmt/knowledge-bases' not in contract.json().get('paths', {}):
        raise AssetDependencyError(
            'services', 'aidp_management',
            detail='ENABLE_AIDP_KNOWLEDGE is disabled in this deployment; AIDP management routes are absent',
        )
    async with isolated_accounts(('tenant_a_user', 'tenant_a_user2', 'tenant_a_admin')) as users:
        yield users


def _management_endpoints(kds_id):
    return [
        ('GET', '/aidp-mgmt/knowledge-bases', {}),
        ('GET', '/aidp-mgmt/knowledge-bases/count', {}),
        ('POST', '/aidp-mgmt/knowledge-bases', {'json': {'name': 'auth-sweep'}}),
        ('GET', f'/aidp-mgmt/knowledge-bases/{kds_id}', {}),
        ('PUT', f'/aidp-mgmt/knowledge-bases/{kds_id}', {'json': {'name': 'auth-sweep'}}),
        ('DELETE', f'/aidp-mgmt/knowledge-bases/{kds_id}', {}),
        ('POST', f'/aidp-mgmt/knowledge-bases/{kds_id}/documents', {'files': [('files', ('auth-sweep.txt', b'content', 'text/plain'))]}),
        ('GET', f'/aidp-mgmt/knowledge-bases/{kds_id}/documents', {}),
        ('PATCH', f'/aidp-mgmt/aidp-permissions/{kds_id}', {'json': {'ingroup_permission': 'PRIVATE'}}),
        ('GET', '/aidp-mgmt/models', {}),
    ]


def _discover_identity_ids():
    users = load_yaml('users.yaml').get('users') or []
    by_tenant = {}
    for user in users:
        tenant = str(user.get('tenant') or '')
        role = (str(user.get('role') or '') or 'USER').upper()
        ident = str(user.get('id') or '')
        if not tenant or not ident:
            continue
        by_tenant.setdefault(tenant, {}).setdefault(role, []).append(ident)
    for roles in by_tenant.values():
        user_ids = roles.get('USER', [])
        management_ids = [ident for role in _MANAGEMENT_ROLES for ident in roles.get(role, [])]
        if len(user_ids) >= 2 and management_ids:
            return user_ids[0], user_ids[1], management_ids[0]
    raise RuntimeError('users.yaml must define a tenant with at least two USER users and one SU/ADMIN user')


def _discover_group_id(tenant_id):
    result = group_db.query_groups_by_tenant(tenant_id, page=1, page_size=200)
    for group in result.get('groups', []):
        group_id = group.get('group_id')
        if group_id is not None:
            return int(group_id)
    raise RuntimeError(f'tenant {tenant_id!r} has no group to use as g_dev')


def _assert_no_data_leak(response):
    try:
        payload = response.json()
    except ValueError:
        return
    if isinstance(payload, dict):
        for key in _DATA_LEAK_KEYS:
            assert key not in payload, f'response leaked {key!r}: {payload}'


@pytest.mark.stage('D2')
@pytest.mark.case_id(CASE_ID)
@pytest.mark.asyncio
async def test_aidp_mgmt_auth_and_permission_surface(isolated_aidp_users):
    user_a = isolated_aidp_users['tenant_a_user']
    user_b = isolated_aidp_users['tenant_a_user2']
    management = isolated_aidp_users['tenant_a_admin']

    assert user_a.tenant_id == user_b.tenant_id, 'UserA/UserB must share a tenant'
    assert user_a.tenant_id == management.tenant_id, 'management role must share UserA tenant'

    tenant_id = user_a.tenant_id
    group_id = _discover_group_id(tenant_id)

    suffix = uuid.uuid4().hex[:12]
    kb_private = f'kb-private-{suffix}'
    kb_shared = f'kb-shared-{suffix}'
    missing_kds_id = f'kb-nonexistent-{suffix}'

    responses = []
    owned_rows = []

    try:
        private_row_id = create_owned_permission(
            kb_id=kb_private, owner_user_id=user_a.user_id,
            tenant_id=tenant_id, ingroup_permission='PRIVATE', group_ids=[],
        )
        owned_rows.append((kb_private, private_row_id))
        shared_row_id = create_owned_permission(
            kb_id=kb_shared, owner_user_id=user_a.user_id,
            tenant_id=tenant_id, ingroup_permission='READ_ONLY', group_ids=[group_id],
        )
        owned_rows.append((kb_shared, shared_row_id))
        async with client('config') as anon:
            for method, path, kwargs in _management_endpoints(missing_kds_id):
                response = await anon.request(method, path, **kwargs)
                assert_status(response, 401)
                _assert_no_data_leak(response)
                responses.append(response)

        async with client('config', token='invalid-token-value') as bad:
            for path in (
                '/aidp-mgmt/knowledge-bases',
                f'/aidp-mgmt/knowledge-bases/{kb_private}',
            ):
                response = await bad.get(path)
                assert_status(response, 401)
                _assert_no_data_leak(response)
                responses.append(response)

        async with client('config', token=user_b.access_token) as api:
            response = await api.get(f'/aidp-mgmt/knowledge-bases/{missing_kds_id}')
            assert_status(response, 404)
            responses.append(response)

        async with client('config', token=user_b.access_token) as api:
            response = await api.get(f'/aidp-mgmt/knowledge-bases/{kb_private}')
            assert_status(response, 403)
            responses.append(response)

            response = await api.put(f'/aidp-mgmt/knowledge-bases/{kb_private}', json={'name': 'x'})
            assert_status(response, 403)
            responses.append(response)

            response = await api.delete(f'/aidp-mgmt/knowledge-bases/{kb_private}')
            assert_status(response, 403)
            responses.append(response)

            response = await api.post(
                f'/aidp-mgmt/knowledge-bases/{kb_private}/documents',
                files=[('files', ('d.txt', b'content', 'text/plain'))],
            )
            assert_status(response, 403)
            responses.append(response)

        async with client('config', token=user_a.access_token) as api:
            response = await api.patch(
                f'/aidp-mgmt/aidp-permissions/{kb_shared}',
                json={'ingroup_permission': 'EDIT', 'group_ids': [group_id]},
            )
            assert_status(response, 403)
            assert response_message(response) == 'USER role can only manage PRIVATE personal knowledge bases'
            responses.append(response)

        async with client('config', token=management.access_token) as api:
            response = await api.patch(
                f'/aidp-mgmt/aidp-permissions/{kb_shared}',
                json={'ingroup_permission': 'EDIT', 'group_ids': [group_id]},
            )
            assert_status(response, 200)
            payload = response.json()
            assert payload.get('permissions_saved') is True
            responses.append(response)

        row = aidp_permission_db.get_permission_by_kb_id(kb_shared, tenant_id)
        assert row is not None, 'kb_shared permission row missing after PATCH'
        assert row['ingroup_permission'] == 'EDIT'
        assert int(group_id) in [int(g) for g in row['group_ids']]

        for identity in (user_a, user_b, management):
            for secret in (identity.access_token, identity.password):
                for response in responses:
                    assert secret not in response.text, 'response leaked a credential'

    finally:
        for kb_id, row_id in reversed(owned_rows):
            delete_owned_permission(
                kb_id=kb_id, row_id=row_id, tenant_id=tenant_id,
                owner_user_id=user_a.user_id,
            )
