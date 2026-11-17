# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime content reads use live signed grants and scoped StorageInterface ports."""

import asyncio
import logging

from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded, ScopeDenied

from infrastructure.knowledge_content import read_knowledge_content

logger = logging.getLogger(__name__)


class KnowledgeContentReader:
    def __init__(self, client, actor):
        self.client, self.actor = client, actor

    async def read(self, request, *, context):
        try:
            async with asyncio.timeout(context.remaining()):
                grant = await self.client.authorize_knowledge_content(
                    request, self.actor.user_id, self.actor.tenant_id
                )
                if any(
                    getattr(grant, field) != getattr(request, field)
                    for field in (
                        "knowledge_id",
                        "file_id",
                        "file_version",
                        "image_ref",
                    )
                ):
                    raise ScopeDenied()
                data = await run_blocking(
                    "knowledge-content",
                    read_knowledge_content,
                    self.actor,
                    grant,
                    context=context,
                    lane="control-io",
                    owner="runtime.knowledge_base",
                )
                current = await self.client.authorize_knowledge_content(
                    request, self.actor.user_id, self.actor.tenant_id
                )
                if current != grant:
                    raise ScopeDenied()
                context.remaining()
                return data, grant.filename
        except (TimeoutError, DeadlineExceeded) as error:
            logger.warning(
                "knowledge_content_timeout operation_id=%s phase=read exception_type=%s",
                context.operation_id,
                type(error).__name__,
            )
            raise TimeoutError("Knowledge content deadline exceeded") from error
