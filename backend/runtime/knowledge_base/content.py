# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime content reads use live signed grants and scoped StorageInterface ports."""

import asyncio
import logging
from dataclasses import replace
from threading import Event

from contracts.agentos_knowledge import KnowledgeLegacyImageRequest
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded, ScopeDenied

from infrastructure.knowledge_content import (
    read_knowledge_content,
    read_legacy_attachment,
)

logger = logging.getLogger(__name__)


class KnowledgeContentReader:
    def __init__(self, client, actor):
        self.client, self.actor = client, actor

    async def read(self, request, *, context):
        owned_cancel = Event() if context.cancelled is None else None
        read_context = (
            replace(context, cancelled=owned_cancel)
            if owned_cancel is not None
            else context
        )
        try:
            async with asyncio.timeout(context.remaining()):
                if isinstance(request, KnowledgeLegacyImageRequest):
                    return await self._read_legacy(request, context=read_context)
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
                    context=read_context,
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
        finally:
            if owned_cancel is not None:
                owned_cancel.set()

    async def _read_legacy(self, request, *, context):
        authorize = self.client.authorize_legacy_knowledge_image
        identity = (self.actor.user_id, self.actor.tenant_id)
        if await authorize(request, *identity) != request:
            raise ScopeDenied()
        data = await run_blocking("legacy-knowledge-content", read_legacy_attachment, self.actor, request,
                                  context=context, role="runtime", lane="control-io", owner="runtime.knowledge_base")
        if await authorize(request, *identity) != request:
            raise ScopeDenied()
        context.remaining()
        return data, request.image_ref.key.rsplit("/", 1)[-1]
