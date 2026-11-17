# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Persist the actual user who changes summary settings through current SI edit authorization."""

import asyncio
import logging
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from management.services.knowledge_base.summary_schedule import SummaryScheduleJournal
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded
from nexent.storage.models import OperationContext

from infrastructure.knowledge_search import knowledge_search_revision
from infrastructure.knowledge_summary import summary_ports

logger = logging.getLogger(__name__)


def authorized_summary_journal(records, resources):
    def authorize(row, *, context):
        resource = KnowledgeFileAuthorization(resources, user_id=records.scope.actor_id).resolve_knowledge(
            row['knowledge_id'], edit=True, context=context)
        return SimpleNamespace(knowledge_id=resource['knowledge_id'], collection=resource['index_name'],
                               revision=knowledge_search_revision(resource))
    return SummaryScheduleJournal(records, authorize=authorize)


async def configure_summary_schedule(index_name, summary_frequency, tenant_id, user_id, *, context=None):
    context = context or OperationContext('knowledge-summary-settings-' + uuid4().hex, monotonic() + 10)
    threshold = max(0.0, context.deadline - monotonic())
    def configure():
        context.remaining()
        with summary_ports(tenant_id, user_id, context=context) as (records, resources):
            authorized_summary_journal(records, resources).configure(index_name, summary_frequency, context=context)
    try:
        async with asyncio.timeout(context.remaining()):
            return await run_blocking('knowledge-summary-settings', configure, lane='control-io', owner='management.knowledge.summary')
    except (TimeoutError, DeadlineExceeded) as error:
        logger.warning('knowledge_summary_settings_timeout operation_id=%s phase=records threshold_seconds=%s exception_type=%s',
                       context.operation_id, threshold, type(error).__name__)
        raise DeadlineExceeded(operation_id=context.operation_id) from error
