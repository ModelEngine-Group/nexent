# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management serves authorized KB references without exposing storage locations."""

import asyncio
import logging
from time import monotonic
from uuid import uuid4

from contracts.agentos_knowledge import KnowledgeLegacyImageRequest
from management.services.knowledge_base.content_authorization import (
    authorize_knowledge_content,
)
from management.services.knowledge_base.legacy_image import fetch_legacy_image
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded, ScopeDenied
from nexent.storage.models import OperationContext

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.knowledge_content import read_knowledge_content

logger = logging.getLogger(__name__)
CONTENT_SECONDS = 10


def _fetch(request, actor, *, context):
    context.remaining()
    if isinstance(request, KnowledgeLegacyImageRequest):
        return fetch_legacy_image(request, actor, context=context)
    grant = authorize_knowledge_content(request, actor, context=context)
    data = read_knowledge_content(actor, grant, role="management", context=context)
    current = authorize_knowledge_content(request, actor, context=context)
    if current != grant:
        raise ScopeDenied()
    context.remaining()
    return data, grant.filename


async def fetch_knowledge_content(request, *, user_id, tenant_id):
    context = OperationContext(
        "knowledge-content-" + uuid4().hex, monotonic() + CONTENT_SECONDS
    )
    try:
        async with asyncio.timeout(context.remaining()):
            return await run_blocking(
                "knowledge-content",
                _fetch,
                request,
                ServicePrincipal(user_id, tenant_id),
                context=context,
                lane="control-io",
                owner="management.knowledge_base",
            )
    except (TimeoutError, DeadlineExceeded) as error:
        logger.warning(
            "knowledge_content_timeout operation_id=%s phase=read threshold_seconds=%s exception_type=%s",
            context.operation_id,
            CONTENT_SECONDS,
            type(error).__name__,
        )
        raise TimeoutError("Knowledge content deadline exceeded") from error
