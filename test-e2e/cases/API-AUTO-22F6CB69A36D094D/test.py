from __future__ import annotations

import uuid

import pytest

from shared.http import assert_status, client, response_message
from shared.factories.ownership import register_owned_http


def _first_tenant_group_id(tenant_id: str) -> int:
    """Return one real active group_id for ``tenant_id`` (LOCAL_FULL_STACK reads the real DB)."""
    from database import group_db

    payload = group_db.query_groups_by_tenant(tenant_id, page=None, page_size=None)
    groups = payload.get('groups') or []
    if not groups:
        raise RuntimeError('no active groups configured for tenant %r' % tenant_id)
    return int(groups[0]['group_id'])


@pytest.mark.case_id('API-AUTO-22F6CB69A36D094D')
@pytest.mark.stage('D2')
async def test_create_aidp_kb_contract(tenant_a_user, tenant_a_admin, tenant_b_admin):
    """Contract test for POST /aidp-mgmt/knowledge-bases.

    Covers: 401 on missing/invalid auth, USER forced-PRIVATE normalization,
    and non-USER 400s for missing group_ids / cross-tenant group / invalid
    ingroup_permission, then best-effort cleanup for repeatability.
    """
    run_tag = uuid.uuid4().hex[:8]
    created_kds_ids = []

    # Missing Authorization header -> 401.
    async with client('config') as api:
        response = await api.post(
            '/aidp-mgmt/knowledge-bases',
            json={'name': 'aidp-d2-%s-noauth' % run_tag},
        )
    assert response.status_code == 401
    assert 'Missing Authorization header' in response_message(response)

    # Invalid bearer token -> 401.
    async with client('config', token='invalid-token-value') as api:
        response = await api.post(
            '/aidp-mgmt/knowledge-bases',
            json={'name': 'aidp-d2-%s-badtoken' % run_tag},
        )
    assert response.status_code == 401

    tenant_a_group_id = _first_tenant_group_id(tenant_a_admin.tenant_id)
    tenant_b_group_id = _first_tenant_group_id(tenant_b_admin.tenant_id)

    # USER role explicitly sending EDIT + a valid tenant group must be normalized
    # to a PRIVATE personal KB (group_ids ignored) and still return 200.
    async with client('config', token=tenant_a_user.access_token) as api:
        response = await api.post(
            '/aidp-mgmt/knowledge-bases',
            json={
                'name': 'aidp-d2-%s-user' % run_tag,
                'ingroup_permission': 'EDIT',
                'group_ids': [tenant_a_group_id],
            },
        )
    assert response.status_code == 200
    body = response.json()
    raw_kds_id = body.get('kds_id') if body.get('kds_id') is not None else body.get('id')
    assert raw_kds_id is not None
    assert body.get('permission') == 'EDIT'
    kds_id = str(raw_kds_id)
    created_kds_ids.append(kds_id)
    # Register at creation time: a later assertion can fail before the manual
    # cleanup loop, but the batch finalizer must still know the exact owner.
    register_owned_http(
        tenant_a_user, 'aidp_knowledge_bases', kds_id,
        f'/aidp-mgmt/knowledge-bases/{kds_id}',
    )

    # The USER KB row must be normalized to PRIVATE with empty group_ids.
    async with client('config', token=tenant_a_user.access_token) as api:
        listing = await api.get(
            '/aidp-mgmt/knowledge-bases',
            params={'page': 1, 'page_size': 100},
        )
    assert listing.status_code == 200
    created = next(
        (item for item in listing.json().get('value', []) if str(item.get('kds_id')) == kds_id),
        None,
    )
    assert created is not None
    assert created.get('ingroup_permission') == 'PRIVATE'
    assert not created.get('group_ids')

    # Non-USER with EDIT/READ_ONLY but no group_ids -> 400.
    async with client('config', token=tenant_a_admin.access_token) as api:
        response = await api.post(
            '/aidp-mgmt/knowledge-bases',
            json={
                'name': 'aidp-d2-%s-admin-nogroup' % run_tag,
                'ingroup_permission': 'EDIT',
            },
        )
    assert response.status_code == 400
    assert 'group_ids is required' in response_message(response)

    # Non-USER with an unsupported ingroup_permission -> 400.
    async with client('config', token=tenant_a_admin.access_token) as api:
        response = await api.post(
            '/aidp-mgmt/knowledge-bases',
            json={
                'name': 'aidp-d2-%s-admin-badperm' % run_tag,
                'ingroup_permission': 'BOGUS',
            },
        )
    assert response.status_code == 400
    assert 'Unsupported ingroup_permission' in response_message(response)

    # Non-USER with a cross-tenant group -> 400 (AidpGroupValidationError mapping).
    async with client('config', token=tenant_a_admin.access_token) as api:
        response = await api.post(
            '/aidp-mgmt/knowledge-bases',
            json={
                'name': 'aidp-d2-%s-admin-cross' % run_tag,
                'ingroup_permission': 'EDIT',
                'group_ids': [tenant_b_group_id],
            },
        )
    assert response.status_code == 400
    assert 'are not part of tenant' in response_message(response)

    # Cleanup the created AIDP knowledge base so the case stays repeatable.
    for created_kds_id in created_kds_ids:
        async with client('config', token=tenant_a_user.access_token) as api:
            cleanup = await api.delete('/aidp-mgmt/knowledge-bases/%s' % created_kds_id)
        assert_status(cleanup, 200)
