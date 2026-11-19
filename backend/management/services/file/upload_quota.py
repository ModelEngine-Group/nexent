# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bound upload quota checks and display statistics without legacy ES calls."""

import asyncio
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.errors.exceptions import QuotaExceededError
from management.services.file.upload_quota_read import UploadQuotaReader
from management.services.knowledge_base.quota_formatting import bytes_to_readable
from management.services.knowledge_base.quota_rules import check_user_capacity
from management.services.knowledge_base.quota_usage import TenantQuotaUsage
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded, ScopeDenied
from nexent.storage.models import OperationContext

logger = logging.getLogger(__name__)


def upload_quota_status(usage, index):
    kb = next((row for row in usage.get('breakdown', []) if row.get('index_name') == index), {})
    return {'quota_status': {
        'warning_enabled': usage.get('warning_enabled', True),
        'tenant_level': {
            'usage_pct': usage.get('usage_pct'), 'warning_level': usage.get('tenant_warning_level', 'normal'),
            'hard_limit_bytes': usage.get('hard_limit_bytes'), 'hard_limit_readable': usage.get('hard_limit_readable'),
            'total_bytes': usage.get('total_bytes'), 'total_readable': usage.get('total_readable'),
            'es_physical_bytes': usage.get('es_physical_bytes'), 'es_physical_readable': usage.get('es_physical_readable'),
        },
        'kb_level': {'usage_pct': kb.get('usage_pct'), 'warning_level': kb.get('kb_warning_level', 'normal')},
    }}


class UploadQuota:
    def __init__(self, actor, storage, *, reader=None, usage=None):
        self.actor, self.storage = actor, storage
        self.reader = reader or UploadQuotaReader()
        self.usage = usage or TenantQuotaUsage()

    async def before(self, pending_bytes):
        return await self._check(pending_bytes, after=False)

    async def after(self):
        return await self._check(0, after=True)

    async def _check(self, pending_bytes, *, after):
        cancelled = Event()
        phase = 'after' if after else 'before'
        context = OperationContext('upload-quota-' + uuid4().hex, monotonic() + 180, cancelled=cancelled)
        try:
            if (not self.actor.user_id or not self.actor.tenant_id or self.actor.tenant_id != self.storage.tenant_id):
                raise ScopeDenied()
            async with asyncio.timeout(context.remaining()):
                inputs = await run_blocking('upload-quota-' + phase, self.reader.read,
                    self.storage.tenant_id, self.actor, context=context, lane='control-io', owner='management.file')
                selected = [row for row in inputs['knowledge_bases'] if row['knowledge_id'] == self.storage.knowledge_id
                            and row['index_name'] == self.storage.index_name and row['tenant_id'] == self.storage.tenant_id]
                if len(selected) != 1:
                    raise ScopeDenied()
                used, limit = inputs['tenant_source_bytes'], inputs['hard_limit_bytes']
                if limit is not None and used + pending_bytes > limit:
                    message = ('Tenant storage limit exceeded after write' if after else
                               f'Tenant storage full: {bytes_to_readable(used + pending_bytes)} exceeds hard limit of {bytes_to_readable(limit)}')
                    raise QuotaExceededError(message, usage_bytes=used, hard_limit_bytes=limit,
                                             exceeded_by_bytes=used + pending_bytes - limit)
                if not after and selected[0]['ingroup_permission'] == 'PRIVATE':
                    check_user_capacity(inputs['personal_bytes'], pending_bytes, inputs['personal_limit'],
                                        inputs['personal_source'], self.actor.user_id)
                _, usage = await self.usage.read(self.storage.tenant_id, self.actor, force_refresh=True,
                                               detail=True, context=context)
                context.remaining()
                return upload_quota_status(usage, self.storage.index_name)
        except (TimeoutError, DeadlineExceeded) as error:
            logger.warning('upload_quota_timeout operation_id=%s phase=%s threshold_seconds=180 exception_type=%s',
                           context.operation_id, phase, type(error).__name__)
            raise DeadlineExceeded(operation_id=context.operation_id) from error
        finally:
            cancelled.set()
