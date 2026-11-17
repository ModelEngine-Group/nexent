# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Management-owned ingestion admission and established public result projection."""

import asyncio
import logging
from dataclasses import replace
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import (
    RuntimeServiceTimeoutError,
    RuntimeServiceUnavailableError,
)
from contracts.errors.ingestion import classify_ingestion_exception
from management.services.knowledge_base.ingestion_coordinator import (
    IngestionCancellation,
)
from management.services.knowledge_base.ingestion_dispatch import default_coordinator
from management.services.knowledge_base.ingestion_selection import (
    resolve_ingestion_file,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    DeadlineExceeded,
    InvalidInput,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import OperationContext

from infrastructure.knowledge_cleanse import knowledge_resource_ports
from infrastructure.trace.knowledge import (
    set_span_attributes,
    trace_knowledge_operation,
)

logger = logging.getLogger(__name__)


def _submission_failure(details, error):
    if isinstance(error, OutcomeUnknown):
        code = "KNOWLEDGE_OUTCOME_UNKNOWN"
    elif isinstance(
        error, (TimeoutError, DeadlineExceeded, RuntimeServiceTimeoutError)
    ):
        code = ErrorCode.SYSTEM_TIMEOUT.value
    elif isinstance(error, (Unavailable, RuntimeServiceUnavailableError)):
        code = ErrorCode.SYSTEM_SERVICE_UNAVAILABLE.value
    elif isinstance(error, ScopeDenied):
        code = ErrorCode.COMMON_FORBIDDEN.value
    elif isinstance(error, NotFound):
        code = ErrorCode.FILE_NOT_FOUND.value
    else:
        code = classify_ingestion_exception(error, "TASK_SUBMIT").error_code
    details = details if isinstance(details, dict) else {}
    return {
        "file_id": details.get("file_id"),
        "source": details.get("path_or_url"),
        "original_filename": details.get("filename"),
        "status": "FAILED",
        "error_code": code,
        "error_message": None,
    }


@trace_knowledge_operation("knowledge.process.submit", "process.submit")
async def submit_knowledge_files(
    files,
    index_name,
    actor,
    *,
    destination="minio",
    chunking_strategy="basic",
    coordinator=None,
    context=None,
):
    """Admit authorized source identities and project the established public task envelope."""
    if not files:
        return None
    if (
        not isinstance(index_name, str)
        or not index_name.strip()
        or len(index_name) > 100
    ):
        raise InvalidInput()
    coordinator = coordinator if coordinator is not None else default_coordinator()
    context = context or OperationContext(
        "ingestion-submit-" + uuid4().hex, monotonic() + 30
    )
    owned = Event()
    operation = replace(
        context,
        deadline=min(context.deadline, monotonic() + 30),
        cancelled=IngestionCancellation(owned, context.cancelled),
    )
    results, task_ids = [], []
    timeout_logged = False

    def resolve(details, bound):
        bound.remaining()
        with knowledge_resource_ports(
            actor.tenant_id, actor.user_id, context=bound, include_files=True
        ) as records:
            return resolve_ingestion_file(
                records,
                actor,
                index_name,
                details,
                destination=destination,
                context=bound,
            )

    try:
        try:
            async with asyncio.timeout(operation.remaining()):
                for details in files:
                    operation.remaining()
                    timeout_logged, phase = False, "select"
                    bound = replace(
                        operation, deadline=min(operation.deadline, monotonic() + 10)
                    )
                    try:
                        async with asyncio.timeout(bound.remaining()):
                            selected = await run_blocking(
                                "ingestion-select-source",
                                resolve,
                                details,
                                bound,
                                lane="control-io",
                                owner="management.knowledge_base",
                            )
                            phase = "admit"
                            row = await coordinator.accept(
                                selected["file_id"],
                                actor,
                                chunking_strategy=chunking_strategy or "basic",
                                context=bound,
                            )
                            task_id = row["process_task_id"]
                            if not isinstance(task_id, str) or not task_id:
                                raise OutcomeUnknown(operation_id=bound.operation_id)
                        task_ids.append(task_id)
                        results.append(
                            {
                                "file_id": selected["file_id"],
                                "source": details.get("path_or_url"),
                                "original_filename": selected["original_filename"],
                                "status": "SUBMITTED",
                                "task_id": task_id,
                            }
                        )
                    except Exception as error:  # noqa: BLE001 - Preserve independent batch outcomes without replay.
                        if (
                            isinstance(error, TimeoutError)
                            or isinstance(error, DeadlineExceeded)
                            and phase == "select"
                        ):
                            logger.warning(
                                "knowledge_ingestion_submit_timeout operation_id=%s phase=%s threshold_seconds=10",
                                operation.operation_id,
                                phase,
                            )
                            timeout_logged = True
                        results.append(_submission_failure(details, error))
        except (TimeoutError, DeadlineExceeded) as error:
            if not timeout_logged:
                logger.warning(
                    "knowledge_ingestion_submit_timeout operation_id=%s phase=batch threshold_seconds=30",
                    operation.operation_id,
                )
            results.extend(
                _submission_failure(details, error) for details in files[len(results) :]
            )
    finally:
        owned.set()
    if len(files) == 1 and task_ids:
        return {"task_id": task_ids[0]}
    failed = len(results) - len(task_ids)
    set_span_attributes(stage="process.submitted")
    return {
        "status": "success"
        if not failed
        else "partial_success"
        if task_ids
        else "failed",
        "task_ids": task_ids,
        "results": results,
        "submitted_count": len(task_ids),
        "failed_count": failed,
    }
