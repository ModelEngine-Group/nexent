# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Local cleansing handlers; all persistence and broker I/O use injected ports."""

import logging
from dataclasses import replace
from datetime import datetime
from time import monotonic
from types import MappingProxyType

from contracts.agentos_knowledge import FileCleanseRequest, ObjectReference
from nexent.storage.errors import InvalidInput, OutcomeUnknown, StorageError
from nexent.storage.models import TaskEnvelope

logger = logging.getLogger(__name__)
HANDLER = "file.cleanse"


class HandlerRegistry:
    def __init__(self, handlers):
        if not handlers or any(
            not isinstance(name, str) or not callable(handler)
            for name, handler in handlers.items()
        ):
            raise InvalidInput()
        self._handlers = MappingProxyType(dict(handlers))

    def dispatch(self, task, *, context):
        handler = self._handlers.get(task.handler)
        if handler is None:
            raise InvalidInput()
        handler(task, context=context)


def consume_once(queue, registry, *, max_wait, context):
    delivery = queue.consume(max_wait=max_wait, context=context)
    if delivery is None:
        return False
    try:
        registry.dispatch(delivery.task, context=context)
    except BaseException:
        # Broker acknowledgement follows durable job outcome, never precedes it.
        try:
            queue.retry(delivery.receipt, context=context)
        except StorageError:
            queue.close()
        raise
    queue.ack(delivery.receipt, context=context)
    return True


def enqueue_ready(jobs, queue, *, limit=100, context):
    count = 0
    for row in jobs.ready(limit=limit, context=context):
        queue.enqueue(
            TaskEnvelope(row["job_id"], HANDLER, {"job_id": row["job_id"]}),
            context=context,
        )
        count += 1
    return count


class CleanseHandler:
    def __init__(self, jobs, *, owner_id, lease_seconds, authorize_execution, execute):
        if not callable(authorize_execution) or not callable(execute):
            raise InvalidInput()
        self.jobs = jobs
        self.owner_id = owner_id
        self.lease_seconds = lease_seconds
        self.authorize = authorize_execution
        self.execute = execute

    def __call__(self, task, *, context):
        if (
            task.handler != HANDLER
            or task.arguments != {"job_id": task.task_id}
            or len(task.task_id) != 32
            or any(char not in "0123456789abcdef" for char in task.task_id)
        ):
            raise InvalidInput()
        row = self.jobs.claim(
            self.owner_id,
            lease_seconds=self.lease_seconds,
            job_id=task.task_id,
            context=context,
        )
        if row is None:
            return  # A terminal/owned duplicate must not execute the parser again.
        try:
            request = FileCleanseRequest.model_validate(row["request_payload"])
            self.authorize(row, request)
            if row["parser_version"] != self.jobs.parser_version:
                self.jobs.transition(
                    row,
                    status="failed",
                    error_code="PARSER_VERSION_UNAVAILABLE",
                    context=context,
                )
                return
            remaining = (
                datetime.fromisoformat(row["lease_until"]) - self.jobs.clock()
            ).total_seconds()
            execution = replace(
                context, deadline=min(context.deadline, monotonic() + max(0, remaining))
            )
            execution.remaining()
            artifact = self.execute(row, request, context=execution)
            if not isinstance(artifact, ObjectReference):
                raise InvalidInput()
        except OutcomeUnknown:
            self.jobs.mark_uncertain(row, context=context)
            return
        except Exception as error:  # noqa: BLE001 - Persist a sanitized handler failure.
            logger.warning("cleanse_handler_failed error_type=%s", type(error).__name__)
            self.jobs.transition(
                row, status="failed", error_code="CLEANSE_FAILED", context=context
            )
            return
        self.jobs.transition(
            row, status="completed", artifact=artifact, context=context
        )
