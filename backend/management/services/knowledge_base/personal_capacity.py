# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compose the actor's PRIVATE capacity from SI accounting and AgentOS scalars."""

import asyncio
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.constants import environment
from management.services.knowledge_base.collection_statistics import (
    collection_usage_statistics,
)
from management.services.knowledge_base.personal_capacity_read import (
    PersonalCapacityReader,
)
from management.services.knowledge_base.quota_formatting import (
    bytes_to_readable,
    vector_bytes_for_display,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded
from nexent.storage.models import OperationContext

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient

logger = logging.getLogger(__name__)


class PersonalSelfCapacity:
    def __init__(self, *, reader=None, client=None):
        self.reader = reader if reader is not None else PersonalCapacityReader()
        self.client = client if client is not None else AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)

    async def read(self, actor, *, context):
        inputs = await run_blocking('personal-capacity-inputs', self.reader.read_self, actor, context=context,
                                   lane='control-io', owner='management.knowledge_base')
        rows = inputs['knowledge_bases']
        # Legacy projection overwrites each index with its last catalog entry.
        indexed = {row['index_name']: row for row in rows if row.get('index_name')}
        observed = await collection_usage_statistics(self.client, actor, list(indexed.values()), context, include_datamate=True)
        sizes = {index: vector_bytes_for_display(observed[row['knowledge_id']].size_bytes)
                 if observed.get(row['knowledge_id']) is not None else 0 for index, row in indexed.items()}
        es_bytes = sum(sizes.get(row.get('index_name'), 0) for row in rows)
        used, quota = inputs['personal_bytes'], inputs['quota_bytes']
        rate = None if quota is None else (100.0 if quota <= 0 and used > 0 else round(used / quota * 100, 2) if quota > 0 else 0.0)
        await run_blocking('personal-capacity-authorize', self.reader.authorize_self, actor, context=context,
                           lane='control-io', owner='management.knowledge_base')
        context.remaining()
        return {
            'used_bytes': used, 'used_readable': bytes_to_readable(used),
            'es_physical_bytes': es_bytes, 'es_physical_readable': bytes_to_readable(es_bytes),
            'quota_bytes': quota, 'quota_readable': bytes_to_readable(quota),
            'quota_source': inputs['quota_source'], 'usage_rate': rate,
            'is_over_quota': quota is not None and used > quota, 'kb_count': len(rows),
        }


async def personal_self_capacity(actor):
    cancelled = Event()
    context = OperationContext('personal-capacity-' + uuid4().hex, monotonic() + 30, cancelled=cancelled)
    try:
        async with asyncio.timeout(context.remaining()):
            return await PersonalSelfCapacity().read(actor, context=context)
    except (TimeoutError, DeadlineExceeded) as error:
        logger.warning('personal_capacity_timeout operation_id=%s phase=capacity threshold_seconds=30 exception_type=%s',
                       context.operation_id, type(error).__name__)
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        cancelled.set()
