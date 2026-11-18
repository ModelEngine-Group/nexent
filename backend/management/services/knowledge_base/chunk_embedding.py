# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Select authorized manual-chunk model IDs through SI and invoke only AgentOS."""

import asyncio
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.errors.exceptions import (
    RuntimeServiceTimeoutError,
    RuntimeServiceUnavailableError,
    RuntimeUpstreamError,
)
from management.clients.model import embed_query
from management.services.knowledge_base.file_reader import KnowledgeFileReader
from nexent.storage.errors import DeadlineExceeded, InvalidInput, ScopeDenied
from nexent.storage.models import OperationContext

logger = logging.getLogger(__name__)


def embed_manual_chunk(index_name, content, actor, *, reader=None, invoke=None, operation_seconds=180):
    if type(operation_seconds) not in {int, float} or not 0 < operation_seconds <= 180:
        raise InvalidInput()
    cancelled = Event()
    context = OperationContext('manual-chunk-embedding-' + uuid4().hex,
                               monotonic() + operation_seconds, cancelled=cancelled)
    try:
        # Resource/DAC failures must prevent writes, rather than becoming model failures.
        try:
            row = (reader or KnowledgeFileReader()).knowledge(index_name, actor, edit=True, context=context)
            context.remaining()
        except (TimeoutError, DeadlineExceeded) as error:
            logger.warning('knowledge_manual_chunk_embedding_timeout operation_id=%s phase=resource threshold_seconds=%s exception_type=%s',
                           context.operation_id, operation_seconds, type(error).__name__)
            raise DeadlineExceeded(operation_id=context.operation_id) from error
        if row['deletion_request'] is not None:
            raise ScopeDenied()
        context.remaining()
        model_id = row['embedding_model_id']
        if type(model_id) is not int or model_id <= 0:
            return None, None

        async def execute():
            async with asyncio.timeout(context.remaining()):
                return await (invoke or embed_query)(model_id=model_id, query=content,
                    user_id=actor.user_id, tenant_id=actor.tenant_id)
        try:
            return model_id, asyncio.run(execute())
        except (TimeoutError, DeadlineExceeded, RuntimeServiceTimeoutError) as error:
            logger.warning('knowledge_manual_chunk_embedding_timeout operation_id=%s phase=model threshold_seconds=%s exception_type=%s',
                           context.operation_id, operation_seconds, type(error).__name__)
        except (RuntimeServiceUnavailableError, RuntimeUpstreamError, ValueError) as error:
            logger.warning('knowledge_manual_chunk_embedding_failed operation_id=%s phase=model exception_type=%s',
                           context.operation_id, type(error).__name__)
        return model_id, None
    finally:
        cancelled.set()
