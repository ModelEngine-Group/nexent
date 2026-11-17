# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""One authorized vector cleanup attempt; unknown outcomes are never replayed."""

import asyncio
import logging
from time import monotonic
from uuid import uuid4

from contracts.agentos_knowledge import KnowledgeAuthorizationRequest
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    NotFound,
    OutcomeUnknown,
)
from nexent.storage.models import (
    Comparison,
    DeleteReceipt,
    Junction,
    OperationContext,
    WriteOutcome,
)
from runtime.knowledge_base.composition import knowledge_jobs, require_knowledge_grant
from runtime.knowledge_base.jobs import job_state
from runtime.knowledge_base.worker import (
    cancellable_context,
    knowledge_request,
    read_knowledge_job,
)

from infrastructure.knowledge_runtime import knowledge_deletion_ports

logger = logging.getLogger(__name__)


class KnowledgeDeleteWorker:
    def __init__(self, authorization_client, *, jobs=knowledge_jobs,
                 ports=knowledge_deletion_ports, operation_seconds=300):
        if type(operation_seconds) not in {int, float} or not 0 < operation_seconds <= 3600:
            raise InvalidInput()
        self.client, self.jobs, self.ports = authorization_client, jobs, ports
        self.operation_seconds = operation_seconds

    async def _blocking(self, action, *args, **kwargs):
        return await run_blocking("knowledge-delete-worker", action, *args,
                                  lane="control-io", owner="runtime.knowledge_base", **kwargs)

    async def _job(self, actor, grant, method, *args, context, **kwargs):
        def execute():
            context.remaining()
            with self.jobs(actor, grant, context=context) as jobs:
                return getattr(jobs, method)(*args, context=context, **kwargs)
        return await self._blocking(execute)

    async def _grant(self, request, actor):
        grant = await self.client.authorize_knowledge(KnowledgeAuthorizationRequest(
            knowledge_id=request.knowledge_id, file_id=request.file_id,
            file_version=request.file_version, action="delete",
        ), actor.user_id, actor.tenant_id)
        require_knowledge_grant(request, grant, action="delete")
        return grant

    @staticmethod
    def _remove(vectors, grant, request, context):
        where = Junction("and", (
            Comparison("knowledge_id", "eq", request.knowledge_id),
            Comparison("file_id", "eq", request.file_id),
            Comparison("file_version", "lte", request.file_version),
        ))

        def count():
            try:
                value = vectors.count(grant.collection, where, context=context)
            except NotFound:
                # A count on this exact collection confirms that it does not exist.
                return 0
            if type(value) is not int or not 0 <= value <= 2**31 - 1:
                raise OutcomeUnknown(operation_id=context.operation_id)
            return value

        deleted_count = count()
        if deleted_count == 0:
            return 0
        receipts = vectors.delete(grant.collection, where, context=context)
        if not isinstance(receipts, tuple) or any(
            not isinstance(r, DeleteReceipt) or r.outcome is not WriteOutcome.CONFIRMED
            or type(r.deleted) is not bool for r in receipts
        ):
            raise OutcomeUnknown(operation_id=context.operation_id)
        if count() != 0:
            raise Conflict(operation_id=context.operation_id)
        return deleted_count

    async def process(self, lookup, actor, *, owner_id, context=None):
        context = context or OperationContext("knowledge-delete-" + uuid4().hex,
                                              monotonic() + self.operation_seconds)
        context, cancelled = cancellable_context(context)
        try:
            async with asyncio.timeout(context.remaining()):
                row = await self._blocking(read_knowledge_job, lookup, actor, context=context)
                request = knowledge_request(row, operation="delete")
                if row["status"] == "deleted" or row["write_started"] or row["reconcile_required"]:
                    return job_state(row)
                grant = await self._grant(request, actor)
                handle = await self._job(actor, grant, "begin_delete", lookup,
                                         owner_id=owner_id, context=context)
                if handle is None:
                    return await self._job(actor, grant, "inspect", lookup, context=context)
                with self.ports(actor, grant, context=context) as vectors:
                    deleted_count = await self._blocking(self._remove, vectors, grant, request, context)
                if await self._grant(request, actor) != grant:
                    raise Conflict()
                return await self._job(actor, grant, "finish_delete", handle,
                                       physical_absence_confirmed=True, deleted_count=deleted_count, context=context)
        except BaseException as error:
            cancelled.set()
            if isinstance(error, TimeoutError):
                logger.warning("knowledge_delete_timeout operation_id=%s phase=cleanup", context.operation_id)
                raise DeadlineExceeded(operation_id=context.operation_id) from error
            raise
