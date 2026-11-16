# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Local cleansing handlers; all persistence and broker I/O use injected ports."""

import logging
from dataclasses import replace
from datetime import datetime
from time import monotonic
from types import MappingProxyType

from contracts.agentos_knowledge import ObjectReference
from contracts.knowledge_cleanse import parse_cleanse_request
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
            queue.retry(delivery.receipt, context=_cleanup_context(context))
        except StorageError:
            queue.close()
        raise
    queue.ack(delivery.receipt, context=_cleanup_context(context))
    return True


def _cleanup_context(context, seconds=5):
    return replace(context, deadline=monotonic() + seconds, cancelled=None)


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
    def __init__(
        self,
        jobs,
        *,
        owner_id,
        lease_seconds,
        authorize_execution,
        execute,
        finalize_seconds=5,
    ):
        if not callable(authorize_execution) or not callable(execute):
            raise InvalidInput()
        self.jobs = jobs
        self.owner_id = owner_id
        self.lease_seconds = lease_seconds
        self.authorize = authorize_execution
        self.execute = execute
        if type(finalize_seconds) is not int or not 1 <= finalize_seconds <= 30:
            raise InvalidInput()
        self.finalize_seconds = finalize_seconds

    def _finalize_context(self, context):
        # Only durable cleanup gets a fresh budget; execution keeps its original deadline.
        return _cleanup_context(context, self.finalize_seconds)

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
            request = parse_cleanse_request(row)
            self.authorize(row, request, context=context)
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
            self.jobs.mark_uncertain(row, context=self._finalize_context(context))
            return
        except Exception as error:  # noqa: BLE001 - Persist a sanitized handler failure.
            logger.warning("cleanse_handler_failed error_type=%s", type(error).__name__)
            self.jobs.transition(
                row,
                status="failed",
                error_code="CLEANSE_FAILED",
                context=self._finalize_context(context),
            )
            return
        completed = self.jobs.transition(
            row,
            status="completed",
            artifact=artifact,
            context=self._finalize_context(context),
        )
        if not completed:
            # A confirmed artifact without an accepted completion must not replay blindly.
            self.jobs.mark_uncertain(row, context=self._finalize_context(context))
