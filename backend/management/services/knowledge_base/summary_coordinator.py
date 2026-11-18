# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management executes one admitted automatic summary using standard AgentOS operations."""

import asyncio
import logging
from datetime import UTC, datetime
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.constants.constants import FREQUENCY_MAP
from contracts.knowledge_summary import SUMMARY_MODEL_DATASET
from management.services.knowledge_base.summary_service import KnowledgeSummaryService
from management.services.knowledge_base.summary_settings import (
    authorized_summary_journal,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import OperationContext, PageRequest, RecordQuery

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.knowledge_summary import summary_ports

logger = logging.getLogger(__name__)


def _time(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise InvalidInput()
    return value


def is_due(last_summary_time, frequency, last_doc_update_time, *, now=None):
    """Keep the existing frequency and document-change rule using explicit SI timestamps."""
    interval = FREQUENCY_MAP.get(frequency)
    if interval is None:
        return False
    if last_summary_time is None:
        return True
    last = _time(last_summary_time)
    if (now or datetime.now(UTC)) - last < interval:
        return False
    return last_doc_update_time is None or _time(last_doc_update_time) > last


def _model_id(records, context):
    page = records.query(SUMMARY_MODEL_DATASET, RecordQuery(), PageRequest(limit=2), context=context)
    if len(page.items) > 1 or page.next_cursor:
        raise Conflict()
    if not page.items:
        return None
    value = page.items[0]['config_value']
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


class SummaryCoordinator:
    def __init__(self, *, summary=None, ports=summary_ports):
        self.summary, self.ports = summary or KnowledgeSummaryService(), ports

    async def _records(self, actor, phase, function):
        stop = Event()
        context = OperationContext('knowledge-summary-' + phase + '-' + uuid4().hex,
                                   monotonic() + 10, cancelled=stop)

        def execute():
            context.remaining()
            with self.ports(actor.tenant_id, actor.user_id, context=context, models=True) as (records, resources):
                result = function(authorized_summary_journal(records, resources), records, context)
                context.remaining()
                return result
        try:
            async with asyncio.timeout(context.remaining()):
                return await run_blocking('knowledge-summary-' + phase, execute, lane='control-io', owner='management.knowledge.summary')
        except (TimeoutError, DeadlineExceeded) as error:
            logger.warning('knowledge_summary_records_timeout operation_id=%s phase=%s threshold_seconds=10 exception_type=%s',
                           context.operation_id, phase, type(error).__name__)
            raise DeadlineExceeded(operation_id=context.operation_id) from error
        finally:
            stop.set()

    async def advance(self, candidate):
        actor = ServicePrincipal(candidate['user_id'], candidate['tenant_id'])
        knowledge_id, index_name = candidate['knowledge_id'], candidate['index_name']
        if type(knowledge_id) is not int or knowledge_id <= 0:
            raise InvalidInput()

        def prepare(journal, records, context):
            row = journal.prepare(knowledge_id, context=context)
            if row is None:
                return None
            if row['index_name'] != index_name:
                raise ScopeDenied()
            if not is_due(row['last_summary_time'], row['summary_frequency'], row['last_doc_update_time']):
                return None
            return row, _model_id(records, context)

        prepared = await self._records(actor, 'prepare', prepare)
        if prepared is None:
            return False
        snapshot, model_id = prepared
        sample = await self.summary.sample(index_name, batch_size=200, user_id=actor.user_id, tenant_id=actor.tenant_id)
        if sample.knowledge_id != knowledge_id or sample.embedding_model.model_id != snapshot['embedding_model_id']:
            raise Conflict()

        def admit(journal, records, context):
            if _model_id(records, context) != model_id:
                raise Conflict()
            return journal.admit(snapshot, data_revision=sample.data_revision, knowledge_revision=sample.knowledge_revision,
                                 model_id=model_id, context=context)

        handle = await self._records(actor, 'admit', admit)
        if handle is None:
            return False
        completing = False
        try:
            summary = await self.summary.summarize_sample(sample, user_id=actor.user_id, tenant_id=actor.tenant_id,
                                                          language='zh', model_id=model_id)
            latest = await self.summary.sample(index_name, batch_size=5, user_id=actor.user_id, tenant_id=actor.tenant_id)
            if (latest.knowledge_revision != sample.knowledge_revision or latest.embedding_model != sample.embedding_model
                or latest.knowledge_id != knowledge_id or latest.data_revision != sample.data_revision):
                raise Conflict()

            def complete(journal, records, context):
                if _model_id(records, context) != model_id:
                    raise Conflict()
                journal.complete(handle, summary, data_revision=latest.data_revision, model_id=model_id, context=context)
            completing = True
            await self._records(actor, 'complete', complete)
            return True
        except OutcomeUnknown:
            raise
        except Exception:
            # An interrupted completion may have committed. Never replace that outcome.
            if not completing:
                await self._records(actor, 'fail', lambda journal, records, context:
                    journal.fail(handle, error_code='SUMMARY_FAILED', context=context))
            raise
