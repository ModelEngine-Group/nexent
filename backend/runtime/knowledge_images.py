# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Actor-bound KB image sources using the shared Runtime CLIP/size decision."""

import asyncio
import logging
from time import monotonic
from uuid import uuid4

from contracts.agentos_knowledge import KnowledgeContentRequest
from contracts.errors.exceptions import RuntimeUpstreamError
from nexent.core.concurrency import get_current_thread_manager
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.concurrency.errors import ThreadManagerError
from nexent.multi_modal.image_codec import decode_image_bytes
from nexent.storage.errors import StorageError
from nexent.storage.models import OperationContext
from runtime.images import web_image_filter
from runtime.knowledge_base.content import KnowledgeContentReader

logger = logging.getLogger(__name__)


class KnowledgeImageFilter:
    def __init__(self, actor, client, *, selector=None):
        self.actor = actor
        self.reader = KnowledgeContentReader(client, actor)
        self.selector = web_image_filter() if selector is None else selector

    def __call__(self, references, query, *, cancellation_scope=None):
        manager = get_current_thread_manager()
        if manager is None:
            raise RuntimeError("KB image filtering requires managed tool execution")
        if any(
            not isinstance(ref, KnowledgeContentRequest) or ref.image_ref is None
            for ref in references
        ):
            raise ValueError(
                "KB image filtering requires pinned file and image references"
            )

        async def execute():
            loop, task = asyncio.get_running_loop(), asyncio.current_task()
            token = None
            if cancellation_scope is not None:
                if cancellation_scope.cancelled:
                    raise RunTerminated()
                token = cancellation_scope.register_closer(
                    lambda: loop.call_soon_threadsafe(task.cancel)
                )

            decoded = set()

            async def load(session, reference):
                try:
                    raw, _ = await self.reader.read(
                        reference,
                        context=OperationContext(
                            "kb-image-" + uuid4().hex,
                            monotonic() + self.selector.image_seconds,
                        ),
                    )
                except (
                    RuntimeUpstreamError,
                    StorageError,
                    ThreadManagerError,
                ) as error:
                    logger.info(
                        "knowledge_image_failed exception_type=%s", type(error).__name__
                    )
                    return None
                image = decode_image_bytes(raw)
                decoded.add(id(reference))
                return image

            try:
                result = await self.selector._filter(
                    references, query, image_loader=load, event_prefix="knowledge_image"
                )
                if cancellation_scope is not None and cancellation_scope.cancelled:
                    raise RunTerminated()
                # Preserve the existing all-empty importance behavior only for verified inputs.
                return (
                    result
                    if result
                    else [ref for ref in references if id(ref) in decoded]
                )
            except asyncio.CancelledError:
                if cancellation_scope is not None and cancellation_scope.cancelled:
                    raise RunTerminated() from None
                raise
            finally:
                if token is not None:
                    cancellation_scope.unregister_closer(token)

        return asyncio.run(execute())
