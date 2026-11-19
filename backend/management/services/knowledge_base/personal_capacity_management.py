# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Assemble management-only personal capacity through SI and standard AgentOS."""

import asyncio
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.constants import environment
from management.services.knowledge_base.collection_statistics import (
    collection_usage_statistics,
)
from management.services.knowledge_base.personal_capacity_display import (
    PersonalCapacityDisplay,
)
from management.services.knowledge_base.personal_capacity_projection import (
    kb_details,
    list_users,
    storage_usage,
    summary,
)
from management.services.knowledge_base.personal_capacity_read import (
    PersonalCapacityReader,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded
from nexent.storage.models import OperationContext

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient

logger = logging.getLogger(__name__)


class PersonalCapacityManagement:
    def __init__(self, *, reader=None, display=None, client=None):
        self.reader = reader if reader is not None else PersonalCapacityReader()
        self.display = display if display is not None else PersonalCapacityDisplay()
        self.client = client if client is not None else AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)

    async def _blocking(self, phase, action, *args, context, **kwargs):
        return await run_blocking('personal-management-' + phase, action, *args, context=context,
                                 lane='control-io', owner='management.knowledge_base', **kwargs)

    async def read(self, operation, tenant, actor, *, subject=None, options=None, context):
        if operation not in {'users', 'details', 'summary'}:
            raise ValueError('Unknown personal capacity operation')
        inputs = await self._blocking('inputs', self.reader.read_management, tenant, actor, subject=subject, context=context)
        options = options if options is not None else {}
        if operation == 'users':
            if options.get('sort_by', 'total_bytes') not in {'user_name', 'kb_count', 'total_bytes', 'quota_limit_bytes', 'usage_rate'}:
                raise ValueError('sort_by must be one of user_name, kb_count, total_bytes, quota_limit_bytes, usage_rate')
            if options.get('sort_order', 'desc').lower() not in {'asc', 'desc'}:
                raise ValueError('sort_order must be asc or desc')
        rows = inputs['knowledge_bases']
        indexed = {row['index_name']: row for row in rows if row.get('index_name')}
        observed = await collection_usage_statistics(self.client, actor, list(indexed.values()), context, include_datamate=True)
        # Project the last index's statistics onto every historical alias.
        observed = {row['knowledge_id']: observed.get(indexed[row['index_name']]['knowledge_id'])
                    for row in rows if row.get('index_name')}
        usage = storage_usage(inputs, observed)
        if operation == 'users':
            subjects = sorted({row['created_by'] for row in rows if row['created_by']})
            emails, identities = await self._blocking('display', self.display.read, tenant, actor, subjects, context=context)
            result = list_users(usage, inputs['quotas'], emails, identities, **options)
        elif operation == 'details':
            result = kb_details(usage, **options)
        else:
            result = summary(usage, inputs['quotas'], inputs['default_quota'])
        await self._blocking('authorize', self.reader.authorize_management, tenant, actor, context=context)
        context.remaining()
        return result


async def personal_capacity_operation(operation, tenant, actor, *, subject=None, options=None):
    cancelled = Event()
    context = OperationContext('personal-management-' + uuid4().hex, monotonic() + 30, cancelled=cancelled)
    try:
        async with asyncio.timeout(context.remaining()):
            return await PersonalCapacityManagement().read(operation, tenant, actor, subject=subject, options=options, context=context)
    except (TimeoutError, DeadlineExceeded) as error:
        logger.warning('personal_capacity_management_timeout operation_id=%s phase=capacity threshold_seconds=30 exception_type=%s',
                       context.operation_id, type(error).__name__)
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        cancelled.set()
