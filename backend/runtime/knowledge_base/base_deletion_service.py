# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""One bounded standard AgentOS request; uncertain collection removal is never replayed."""

import asyncio
import logging
from dataclasses import replace
from time import monotonic
from uuid import uuid4

from contracts.errors.exceptions import RuntimeServiceTimeoutError
from contracts.knowledge_base_deletion import (
    KnowledgeBaseDelete,
    KnowledgeBaseDeleteAuthorization,
    KnowledgeBaseDeleteLookup,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import DeleteReceipt, OperationContext, WriteOutcome
from runtime.knowledge_base.base_deletion import KnowledgeBaseDeletionJournal
from runtime.knowledge_base.worker import cancellable_context

from infrastructure.knowledge_base_deletion import knowledge_base_deletion_ports

logger = logging.getLogger(__name__)


class KnowledgeBaseDeletionService:
    def __init__(self, client, *, ports=knowledge_base_deletion_ports, operation_seconds=10):
        if type(operation_seconds) not in {int, float} or not 0 < operation_seconds <= 30:
            raise InvalidInput()
        self.client, self.ports, self.seconds = client, ports, operation_seconds

    async def delete(self, request, actor, *, context=None):
        if not isinstance(request, KnowledgeBaseDelete):
            raise InvalidInput()
        return await self._dispatch(request, actor, context)

    async def inspect(self, request, actor, *, context=None):
        if not isinstance(request, KnowledgeBaseDeleteLookup):
            raise InvalidInput()
        return await self._dispatch(request, actor, context)

    async def _grant(self, request, actor):
        grant = await self.client.authorize_knowledge_base_deletion(
            KnowledgeBaseDeleteAuthorization(knowledge_id=request.knowledge_id), actor.user_id, actor.tenant_id,
        )
        if grant.knowledge_id != request.knowledge_id:
            raise ScopeDenied()
        return grant

    async def _blocking(self, fn, *args):
        return await run_blocking('knowledge-base-deletion', fn, *args, lane='control-io', owner='runtime.knowledge_base')

    def _prepare(self, request, actor, grant, context):
        with self.ports(actor, grant, context=context) as (records, _):
            journal = KnowledgeBaseDeletionJournal(records, actor, grant)
            return (journal.reserve(request, context=context) if isinstance(request, KnowledgeBaseDelete)
                    else (journal.record(request, context=context), False))

    def _physical(self, row, owner, actor, grant, context):
        with self.ports(actor, grant, context=context) as (records, vectors):
            journal = KnowledgeBaseDeletionJournal(records, actor, grant)
            journal.ready(records, context=context)
            if owner:
                receipt = vectors.delete_empty_collection(grant.collection, context=context)
                if (not isinstance(receipt, DeleteReceipt) or receipt.outcome is not WriteOutcome.CONFIRMED
                        or type(receipt.deleted) is not bool):
                    raise OutcomeUnknown(operation_id=context.operation_id)
                return True
            exists = vectors.collection_exists(grant.collection, context=context)
            if type(exists) is not bool:
                raise OutcomeUnknown(operation_id=context.operation_id)
            return not exists

    def _finish(self, row, actor, grant, context):
        with self.ports(actor, grant, context=context) as (records, _):
            return KnowledgeBaseDeletionJournal(records, actor, grant).finish(
                row, physical_absence_confirmed=True, context=context,
            )

    async def _dispatch(self, request, actor, context):
        context = context or OperationContext('kb-collection-' + uuid4().hex, monotonic() + self.seconds)
        context, stopped = cancellable_context(replace(context, deadline=min(context.deadline, monotonic() + self.seconds)))
        try:
            async with asyncio.timeout(context.remaining()):
                grant = await self._grant(request, actor)
                row, owner = await self._blocking(self._prepare, request, actor, grant, context)
                if row['status'] == 'deleted':
                    return KnowledgeBaseDeletionJournal.state(row)
                absent = await self._blocking(self._physical, row, owner, actor, grant, context)
                if not absent:
                    return KnowledgeBaseDeletionJournal.state(row)
                if await self._grant(request, actor) != grant:
                    raise Conflict()
                return await self._blocking(self._finish, row, actor, grant, context)
        except RuntimeServiceTimeoutError as error:
            raise DeadlineExceeded(operation_id=context.operation_id) from error
        except (TimeoutError, DeadlineExceeded) as error:
            logger.warning('knowledge_base_deletion_timeout operation_id=%s threshold_seconds=%s error_type=%s',
                           context.operation_id, self.seconds, type(error).__name__)
            raise DeadlineExceeded(operation_id=context.operation_id) from error
        finally:
            stopped.set()
