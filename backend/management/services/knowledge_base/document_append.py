# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authorize synchronous document appends and project confirmed batch counts."""

import asyncio
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.agentos_knowledge import ModelVersion
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeServiceTimeoutError
from contracts.knowledge_documents import (
    KnowledgeDocumentsAppend,
    KnowledgeDocumentsAppended,
)
from management.services.knowledge_base.chunks_authorization import (
    chunks_resource_grant,
)
from management.services.knowledge_base.file_reader import KnowledgeFileReader
from management.services.knowledge_base.summary_schedule import SummaryScheduleJournal
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, DeadlineExceeded, InvalidInput, ScopeDenied
from nexent.storage.models import OperationContext

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient
from infrastructure.knowledge_summary import summary_ports

logger = logging.getLogger(__name__)


def _touch_activity(index_name, grant, actor, reader, *, context):
    def authorize(row, *, context):
        current = chunks_resource_grant(reader.knowledge(index_name, actor, edit=True, context=context))
        if current != grant:
            raise Conflict()
        return current

    with summary_ports(grant.resource_tenant_id, actor.user_id, context=context) as (records, _):
        if (records.scope.actor_id != actor.user_id or records.scope.tenant_id != grant.resource_tenant_id
            or records.scope.service_role != "management" or records.scope.system):
            raise ScopeDenied()
        SummaryScheduleJournal(records, authorize=authorize).touch_documents(grant.knowledge_id, context=context)


async def append_documents(index_name, documents, actor, *, reader=None, client=None, operation_seconds=180,
                           context=None, embedding_batch_size=None, model_binding=None):
    if not isinstance(documents, (list, tuple)):
        raise InvalidInput()
    if not documents:
        return 0
    if type(operation_seconds) not in {int, float} or not 0 < operation_seconds <= 180:
        raise InvalidInput()
    if embedding_batch_size is not None and (type(embedding_batch_size) is not int or embedding_batch_size <= 0):
        raise InvalidInput()
    if model_binding is not None:
        if not isinstance(model_binding, ModelVersion):
            raise InvalidInput()
        model_binding = ModelVersion.model_validate(model_binding.model_dump())
    cancelled = Event() if context is None else None
    context = context or OperationContext("knowledge-document-append-" + uuid4().hex,
                                         monotonic() + operation_seconds, cancelled=cancelled)
    reader = reader or KnowledgeFileReader()
    client = client or AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)
    threshold = context.remaining()
    try:
        async with asyncio.timeout(threshold):
            row = await run_blocking("knowledge-document-resource", reader.knowledge, index_name, actor, edit=True,
                                     context=context, lane="control-io", owner="management.knowledge_base")
            grant = chunks_resource_grant(row)
            model_id = row["embedding_model_id"]
            if row["index_name"] != index_name or type(model_id) is not int or model_id <= 0:
                raise InvalidInput()
            if model_binding is not None and model_binding.model_id != model_id:
                raise Conflict()
            indexed = 0
            for offset in range(0, len(documents), 64):
                selected = list(documents[offset:offset + 64])
                request = KnowledgeDocumentsAppend(knowledge_id=grant.knowledge_id, resource_revision=grant.revision,
                    embedding_model=model_binding or {"model_id": model_id}, documents=selected,
                    embedding_batch_size=min(embedding_batch_size, 64) if embedding_batch_size is not None else None)
                result = await client.append_knowledge_documents(request, actor.user_id, actor.tenant_id)
                context.remaining()
                if (not isinstance(result, KnowledgeDocumentsAppended) or result.knowledge_id != grant.knowledge_id
                    or result.total_submitted != len(selected)
                    or result.total_skipped > sum(doc.metadata.get("process_source") == "UniversalImageExtractor" for doc in request.documents)):
                    raise Conflict()
                indexed += result.total_indexed
            try:
                await run_blocking("knowledge-document-activity", _touch_activity, index_name, grant, actor, reader,
                                   context=context, lane="control-io", owner="management.knowledge_base")
            except Exception as error:  # noqa: BLE001 - Preserve the existing optional activity timestamp update.
                logger.warning("knowledge_document_activity_failed operation_id=%s exception_type=%s",
                               context.operation_id, type(error).__name__)
            context.remaining()
            return indexed
    except (TimeoutError, DeadlineExceeded, RuntimeServiceTimeoutError) as error:
        logger.warning("knowledge_document_append_timeout operation_id=%s threshold_seconds=%s exception_type=%s",
                       context.operation_id, threshold, type(error).__name__)
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        if cancelled is not None:
            cancelled.set()
