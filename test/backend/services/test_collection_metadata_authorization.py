# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-COL-META-01 preserve current list DAC with finite SI metadata."""

from contextlib import contextmanager
from time import monotonic
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.knowledge_collections import KnowledgeCollectionsAuthorization
from management.services.knowledge_base import (
    collection_metadata_authorization as module,
)
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import OperationContext

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.knowledge_catalog import knowledge
from infrastructure.knowledge_collection_metadata import (
    bind_collection_metadata,
    bind_collection_permissions,
    permissions_table,
)


@pytest.fixture
def boundary(mocker):
    engine = sa.create_engine('sqlite://', execution_options={'schema_translate_map': {'nexent': None}})
    knowledge.create(engine); permissions_table.create(engine)
    actor = ServicePrincipal('reader', 'tenant-a')
    identity = SimpleNamespace(scope=SimpleNamespace(service_role='management', tenant_id=actor.tenant_id,
        actor_id=actor.user_id, system=False, resource_prefix=''))
    member = {'tenant_id': actor.tenant_id, 'user_roles': ['DEV']}
    identity_read = mocker.patch.object(module.KnowledgeFileAuthorization, 'identity', side_effect=lambda **kw: (member, [5]))
    with engine.begin() as conn:
        for key, tenant, creator, permission, groups, source in [
            (1, 'tenant-a', 'reader', 'PRIVATE', None, 'elasticsearch'),
            (2, 'tenant-a', 'other', 'PRIVATE', None, 'elasticsearch'),
            (3, 'tenant-a', 'other', 'READ_ONLY', '5', 'elasticsearch'),
            (4, ASSET_OWNER_TENANT_ID, 'publisher', 'READ_ONLY', None, 'elasticsearch'),
            (5, 'tenant-b', 'other', 'READ_ONLY', None, 'elasticsearch'),
            (6, 'tenant-a', 'reader', 'EDIT', None, 'datamate'),
        ]:
            conn.execute(knowledge.insert(), {'knowledge_id': key, 'tenant_id': tenant, 'index_name': f'kb-{key}',
                'created_by': creator, 'ingroup_permission': permission, 'group_ids': groups,
                'knowledge_sources': source, 'embedding_model_id': None, 'version': 1, 'delete_flag': 'N'})
        conn.execute(permissions_table.insert(), {'role_permission_id': 1, 'user_role': 'OPS',
            'permission_category': 'RESOURCE', 'permission_type': 'RESOURCE.INVENTORY', 'permission_subtype': 'READ'})
    opened, closed = [], []

    @contextmanager
    def ports(principal, *, context):
        assert principal == actor
        owned = [bind_collection_permissions(actor, engine)]
        def resources(*, cross_tenant):
            opened.append(cross_tenant)
            port = bind_collection_metadata(actor, engine, cross_tenant=cross_tenant)
            owned.append(port)
            return port
        try:
            yield identity, owned[0], resources
        finally:
            for port in reversed(owned):
                port.close()
            closed.append(True)

    yield SimpleNamespace(**locals())
    engine.dispose()


def invoke(s, ids, view='resources'):
    return module.authorize_collection_metadata(KnowledgeCollectionsAuthorization(knowledge_ids=ids, view=view),
        s.actor, context=OperationContext('metadata-policy', monotonic() + 10), ports=s.ports)


def test_dev_can_read_own_private_group_and_shared_without_model_configuration(boundary):
    s = boundary
    result = invoke(s, [4, 1, 3])
    assert [g.knowledge_id for g in result.knowledge_bases] == [4, 1, 3]
    assert all(g.embedding_model_id is None and len(g.revision) == 64 for g in result.knowledge_bases)
    assert result.knowledge_bases[0].resource_tenant_id == ASSET_OWNER_TENANT_ID
    assert s.opened == [False] and s.closed == [True]


@pytest.mark.parametrize('ids', [[2], [5], [6], [99]])
def test_other_private_foreign_datamate_and_missing_are_rejected(boundary, ids):
    with pytest.raises(ScopeDenied):
        invoke(boundary, ids)
    assert boundary.closed == [True]


def test_su_can_describe_foreign_shared_but_still_cannot_read_another_private_kb(boundary):
    s = boundary
    s.member['user_roles'] = ['SU']
    assert invoke(s, [5]).knowledge_bases[0].resource_tenant_id == 'tenant-b'
    assert s.opened == [True]
    with pytest.raises(ScopeDenied):
        invoke(s, [2])


def test_inventory_is_own_tenant_metadata_only_with_live_si_permission(boundary):
    s = boundary
    s.member['user_roles'] = ['OPS']
    assert invoke(s, [2], 'inventory').knowledge_bases[0].knowledge_id == 2
    with pytest.raises(ScopeDenied):
        invoke(s, [2])
    with pytest.raises(ScopeDenied):
        invoke(s, [5], 'inventory')
    with s.engine.begin() as conn:
        conn.execute(permissions_table.delete())
    with pytest.raises(ScopeDenied):
        invoke(s, [2], 'inventory')


@pytest.mark.parametrize('roles', [['DEV'], ['ADMIN'], ['SU'], ['OPS', 'ADMIN'], ['OPS', 'SU']])
def test_inventory_cannot_bypass_the_public_view_role_rules(boundary, roles):
    s = boundary
    s.member['user_roles'] = roles
    with pytest.raises(ScopeDenied):
        invoke(s, [2], 'inventory')
    assert not s.opened


def test_multi_role_inventory_and_normal_visibility_are_separate(boundary):
    s = boundary
    s.member['user_roles'] = ['DEV', 'OPS']
    assert invoke(s, [2], 'inventory').knowledge_bases[0].knowledge_id == 2
    with pytest.raises(ScopeDenied):
        invoke(s, [2])


def test_metadata_retains_active_deleting_directory_without_granting_edit(boundary):
    s = boundary
    with s.engine.begin() as conn:
        conn.execute(knowledge.update().where(knowledge.c.knowledge_id == 1).values(deletion_request={'pending': True}))
    assert invoke(s, [1]).knowledge_bases[0].knowledge_id == 1


def test_bad_scope_or_unavailable_identity_never_opens_resource_catalog(boundary):
    s = boundary
    s.identity.scope.actor_id = 'other'
    with pytest.raises(ScopeDenied):
        invoke(s, [1])
    s.identity_read.assert_not_called()
    s.identity.scope.actor_id = s.actor.user_id
    s.identity_read.side_effect = ScopeDenied()
    with pytest.raises(ScopeDenied):
        invoke(s, [1])
    assert not s.opened


def test_duplicate_physical_namespace_is_rejected_before_runtime(boundary):
    s = boundary
    with s.engine.begin() as conn:
        conn.execute(knowledge.update().where(knowledge.c.knowledge_id == 3).values(index_name='kb-1'))
    with pytest.raises(ScopeDenied):
        invoke(s, [1, 3])
