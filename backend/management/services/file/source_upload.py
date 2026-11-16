# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Service-owned upload work with one deadline and durable source pinning."""

import asyncio
import logging
import math
from time import monotonic
from uuid import uuid4

from management.services.file.source_finalize import SourceFinalizer
from management.services.file.source_publish import SourcePublisher
from nexent.core.concurrency import (
    ManagedTaskSpec,
    get_current_thread_manager,
    get_default_thread_manager,
)
from nexent.storage.errors import InvalidInput, OutcomeUnknown
from nexent.storage.models import OperationContext

from infrastructure.source_upload import source_upload_ports

logger = logging.getLogger(__name__)


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
            source = SourcePublisher(records, objects).publish(
                record["file_id"],
                content,
                content_type=content_type,
                expected_version=record["version"],
                context=context,
            )
            try:
                accounted = SourceFinalizer(records, objects).account(
                    record["file_id"],
                    owner_user_id=record["created_by"],
                    owner_service=record.get("upload_owner_service"),
                    context=context,
                )
            except Exception as error:  # noqa: BLE001 - A confirmed object must retain recovery on any accounting failure.
                # The confirmed source can already have a charge; preserve recovery.
                logger.warning(
                    "source_accounting_requires_reconciliation error_type=%s",
                    type(error).__name__,
                )
                raise OutcomeUnknown(operation_id=operation_id) from None
            return source, accounted

    try:
        async with asyncio.timeout(timeout):
            source, accounted = await manager.run(
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
            record.update(accounted)
            return source
    except TimeoutError:
        raise OutcomeUnknown(operation_id=operation_id) from None
