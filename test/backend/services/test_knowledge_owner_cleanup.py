# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-OWNER-01/02: scoped deprovision authority never impersonates its owner."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.knowledge_admission import (
    KnowledgeBaseDeletionIntent,
    KnowledgeOwnerCleanup,
)
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from management.services.knowledge_base.owner_cleanup import (
    authorize_owner_cleanup_admission,
    has_owner_cleanup_authority,
)
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import Page, StorageScope

from infrastructure.rdb.cleanse_resources import bind_cleanse_resources
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context


def knowledge(**changes):
    return {'knowledge_id': 1, 'tenant_id': 'target-tenant', 'index_name': 'kb', 'created_by': 'owner',
            'ingroup_permission': 'PRIVATE', 'knowledge_sources': 'elasticsearch', 'delete_flag': 'N', **changes}


@pytest.fixture
def authority():
    actor = SimpleNamespace(user_id='admin', tenant_id='target-tenant')
    rows = [{'user_tenant_id': 1, 'user_id': 'admin', 'tenant_id': 'target-tenant', 'user_roles': ['ADMIN']},
            {'user_tenant_id': 2, 'user_id': 'owner', 'tenant_id': 'target-tenant', 'user_roles': ['USER']}]
    records = SimpleNamespace(scope=StorageScope('management', 'target-tenant', 'admin', {'knowledge_owner_cleanup_identities'}))
    calls = []

    def query(*args, **kwargs):
        calls.append(args)
        return Page(tuple(rows))

    records.query = Mock(side_effect=query)

    @contextmanager
    def ports(actual, owner, *, context):
        assert actual == actor and owner == 'owner'
        yield records

    return SimpleNamespace(**locals())


def test_current_admin_gets_only_exact_private_owner_scope(authority):
    s = authority
    grant = authorize_owner_cleanup_admission(knowledge(), 'owner', 'user_deletion', s.actor,
                                              context=context(), ports=s.ports)
    assert grant == KnowledgeOwnerCleanup(owner_user_id='owner', actor_tenant_id='target-tenant', purpose='user_deletion')
    s.records.query.assert_called_once()


def test_super_admin_cross_tenant_preserves_original_actor_tenant(authority):
    s = authority
    s.rows[0].update(tenant_id='operator-tenant', user_roles=['SU'])
    grant = authorize_owner_cleanup_admission(knowledge(), 'owner', 'user_deletion', s.actor, context=context(), ports=s.ports)
    assert grant.actor_tenant_id == 'operator-tenant'
    assert s.actor.user_id == 'admin'


@pytest.mark.parametrize('change', [{'tenant_id': 'foreign'}, {'created_by': 'different'},
                                    {'ingroup_permission': 'EDIT'}, {'knowledge_sources': 'datamate'}])
def test_wrong_resource_rejected_before_identity_query(authority, change):
    s = authority
    with pytest.raises(ScopeDenied):
        authorize_owner_cleanup_admission(knowledge(**change), 'owner', 'user_deletion', s.actor, context=context(), ports=s.ports)
    s.records.query.assert_not_called()


@pytest.mark.parametrize('change', [{'user_roles': ['DEV']}, {'tenant_id': 'foreign', 'user_roles': ['ADMIN']}])
def test_non_management_or_foreign_admin_cannot_mint_grant(authority, change):
    s = authority
    s.rows[0].update(**change)
    with pytest.raises(ScopeDenied):
        authorize_owner_cleanup_admission(knowledge(), 'owner', 'user_deletion', s.actor, context=context(), ports=s.ports)


@pytest.mark.parametrize('purpose,role,allowed', [('tenant_deletion', 'SU', True), ('tenant_deletion', 'ADMIN', False),
                                                ('user_deletion', 'SU', False)])
def test_tenant_command_uses_existing_su_authority_for_special_targets(authority, purpose, role, allowed):
    s = authority
    s.rows[0]['user_roles'] = [role]
    s.rows[1]['user_roles'] = ['SU']
    if allowed:
        assert authorize_owner_cleanup_admission(knowledge(), 'owner', purpose, s.actor, context=context(), ports=s.ports).purpose == purpose
    else:
        with pytest.raises(ScopeDenied):
            authorize_owner_cleanup_admission(knowledge(), 'owner', purpose, s.actor, context=context(), ports=s.ports)


def test_ambiguous_actor_membership_is_never_selected_arbitrarily(authority):
    s = authority
    s.rows.append({**s.rows[0], 'user_tenant_id': 3, 'tenant_id': 'other'})
    with pytest.raises(ScopeDenied):
        authorize_owner_cleanup_admission(knowledge(), 'owner', 'user_deletion', s.actor, context=context(), ports=s.ports)


@pytest.mark.parametrize('role,allowed', [('USER', True), ('DEV', True), ('ADMIN', False), ('SU', False)])
def test_self_revocation_keeps_original_account_revoke_role_boundary(authority, role, allowed):
    s = authority
    s.actor.user_id = 'owner'
    s.rows[:] = [{**s.rows[1], 'user_roles': [role]}]
    s.records.scope = StorageScope('management', 'target-tenant', 'owner', {'knowledge_owner_cleanup_identities'})
    if allowed:
        grant = authorize_owner_cleanup_admission(knowledge(), 'owner', 'user_deletion', s.actor, context=context(), ports=s.ports)
        assert grant.owner_user_id == 'owner'
    else:
        with pytest.raises(ScopeDenied):
            authorize_owner_cleanup_admission(knowledge(), 'owner', 'user_deletion', s.actor, context=context(), ports=s.ports)


def granted(**changes):
    intent = KnowledgeBaseDeletionIntent(knowledge_id=1, index_name='kb', user_id='admin',
        owner_cleanup=KnowledgeOwnerCleanup(owner_user_id='owner', actor_tenant_id='operator-tenant', purpose='user_deletion'))
    return knowledge(deletion_request=intent.model_dump(mode='json'), **changes)


def test_persisted_resource_authority_needs_no_deleted_owner_identity():
    assert has_owner_cleanup_authority(granted(), 'admin', 'target-tenant') is True
    assert has_owner_cleanup_authority(knowledge(deletion_request=None), 'admin', 'target-tenant') is False


@pytest.mark.parametrize('change,user,tenant', [({'knowledge_id': 2}, 'admin', 'target-tenant'),
    ({'created_by': 'other'}, 'admin', 'target-tenant'), ({'ingroup_permission': 'EDIT'}, 'admin', 'target-tenant'),
    ({'index_name': 'other'}, 'admin', 'target-tenant'), ({}, 'owner', 'target-tenant'), ({}, 'admin', 'other')])
def test_persisted_grant_is_not_portable_to_other_actor_resource_or_tenant(change, user, tenant):
    with pytest.raises(ScopeDenied):
        has_owner_cleanup_authority(granted(**change), user, tenant)


def test_cleanup_callback_uses_persisted_issuer_after_target_identity_is_gone(resources):  # noqa: F811
    _, update, engine, tables = resources
    scope = KnowledgeBaseDeletionIntent(knowledge_id=1, index_name='kb-one', user_id='admin',
        owner_cleanup=KnowledgeOwnerCleanup(owner_user_id='owner', actor_tenant_id='operator-tenant', purpose='user_deletion'))
    update('cleanse_knowledge', created_by='owner', ingroup_permission='PRIVATE', deletion_request=scope.model_dump(mode='json'))
    update('cleanse_memberships', delete_flag='Y')
    update('cleanse_accounts', delete_flag='Y')
    records = bind_cleanse_resources(StorageScope('management', 'tenant-a', 'admin', set(tables)), engine)
    try:
        policy = KnowledgeFileAuthorization(records, user_id='admin')
        assert policy.resolve_knowledge(1, edit=True, cleanup=True, context=context())['created_by'] == 'owner'
        for edit, cleanup in ((True, False), (False, False), (False, True)):
            with pytest.raises(ScopeDenied):
                policy.resolve_knowledge(1, edit=edit, cleanup=cleanup, context=context())
    finally:
        records.close()
