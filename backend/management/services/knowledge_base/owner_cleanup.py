# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""A durable, exact resource authority for an already admitted identity deletion."""

from contracts.errors.exceptions import ForbiddenError
from contracts.knowledge_admission import OWNER_CLEANUP_IDENTITIES as DATASET
from contracts.knowledge_admission import (
    KnowledgeBaseDeletionIntent,
    KnowledgeOwnerCleanup,
)
from contracts.roles import has_any_role, roles_from_record
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import PageRequest, RecordQuery
from permissions.role_assignment import check_managed_target
from pydantic import ValidationError

from infrastructure.knowledge_owner_cleanup import owner_cleanup_identity_ports


def require_private_owner(row, owner_user_id, tenant_id):
    if (row['tenant_id'] != tenant_id or row['created_by'] != owner_user_id
            or row['ingroup_permission'] != 'PRIVATE' or row['knowledge_sources'] != 'elasticsearch'
            or row['delete_flag'] != 'N'):
        raise ScopeDenied()


def authorize_owner_cleanup_admission(row, owner_user_id, purpose, actor, *, context, ports=owner_cleanup_identity_ports):
    if (not isinstance(owner_user_id, str) or not 0 < len(owner_user_id) <= 100
            or purpose not in {'user_deletion', 'tenant_deletion'}):
        raise ScopeDenied()
    require_private_owner(row, owner_user_id, actor.tenant_id)
    with ports(actor, owner_user_id, context=context) as records:
        scope = records.scope
        if (scope.system or scope.service_role != 'management' or scope.actor_id != actor.user_id
                or scope.tenant_id != actor.tenant_id or DATASET not in scope.namespaces):
            raise ScopeDenied()
        page = records.query(DATASET, RecordQuery(), PageRequest(limit=4), context=context)
        issuers = [item for item in page.items if item['user_id'] == actor.user_id]
        owners = [item for item in page.items if item['user_id'] == owner_user_id and item['tenant_id'] == actor.tenant_id]
        if page.next_cursor or len(issuers) != 1 or len(owners) != 1:
            raise ScopeDenied()
        issuer, owner = issuers[0], owners[0]
        if purpose == 'tenant_deletion':
            if not has_any_role(roles_from_record(issuer), {'SU'}):
                raise ScopeDenied()
        elif actor.user_id == owner_user_id:
            if has_any_role(roles_from_record(issuer), {'ADMIN', 'SU'}):
                raise ScopeDenied()
        else:
            try:
                check_managed_target(issuer, owner)
            except ForbiddenError:
                raise ScopeDenied() from None
        return KnowledgeOwnerCleanup(purpose=purpose, owner_user_id=owner_user_id, actor_tenant_id=issuer['tenant_id'])


def has_owner_cleanup_authority(row, user_id, tenant_id):
    raw = row.get('deletion_request')
    if raw is None or isinstance(raw, dict) and raw.get('owner_cleanup') is None:
        return False
    try:
        intent = KnowledgeBaseDeletionIntent.model_validate(raw)
    except ValidationError:
        raise ScopeDenied() from None
    if (intent.owner_cleanup is None or intent.phase == 'deleted' or intent.user_id != user_id
            or intent.knowledge_id != row['knowledge_id'] or intent.index_name != row['index_name']):
        raise ScopeDenied()
    require_private_owner(row, intent.owner_cleanup.owner_user_id, tenant_id)
    return True
