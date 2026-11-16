# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Actor-bound KB image sources using the shared Runtime CLIP/size decision."""

import asyncio
import base64
import logging
from time import monotonic
from urllib.parse import urlsplit
from uuid import uuid4

from nexent.core.concurrency import ManagedTaskSpec, get_current_thread_manager
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.concurrency.errors import ThreadManagerError
from nexent.multi_modal.image_codec import decode_image_bytes
from nexent.multi_modal.utils import parse_s3_url
from nexent.storage.errors import DeadlineExceeded, StorageError
from nexent.storage.models import OperationContext
from runtime.images import web_image_filter

from infrastructure.file_processing.image_sources import read_object_image
from infrastructure.object_storage.read_access import validate_s3_url_access
from infrastructure.web_images import load_web_image

logger = logging.getLogger(__name__)


class KnowledgeImageFilter:
    def __init__(self, actor, *, selector=None):
        self.actor = actor
        self.selector = web_image_filter() if selector is None else selector

    def __call__(self, urls, query, *, cancellation_scope=None):
        manager = get_current_thread_manager()
        if manager is None:
            raise RuntimeError("KB image filtering requires managed tool execution")

        async def execute():
            loop, task = asyncio.get_running_loop(), asyncio.current_task()
            token = None
            if cancellation_scope is not None:
                if cancellation_scope.cancelled:
                    raise RunTerminated()
                token = cancellation_scope.register_closer(lambda: loop.call_soon_threadsafe(task.cancel))

            async def load(session, url):
                if urlsplit(url).scheme.lower() != "s3":
                    if url.startswith("data:image"):
                        return decode_image_bytes(base64.b64decode(url.split(",", 1)[1]))
                    return await load_web_image(session, url)
                _, key = parse_s3_url(url)
                validate_s3_url_access(key, self.actor.user_id, self.actor.tenant_id)
                deadline = monotonic() + self.selector.image_seconds

                def read(cancel_event):
                    context = OperationContext("kb-image-" + uuid4().hex, deadline, cancelled=cancel_event)
                    return read_object_image(url, user_id=self.actor.user_id, tenant_id=self.actor.tenant_id,
                                             role="runtime", context=context)

                try:
                    raw = await manager.run(
                        "control-io", ManagedTaskSpec(task_name="kb-image-source", owner="runtime.knowledge",
                                                      deadline_monotonic=deadline, pass_cancel_event=True), read,
                    )
                except DeadlineExceeded as error:
                    raise TimeoutError("KB image deadline exceeded") from error
                except (StorageError, ThreadManagerError) as error:
                    logger.info("knowledge_image_failed exception_type=%s", type(error).__name__)
                    return None
                return decode_image_bytes(raw)

            try:
                result = await self.selector._filter(urls, query, image_loader=load, event_prefix="knowledge_image")
                if cancellation_scope is not None and cancellation_scope.cancelled:
                    raise RunTerminated()
                return result
            except asyncio.CancelledError:
                if cancellation_scope is not None and cancellation_scope.cancelled:
                    raise RunTerminated() from None
                raise
            finally:
                if token is not None:
                    cancellation_scope.unregister_closer(token)

        return asyncio.run(execute())
