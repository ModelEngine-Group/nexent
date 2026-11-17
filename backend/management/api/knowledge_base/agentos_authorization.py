# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Signed Runtime-to-Management resource authorization; no task side effects."""

import asyncio
import logging
from time import monotonic
from uuid import uuid4

from contracts.agentos import ManagementOperation
from contracts.agentos_knowledge import (
    KnowledgeAuthorizationRequest,
    KnowledgeContentRequest,
    KnowledgeSearchAuthorization,
)
from contracts.knowledge_base_deletion import KnowledgeBaseDeleteAuthorization
from fastapi import APIRouter, HTTPException, Request
from management.api.agentos_request import read_agentos_callback
from management.services.knowledge_base.authorization import authorize_knowledge
from management.services.knowledge_base.base_deletion_authorization import (
    authorize_knowledge_base_deletion,
)
from management.services.knowledge_base.content_authorization import (
    authorize_knowledge_content,
)
from management.services.knowledge_base.search_authorization import (
    authorize_knowledge_search,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded
from nexent.storage.models import OperationContext

from backend.http.server.knowledge_errors import knowledge_error

logger = logging.getLogger(__name__)


def create_knowledge_authorization_router(service=authorize_knowledge, search_service=authorize_knowledge_search,
                                         content_service=authorize_knowledge_content,
                                         base_deletion_service=authorize_knowledge_base_deletion):
    router = APIRouter()

    async def dispatch(request, operation, schema, action):
        context = OperationContext("knowledge-grant-" + uuid4().hex, monotonic() + 10)
        try:
            async with asyncio.timeout(context.remaining()):
                payload, actor = await read_agentos_callback(
                    request,
                    operation,
                    schema,
                    max_bytes=16384,
                )
                return await run_blocking(
                    "agentos-knowledge-authorization",
                    action,
                    payload,
                    actor,
                    context=context,
                    lane="control-io",
                    owner="management.knowledge_base",
                )
        except HTTPException:
            raise
        except TimeoutError:
            logger.warning(
                "knowledge_authorization_timeout operation_id=%s phase=records",
                context.operation_id,
            )
            return knowledge_error(DeadlineExceeded(operation_id=context.operation_id))
        except Exception as error:  # noqa: BLE001 - The HTTP boundary must redact unexpected failures.
            return knowledge_error(error)

    @router.post(ManagementOperation.KNOWLEDGE_AUTHORIZE.value, include_in_schema=False)
    async def authorize(request: Request):
        return await dispatch(request, ManagementOperation.KNOWLEDGE_AUTHORIZE, KnowledgeAuthorizationRequest, service)

    @router.post(ManagementOperation.KNOWLEDGE_SEARCH_AUTHORIZE.value, include_in_schema=False)
    async def authorize_search(request: Request):
        return await dispatch(request, ManagementOperation.KNOWLEDGE_SEARCH_AUTHORIZE, KnowledgeSearchAuthorization, search_service)

    @router.post(ManagementOperation.KNOWLEDGE_CONTENT_AUTHORIZE.value, include_in_schema=False)
    async def authorize_content(request: Request):
        return await dispatch(request, ManagementOperation.KNOWLEDGE_CONTENT_AUTHORIZE, KnowledgeContentRequest, content_service)

    @router.post(ManagementOperation.KNOWLEDGE_BASE_DELETION_AUTHORIZE.value, include_in_schema=False)
    async def authorize_base_deletion(request: Request):
        return await dispatch(request, ManagementOperation.KNOWLEDGE_BASE_DELETION_AUTHORIZE,
                              KnowledgeBaseDeleteAuthorization, base_deletion_service)

    return router
