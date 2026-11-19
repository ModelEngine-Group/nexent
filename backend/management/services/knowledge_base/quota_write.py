# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Manage quota configuration without native repositories or vector services."""

import asyncio
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.knowledge import KEY_PLATFORM_CAPACITY_BYTES, KEY_TENANT_HARD_LIMIT_BYTES
from contracts.roles import has_any_role
from management.services.knowledge_base.platform_quota_read import PlatformQuotaReader
from management.services.knowledge_base.quota_allocation_read import (
    QuotaAllocationReader,
)
from management.services.knowledge_base.quota_allocation_rules import (
    allocation_lock,
    validate_platform_capacity,
    validate_tenant_allocation,
)
from management.services.knowledge_base.quota_authorization import (
    quota_identity_roles,
    require_quota_scope,
)
from management.services.knowledge_base.quota_formatting import bytes_to_readable
from management.services.knowledge_base.quota_rules import (
    hard_limit_values,
    warning_values,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    OperationContext,
    PageRequest,
    RecordQuery,
)

from infrastructure.quota_write import CONFIGS, quota_write_ports

logger = logging.getLogger(__name__)
EDITABLE = 'KB_QUOTA_HARD_LIMIT_EDITABLE'
WARNING = 'KB_QUOTA_WARNING_ENABLED'
WARNING_PCT = 'KB_QUOTA_WARNING_THRESHOLD_PCT'
CRITICAL_PCT = 'KB_QUOTA_CRITICAL_THRESHOLD_PCT'


class QuotaWriteDenied(ScopeDenied):
    def __init__(self, detail):
        self.message = detail
        super().__init__()


class InvalidQuotaWarning(ValueError):
    pass


class QuotaWriter:
    def __init__(self, *, ports=quota_write_ports, allocation=None, platform=None):
        self.ports = ports
        self.allocation = allocation if allocation is not None else QuotaAllocationReader()
        self.platform = platform if platform is not None else PlatformQuotaReader()

    def _authorize(self, identity, actor, tenant, action, context):
        roles = quota_identity_roles(identity, actor, context=context)
        privileged = has_any_role(roles, {'SU', 'ASSET_OWNER'})
        if action in ('hard', 'capacity', 'remove-platform') and not privileged:
            raise QuotaWriteDenied('This operation requires SU or ASSET_OWNER role')
        if not privileged and not has_any_role(roles, {'ADMIN'}):
            raise QuotaWriteDenied('This operation requires ADMIN, SU, or ASSET_OWNER role')
        if action != 'capacity' and tenant != actor.tenant_id and not privileged:
            raise QuotaWriteDenied('Cannot modify quota config for another tenant')
        return privileged

    def _row(self, records, key, context):
        page = records.query(CONFIGS, RecordQuery(where=Comparison('config_key', 'eq', key)),
                             PageRequest(limit=1), context=context)
        return page.items[0] if page.items else None

    def _value(self, records, key, context):
        row = self._row(records, key, context)
        return row['config_value'] if row else None

    def _set(self, records, key, value, actor, context):
        row = self._row(records, key, context)
        if row is None:
            records.create(CONFIGS, {'config_key': key, 'config_value': str(value),
                'user_id': actor.user_id, 'value_type': 'single'}, context=context)
            return
        receipt = records.patch(CONFIGS, row['tenant_config_id'],
            FieldPatch(set_values={'config_value': str(value)}), context=context)
        if not receipt.matched:
            raise Conflict(operation_id=context.operation_id)

    def _delete(self, records, key, context):
        row = self._row(records, key, context)
        if row and not records.delete(CONFIGS, row['tenant_config_id'], context=context).deleted:
            raise Conflict(operation_id=context.operation_id)

    def _configuration(self, records, context):
        return {**hard_limit_values(self._value(records, KEY_TENANT_HARD_LIMIT_BYTES, context),
                                   self._value(records, EDITABLE, context)),
                **warning_values(self._value(records, WARNING, context), self._value(records, WARNING_PCT, context),
                                 self._value(records, CRITICAL_PCT, context))}

    @staticmethod
    def _limit(payload):
        mb = payload.get('hard_limit_mb')
        gb = payload.get('hard_limit_gb')
        if mb is None and gb is None:
            return None
        amount = int(mb if mb is not None else gb)
        if amount < 0:
            raise ValueError(f"{'MB' if mb is not None else 'GB'} value must be non-negative, got {amount}")
        return amount * (1024**2 if mb is not None else 1024**3)

    def run(self, action, tenant, actor, payload, *, context):
        if action not in {'update', 'remove', 'remove-platform', 'capacity', 'hard'}:
            raise ValueError('Unknown quota mutation')
        context.remaining()
        with self.ports(actor, context=context) as (identity, open_records):
            self._authorize(identity, actor, tenant, action, context)
            if not allocation_lock.acquire(timeout=context.remaining()):
                raise DeadlineExceeded(operation_id=context.operation_id)
            try:
                privileged = self._authorize(identity, actor, tenant, action, context)
                target = ASSET_OWNER_TENANT_ID if action == 'capacity' else tenant
                records = open_records(target)
                require_quota_scope(records, actor, target)
                if action == 'capacity':
                    capacity = payload.get('capacity_gb')
                    if capacity is not None:
                        capacity = int(capacity) * 1024**3
                        if capacity < 0:
                            raise ValueError(f'GB value must be non-negative, got {int(payload["capacity_gb"])}')
                        state = self.platform.read(actor, context=context)
                        validate_platform_capacity(capacity, sum(t['hard_limit_bytes'] or 0 for t in state['tenants']))
                    with records.transaction(context=context) as tx:
                        if capacity is None:
                            self._delete(tx, KEY_PLATFORM_CAPACITY_BYTES, context)
                        else:
                            self._set(tx, KEY_PLATFORM_CAPACITY_BYTES, capacity, actor, context)
                        self._authorize(identity, actor, tenant, action, context)
                    return {'capacity_bytes': capacity, 'capacity_readable': bytes_to_readable(capacity)}
                if (action == 'update' and not privileged
                        and (payload.get('hard_limit_mb') is not None or payload.get('hard_limit_gb') is not None)
                        and self._value(records, EDITABLE, context) == 'false'):
                    raise QuotaWriteDenied('Tenant hard quota is managed by the platform administrator')
                limit = self._limit(payload) if action in {'update', 'hard'} else None
                if limit is not None:
                    inputs = self.allocation.read(tenant, actor, context=context)
                    if action == 'update' and not privileged and not inputs['hard_limit_editable']:
                        raise QuotaWriteDenied('Tenant hard quota is managed by the platform administrator')
                    validate_tenant_allocation(tenant, limit, inputs)
                if action in {'remove', 'remove-platform', 'hard'} or limit is not None:
                    with records.transaction(context=context) as tx:
                        if limit is None:
                            self._delete(tx, KEY_TENANT_HARD_LIMIT_BYTES, context)
                            self._delete(tx, EDITABLE, context)
                        else:
                            self._set(tx, KEY_TENANT_HARD_LIMIT_BYTES, limit, actor, context)
                            self._set(tx, EDITABLE, 'false' if privileged else 'true', actor, context)
                        self._authorize(identity, actor, tenant, action, context)
                if action in {'remove', 'remove-platform'}:
                    return True
                if action == 'hard':
                    return {'hard_limit_bytes': limit, 'hard_limit_readable': bytes_to_readable(limit)}
                self._warnings(records, actor, payload, context, identity, tenant)
                result = self._configuration(records, context)
                self._authorize(identity, actor, tenant, action, context)
                return result
            finally:
                allocation_lock.release()

    def _warnings(self, records, actor, payload, context, identity, tenant):
        warning, critical = payload.get('warning_threshold_pct'), payload.get('critical_threshold_pct')
        enabled = payload.get('warning_enabled')
        if all(value is None for value in (warning, critical, enabled)):
            return
        for label, value in (('warning_pct', warning), ('critical_pct', critical)):
            if value is not None and not 1 <= value <= 100:
                raise InvalidQuotaWarning(f'{label} must be 1-100, got {value}')
        current = self._configuration(records, context)
        effective_warning = warning if warning is not None else current['warning_threshold_pct']
        effective_critical = critical if critical is not None else current['critical_threshold_pct']
        if effective_warning is not None and effective_critical is not None and effective_warning >= effective_critical:
            raise InvalidQuotaWarning(f'warning_threshold_pct ({effective_warning}) must be lower than '
                                      f'critical_threshold_pct ({effective_critical})')
        with records.transaction(context=context) as tx:
            for key, value in ((WARNING_PCT, warning), (CRITICAL_PCT, critical),
                               (WARNING, str(enabled).lower() if enabled is not None else None)):
                if value is not None:
                    self._set(tx, key, value, actor, context)
            self._authorize(identity, actor, tenant, 'update', context)


async def write_quota(action, tenant, actor, payload):
    cancelled = Event()
    context = OperationContext('quota-write-' + uuid4().hex, monotonic() + 30, cancelled=cancelled)
    try:
        async with asyncio.timeout(context.remaining()):
            return await run_blocking('quota-write', QuotaWriter().run, action, tenant, actor, payload,
                                      context=context, lane='control-io', owner='management.quota')
    except (TimeoutError, DeadlineExceeded) as error:
        logger.warning('quota_write_timeout operation_id=%s phase=configuration threshold_seconds=30 exception_type=%s',
                       context.operation_id, type(error).__name__)
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        cancelled.set()
