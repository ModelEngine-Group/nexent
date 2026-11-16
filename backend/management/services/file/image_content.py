# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management owns image-source authorization and bounded preview orchestration."""

import asyncio
from dataclasses import replace
from time import monotonic
from urllib.parse import urlsplit
from uuid import uuid4

from nexent.core.concurrency import (
    ManagedTaskSpec,
    get_current_thread_manager,
    get_default_thread_manager,
)
from nexent.multi_modal.image_codec import encode_image_bytes
from nexent.multi_modal.utils import parse_s3_url
from nexent.storage.errors import DeadlineExceeded
from nexent.storage.models import OperationContext

from infrastructure.file_processing.image_sources import (
    read_inline_or_web_image,
    read_object_image,
)
from infrastructure.object_storage.read_access import validate_s3_url_access


async def fetch_image_content(url, *, user_id=None, tenant_id=None):
    context = OperationContext("image-proxy-" + uuid4().hex, monotonic() + 5)
    manager = get_current_thread_manager() or get_default_thread_manager()
    if manager is None:
        raise RuntimeError("Image proxy requires a service-owned ThreadManager")
    try:
        async with asyncio.timeout(context.remaining()):
            if urlsplit(url).scheme.lower() == "s3":
                _, key = parse_s3_url(url)
                validate_s3_url_access(key, user_id, tenant_id)
                data = None
            else:
                data = await read_inline_or_web_image(url, context=context)

            def render(cancel_event):
                bound = replace(context, cancelled=cancel_event)
                bound.remaining()
                raw = data if data is not None else read_object_image(
                    url, user_id=user_id, tenant_id=tenant_id, context=bound,
                )
                bound.remaining()
                result = encode_image_bytes(raw)
                bound.remaining()
                return result

            return await manager.run(
                "control-io",
                ManagedTaskSpec(
                    task_name="image-proxy", owner="management.image",
                    deadline_monotonic=context.deadline, pass_cancel_event=True,
                ),
                render,
            )
    except DeadlineExceeded as error:
        raise TimeoutError("Image proxy deadline exceeded") from error
