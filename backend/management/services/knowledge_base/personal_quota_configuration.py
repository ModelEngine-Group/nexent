# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read or write default personal quota with current scoped SI authorization."""

import asyncio
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.constants.constants import (
    PERSONAL_KB_CAPACITY_MANAGE_PERMISSION,
    PERSONAL_KB_CAPACITY_READ_PERMISSION,
)
from contracts.roles import has_any_role
from management.services.knowledge_base.quota_authorization import (
    quota_identity_roles,
    require_quota_scope,
)
from management.services.knowledge_base.quota_config_records import (
    QuotaConfigurationRecords,
)
from management.services.knowledge_base.quota_formatting import bytes_to_readable
from management.services.knowledge_base.quota_rules import parse_personal_quota
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded, ScopeDenied
from nexent.storage.models import Comparison, Junction, OperationContext, RecordQuery

from infrastructure.knowledge_collection_metadata import PERMISSIONS
from infrastructure.personal_quota_configuration import (
    personal_quota_configuration_ports,
)

logger = logging.getLogger(__name__)
DEFAULT_KEY = 'PERSONAL_KB_QUOTA_DEFAULT'


class PersonalQuotaDenied(ScopeDenied):
    def __init__(self, detail):
        self.message = detail
        super().__init__()


class InvalidPersonalQuotaPayload(ValueError):
    pass


class PersonalQuotaConfiguration(QuotaConfigurationRecords):
    def __init__(self, *, ports=personal_quota_configuration_ports):
        self.ports = ports

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

    def run(self, operation, tenant, actor, payload, *, context):
        if operation not in ('read', 'write'):
            raise ValueError('Unknown personal quota configuration operation')
        writable = operation == 'write'
        context.remaining()
        with self.ports(actor, context=context, writable=writable) as (identity, permissions, open_records):
            self._authorize(identity, permissions, actor, tenant, writable, context)
            if writable and payload.get('quota_limit_bytes') is None and not payload.get('unlimited'):
                raise InvalidPersonalQuotaPayload('Provide quota_limit_bytes or unlimited=true')
            records = open_records(tenant)
            require_quota_scope(records, actor, tenant)
            if writable:
                value = None if payload.get('unlimited') or payload.get('quota_limit_bytes') is None else int(payload['quota_limit_bytes'])
                with records.transaction(context=context) as tx:
                    if value is None:
                        self._delete(tx, DEFAULT_KEY, context)
                    else:
                        self._set(tx, DEFAULT_KEY, value, actor, context)
                    self._authorize(identity, permissions, actor, tenant, writable, context)
            else:
                value = parse_personal_quota(self._value(records, DEFAULT_KEY, context))
                self._authorize(identity, permissions, actor, tenant, writable, context)
            context.remaining()
            result = {'quota_limit_bytes': value, 'quota_limit_readable': bytes_to_readable(value)}
            return result if writable else {**result, 'unlimited': value is None}


async def personal_quota_configuration(operation, tenant, actor, payload=None):
    cancelled = Event()
    context = OperationContext('personal-quota-config-' + uuid4().hex, monotonic() + 30, cancelled=cancelled)
    try:
        async with asyncio.timeout(context.remaining()):
            return await run_blocking('personal-quota-config', PersonalQuotaConfiguration().run, operation, tenant, actor,
                payload if payload is not None else {}, context=context, lane='control-io', owner='management.quota')
    except (TimeoutError, DeadlineExceeded) as error:
        logger.warning('personal_quota_config_timeout operation_id=%s phase=configuration threshold_seconds=30 exception_type=%s',
                       context.operation_id, type(error).__name__)
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        cancelled.set()
