# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Lifespan-owned consumption of durable queued uploads without retry or restart."""

import asyncio
import logging
import math
from contextlib import asynccontextmanager
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.agentos_knowledge import KnowledgeJobLookup
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import InvalidInput
from nexent.storage.models import OperationContext, PageRequest, RecordQuery, Sort

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.knowledge_runtime import knowledge_dispatch_ports
from infrastructure.rdb.knowledge_dispatch import DATASET

logger = logging.getLogger(__name__)


def _owner(owner_id):
    if not isinstance(owner_id, str) or not owner_id.strip() or len(owner_id) > 100:
        raise InvalidInput()


async def dispatch_once(workers, *, owner_id, stop):
    _owner(owner_id)
    if stop.is_set():
        return 0
    context = OperationContext("knowledge-discovery-" + uuid4().hex, monotonic() + 10, cancelled=stop)

    def discover():
        context.remaining()
        with knowledge_dispatch_ports(context=context) as records:
            return records.query(
                DATASET, RecordQuery(order_by=(Sort("create_time"),)),
                PageRequest(limit=100), context=context,
            ).items

    rows = await run_blocking(
        "knowledge-discovery", discover, lane="control-io", owner="runtime.knowledge_base",
    )
    consumed = 0
    for row in rows:
        if stop.is_set():
            break
        actor = ServicePrincipal(row["user_id"], row["tenant_id"])
        worker = workers[row["operation"]]
        lookup = KnowledgeJobLookup(**{name: row[name] for name in (
            "job_id", "knowledge_id", "file_id", "file_version",
        )})
        await worker.process(
            lookup, actor, owner_id=owner_id,
            context=OperationContext(
                "knowledge-job-" + uuid4().hex,
                monotonic() + worker.operation_seconds, cancelled=stop,
            ),
        )
        consumed += 1
    return consumed


async def serve(workers, *, owner_id, stop, poll_seconds=1):
    _owner(owner_id)
    if (type(poll_seconds) not in {int, float} or not math.isfinite(poll_seconds)
            or not 0.01 <= poll_seconds <= 30):
        raise InvalidInput()
    while not stop.is_set():
        await dispatch_once(workers, owner_id=owner_id, stop=stop)
        if not stop.is_set():
            await asyncio.sleep(poll_seconds)


def default_workers():
    from contracts.constants import environment
    from runtime.knowledge_base.composition import default_service
    from runtime.knowledge_base.deletion import KnowledgeDeleteWorker
    from runtime.knowledge_base.worker import KnowledgeUploadWorker

    service = default_service()
    return {"upload": KnowledgeUploadWorker(
        service.client, service.models,
        max_artifact_bytes=environment.MAX_KNOWLEDGE_FILE_SIZE_BYTES,
        max_source_bytes=environment.MAX_KNOWLEDGE_FILE_SIZE_BYTES,
        operation_seconds=environment.MAX_TIMEOUT,
    ), "delete": KnowledgeDeleteWorker(service.client, operation_seconds=environment.MAX_TIMEOUT)}


def _finished(task, stop):
    if not task.cancelled() and not stop.is_set():
        error = task.exception()
        logger.warning("knowledge_dispatch_failed exception_type=%s",
                       type(error).__name__ if error else "UnexpectedCompletion")


@asynccontextmanager
async def knowledge_lifespan(app, *, workers=None):
    stop = Event()
    task = asyncio.create_task(
        serve(workers if workers is not None else default_workers(), owner_id="knowledge-" + uuid4().hex, stop=stop),
        name="runtime-knowledge-dispatch",
    )
    task.add_done_callback(lambda finished: _finished(finished, stop))
    app.state.required_background_tasks = (*getattr(app.state, "required_background_tasks", ()), task)
    try:
        yield
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        app.state.required_background_tasks = tuple(
            item for item in app.state.required_background_tasks if item is not task
        )
