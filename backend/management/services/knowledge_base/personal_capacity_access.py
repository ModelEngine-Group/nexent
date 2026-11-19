# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Current identity and permission rules shared by personal capacity policies."""

from contracts.constants.constants import (
    PERSONAL_KB_CAPACITY_MANAGE_PERMISSION,
    PERSONAL_KB_CAPACITY_READ_PERMISSION,
)
from contracts.roles import has_any_role
from management.services.knowledge_base.quota_authorization import (
    quota_identity_roles,
    require_quota_scope,
)
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import Comparison, Junction, RecordQuery

from infrastructure.knowledge_collection_metadata import PERMISSIONS


class PersonalQuotaDenied(ScopeDenied):
    def __init__(self, detail):
        self.message = detail
        super().__init__()

class PersonalCapacityAccess:
    def _authorize(self, identity, permissions, actor, tenant, writable, context):
        roles = quota_identity_roles(identity, actor, context=context)
        require_quota_scope(permissions, actor, actor.tenant_id)
        permission = PERSONAL_KB_CAPACITY_MANAGE_PERMISSION if writable else PERSONAL_KB_CAPACITY_READ_PERMISSION
        requested = [permission] if writable else [permission, 'resource.inventory:read']
        alternatives = tuple(Junction('and', (Comparison('permission_type', 'eq', item.split(':')[0]),
            Comparison('permission_subtype', 'eq', item.split(':')[1]))) for item in requested)
        if not permissions.count(PERMISSIONS, RecordQuery(where=Junction('and', (
            Comparison('user_role', 'in', list(roles)), Comparison('permission_category', 'eq', 'RESOURCE'),
            Junction('or', alternatives),
        ))), context=context):
            raise PersonalQuotaDenied('Missing required permission: ' + permission)
        if tenant != actor.tenant_id and not has_any_role(roles, {'SU'}):
            raise PersonalQuotaDenied('Cannot access personal KB capacity for another tenant')
