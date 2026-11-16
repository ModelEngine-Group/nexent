# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Service-owned upload work with one deadline and durable source pinning."""

import asyncio
import math
from time import monotonic
from uuid import uuid4

from management.services.file.source_publish import SourcePublisher
from nexent.core.concurrency import (
    ManagedTaskSpec,
    get_current_thread_manager,
    get_default_thread_manager,
)
from nexent.storage.errors import InvalidInput, OutcomeUnknown
from nexent.storage.models import OperationContext

from infrastructure.source_upload import source_upload_ports


async def upload_knowledge_source(
    record, content, content_type, *, manager=None, timeout=120
):
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise InvalidInput()
    manager = manager or get_current_thread_manager() or get_default_thread_manager()
    if manager is None:
        raise RuntimeError("Source upload requires a service-owned ThreadManager")
    deadline = monotonic() + timeout
    operation_id = "source-upload-" + uuid4().hex

    def run(cancel_event):
        context = OperationContext(operation_id, deadline, cancelled=cancel_event)
        context.remaining()
        with source_upload_ports(record, context=context) as (records, objects):
            return SourcePublisher(records, objects).publish(
                record["file_id"],
                content,
                content_type=content_type,
                expected_version=record["version"],
                context=context,
            )

    try:
        async with asyncio.timeout(timeout):
            return await manager.run(
                "file-upload",
                ManagedTaskSpec(
                    task_name="knowledge-source-upload",
                    owner="management",
                    attempt_id=record["file_id"],
                    deadline_monotonic=deadline,
                    pass_cancel_event=True,
                ),
                run,
            )
    except TimeoutError:
        raise OutcomeUnknown(operation_id=operation_id) from None
