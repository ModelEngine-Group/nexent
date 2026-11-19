# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read or write personal quota configuration with current scoped SI authorization."""

import asyncio
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

from management.services.knowledge_base.personal_capacity_access import (
    PersonalCapacityAccess,
)
from management.services.knowledge_base.personal_capacity_read import (
    PersonalCapacityReader,
)
from management.services.knowledge_base.quota_authorization import require_quota_scope
from management.services.knowledge_base.quota_config_records import (
    QuotaConfigurationRecords,
)
from management.services.knowledge_base.quota_formatting import bytes_to_readable
from management.services.knowledge_base.quota_rules import (
    check_user_quota_allocation,
    parse_personal_quota,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded
from nexent.storage.models import OperationContext

from infrastructure.personal_capacity import personal_capacity_ports

logger = logging.getLogger(__name__)
DEFAULT_KEY = 'PERSONAL_KB_QUOTA_DEFAULT'


class InvalidPersonalQuotaPayload(ValueError):
    pass


class PersonalQuotaConfiguration(QuotaConfigurationRecords, PersonalCapacityAccess):
    def __init__(self, *, ports=personal_capacity_ports, usage_reader=None):
        self.ports = ports
        self.usage_reader = usage_reader

    def run(self, operation, tenant, actor, payload, *, context):
        if operation not in ('read', 'write', 'user-write'):
            raise ValueError('Unknown personal quota configuration operation')
        writable = operation != 'read'
        context.remaining()
        with self.ports(actor, context=context, writable=writable) as (identity, permissions, open_records):
            self._authorize(identity, permissions, actor, tenant, writable, context)
            if writable and payload.get('quota_limit_bytes') is None and not payload.get('unlimited'):
                raise InvalidPersonalQuotaPayload('Provide quota_limit_bytes or unlimited=true')
            subject = payload['subject_user_id'] if operation == 'user-write' else None
            key = 'PERSONAL_KB_QUOTA_' + subject if subject is not None else DEFAULT_KEY
            records = open_records(tenant)
            require_quota_scope(records, actor, tenant)
            if writable:
                value = None if payload.get('unlimited') or payload.get('quota_limit_bytes') is None else int(payload['quota_limit_bytes'])
                if operation == 'user-write' and value is not None:
                    reader = self.usage_reader if self.usage_reader is not None else PersonalCapacityReader()
                    usage = reader.read(tenant, actor, subject, strict=False, context=context)
                    check_user_quota_allocation(value, usage['personal_bytes'])
                with records.transaction(context=context) as tx:
                    if value is None:
                        self._delete(tx, key, context)
                    else:
                        self._set(tx, key, value, actor, context)
                    self._authorize(identity, permissions, actor, tenant, writable, context)
            else:
                value = parse_personal_quota(self._value(records, DEFAULT_KEY, context))
                self._authorize(identity, permissions, actor, tenant, writable, context)
            context.remaining()
            result = {'quota_limit_bytes': value, 'quota_limit_readable': bytes_to_readable(value)}
            if operation == 'user-write':
                return {'user_id': subject, **result}
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
