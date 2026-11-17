# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""SU tenant deprovision is separate from the exact PRIVATE owner scope."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.knowledge_admission import (
    KnowledgeBaseDeletionIntent,
    KnowledgeOwnerCleanup,
    KnowledgeTenantCleanup,
)
from management.services.knowledge_base.owner_cleanup import (
    authorize_tenant_cleanup_admission,
    has_cleanup_authority,
)
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import Page, StorageScope
from pydantic import ValidationError

from test.backend.services.test_cleanse_jobs import context


def knowledge(**changes):
    return {'knowledge_id': 1, 'index_name': 'shared', 'tenant_id': 'target', 'delete_flag': 'N',
            'created_by': 'departed', 'ingroup_permission': 'READ_ONLY', 'knowledge_sources': 'elasticsearch', **changes}


@pytest.fixture
def authority():
    actor = SimpleNamespace(user_id='admin', tenant_id='target')
    rows = [{'user_id': 'admin', 'tenant_id': 'operator', 'user_roles': ['SU']}]
    records = SimpleNamespace(scope=StorageScope('management', 'target', 'admin', {'knowledge_owner_cleanup_identities'}),
                              query=Mock(side_effect=lambda *args, **kwargs: Page(tuple(rows))))

    @contextmanager
    def ports(actual, selected, *, context):
        assert actual == actor and selected == 'admin'
        yield records

    return SimpleNamespace(**locals())


@pytest.mark.parametrize('permission', ['READ_ONLY', 'EDIT'])
def test_actual_su_authorizes_shared_resource_without_borrowing_creator_identity(authority, permission):
    s = authority
    grant = authorize_tenant_cleanup_admission(knowledge(ingroup_permission=permission), s.actor,
                                               context=context(), ports=s.ports)
    assert grant == KnowledgeTenantCleanup(actor_tenant_id='operator')
    s.records.query.assert_called_once()


@pytest.mark.parametrize('role', ['ADMIN', 'DEV', 'USER'])
def test_only_su_can_mint_tenant_deprovision(authority, role):
    s = authority
    s.rows[0]['user_roles'] = [role]
    with pytest.raises(ScopeDenied):
        authorize_tenant_cleanup_admission(knowledge(), s.actor, context=context(), ports=s.ports)


@pytest.mark.parametrize('changes', [{'tenant_id': 'other'}, {'ingroup_permission': 'PRIVATE'},
                                    {'ingroup_permission': None}, {'knowledge_sources': 'datamate'}, {'delete_flag': 'Y'}])
def test_wrong_resource_rejected_before_identity_query(authority, changes):
    s = authority
    with pytest.raises(ScopeDenied):
        authorize_tenant_cleanup_admission(knowledge(**changes), s.actor, context=context(), ports=s.ports)
    s.records.query.assert_not_called()


@pytest.mark.parametrize('rows', [[], [{'user_id': 'admin', 'tenant_id': 'a', 'user_roles': ['SU']},
                                    {'user_id': 'admin', 'tenant_id': 'b', 'user_roles': ['SU']}]])
def test_missing_or_ambiguous_issuer_is_not_selected_arbitrarily(authority, rows):
    authority.rows[:] = rows
    with pytest.raises(ScopeDenied):
        authorize_tenant_cleanup_admission(knowledge(), authority.actor, context=context(), ports=authority.ports)


def persisted(**changes):
    intent = KnowledgeBaseDeletionIntent(knowledge_id=1, index_name='shared', user_id='admin',
                                        tenant_cleanup=KnowledgeTenantCleanup(actor_tenant_id='operator'))
    return knowledge(deletion_request=intent.model_dump(mode='json'), **changes)


def test_persisted_shared_authority_uses_actual_issuer_without_live_creator_lookup():
    assert has_cleanup_authority(persisted(), 'admin', 'target') is True
    assert has_cleanup_authority(knowledge(deletion_request=None), 'admin', 'target') is False


@pytest.mark.parametrize('changes,user,tenant', [({'knowledge_id': 2}, 'admin', 'target'),
    ({'index_name': 'other'}, 'admin', 'target'), ({'ingroup_permission': 'PRIVATE'}, 'admin', 'target'),
    ({'knowledge_sources': 'datamate'}, 'admin', 'target'), ({}, 'departed', 'target'), ({}, 'admin', 'other')])
def test_persisted_authority_is_exact_not_a_general_su_grant(changes, user, tenant):
    with pytest.raises(ScopeDenied):
        has_cleanup_authority(persisted(**changes), user, tenant)


def test_private_and_tenant_authorities_cannot_coexist():
    with pytest.raises(ValidationError):
        KnowledgeBaseDeletionIntent(knowledge_id=1, index_name='shared', user_id='admin',
            tenant_cleanup=KnowledgeTenantCleanup(actor_tenant_id='operator'),
            owner_cleanup=KnowledgeOwnerCleanup(purpose='tenant_deletion', owner_user_id='owner', actor_tenant_id='operator'))
