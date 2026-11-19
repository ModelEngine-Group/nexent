# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Attest list metadata without extending body, write or execution permissions."""

from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.knowledge_collections import (
    KnowledgeCollectionGrant,
    KnowledgeCollectionsAuthorization,
    KnowledgeCollectionsGrant,
)
from contracts.roles import has_any_role, roles_from_record
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import Comparison, Junction, PageRequest, RecordQuery
from permissions.dac import ResourceAccessControl
from permissions.models import Resource

from infrastructure.knowledge_collection_metadata import (
    METADATA,
    PERMISSIONS,
    collection_metadata_ports,
)
from infrastructure.knowledge_search import knowledge_search_revision


def _scope(port, actor):
    scope = port.scope
    if (scope.service_role != 'management' or scope.tenant_id != actor.tenant_id
        or scope.actor_id != actor.user_id or scope.system or scope.resource_prefix):
        raise ScopeDenied()


def authorize_collection_metadata(request, actor, *, context, ports=collection_metadata_ports):
    if type(request) is not KnowledgeCollectionsAuthorization:
        raise ScopeDenied()
    request = KnowledgeCollectionsAuthorization.model_validate(request.model_dump())
    context.remaining()
    with ports(actor, context=context) as (identity, permissions, resources):
        _scope(identity, actor); _scope(permissions, actor)
        member, groups = KnowledgeFileAuthorization(identity, user_id=actor.user_id).identity(context=context)
        if member.get('tenant_id') != actor.tenant_id:
            raise ScopeDenied()
        try:
            roles = roles_from_record(member)
        except ValueError as error:
            raise ScopeDenied() from error
        inventory = request.view == 'inventory'
        if inventory and (has_any_role(roles, {'ADMIN', 'SU'}) or not permissions.count(PERMISSIONS, RecordQuery(where=Junction('and', (
                Comparison('user_role', 'in', list(roles)), Comparison('permission_category', 'eq', 'RESOURCE'),
                Comparison('permission_type', 'eq', 'resource.inventory'), Comparison('permission_subtype', 'eq', 'read'),
            ))), context=context)):
            raise ScopeDenied()
        records = resources(cross_tenant=has_any_role(roles, {'SU'}))
        _scope(records, actor)
        page = records.query(METADATA, RecordQuery(where=Comparison('knowledge_id', 'in', request.knowledge_ids)),
                             PageRequest(limit=len(request.knowledge_ids)), context=context)
        rows = {row['knowledge_id']: row for row in page.items}
        if page.next_cursor or len(page.items) != len(rows) or set(rows) != set(request.knowledge_ids):
            raise ScopeDenied()
        grants = []
        for key in request.knowledge_ids:
            row = {**rows[key], 'tenant_id': rows[key]['resource_tenant_id']}
            if row['knowledge_sources'] != 'elasticsearch':
                raise ScopeDenied()
            if inventory:
                if row['tenant_id'] != actor.tenant_id:
                    raise ScopeDenied()
            else:
                access = ResourceAccessControl.check(Resource(resource_type='knowledge_base', resource_id=row['index_name'],
                    tenant_id=row['tenant_id'], created_by=row['created_by'], group_ids=row['group_ids'],
                    ingroup_permission=row['ingroup_permission'], knowledge_sources=row['knowledge_sources']),
                    user_id=actor.user_id, role=roles, user_groups=groups,
                    user_tenant_id=row['tenant_id'] if has_any_role(roles, {'SU'}) else actor.tenant_id,
                    asset_owner_tenant_id=ASSET_OWNER_TENANT_ID)
                if not access.can_read:
                    raise ScopeDenied()
            grants.append(KnowledgeCollectionGrant(knowledge_id=key, collection=row['index_name'],
                resource_tenant_id=row['tenant_id'], revision=knowledge_search_revision(row),
                embedding_model_id=row['embedding_model_id'] if type(row['embedding_model_id']) is int
                and row['embedding_model_id'] > 0 else None))
        if len({(g.resource_tenant_id, g.collection) for g in grants}) != len(grants):
            raise ScopeDenied()
        context.remaining()
        return KnowledgeCollectionsGrant(knowledge_bases=grants)
