# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Lifespan-owned discovery advances existing intentions without replaying uncertain work."""

import asyncio
import logging
import math
from contextlib import asynccontextmanager
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.constants import environment
from management.services.knowledge_base.ingestion_journal import IngestionPhaseChanged
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import InvalidInput
from nexent.storage.models import OperationContext, PageRequest, RecordQuery, Sort

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.knowledge_ingestion import ingestion_dispatch_ports
from infrastructure.rdb.knowledge_ingestion_dispatch import DATASET

logger = logging.getLogger(__name__)


def default_coordinator():
    from management.services.file.knowledge_cleanse_service import (
        KnowledgeCleanseService,
    )
    from management.services.knowledge_base.ingestion_coordinator import (
        IngestionCoordinator,
    )

    from backend.http.client import create_httpx_client
    from infrastructure.agentos_client import AgentOSClient

    return IngestionCoordinator(
        KnowledgeCleanseService(
            parser_version=environment.KNOWLEDGE_CLEANSE_PARSER_VERSION
        ),
        AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client),
    )


async def dispatch_once(coordinator, *, stop, cursor=None):
    if stop.is_set():
        return 0, cursor
    context = OperationContext(
        "ingestion-discovery-" + uuid4().hex, monotonic() + 10, cancelled=stop
    )

    def discover():
        context.remaining()
        with ingestion_dispatch_ports(context=context) as records:
            return records.query(
                DATASET,
                RecordQuery(order_by=(Sort("file_id"),)),
                PageRequest(limit=100, cursor=cursor),
                context=context,
            )

    page = await run_blocking(
        "ingestion-discovery",
        discover,
        lane="control-io",
        owner="management.knowledge_base",
    )
    consumed = 0
    for row in page.items:
        if stop.is_set():
            break
        try:
            await coordinator.advance(
                row["file_id"],
                ServicePrincipal(row["user_id"], row["tenant_id"]),
                context=OperationContext(
                    "ingestion-advance-" + uuid4().hex, monotonic() + 10, cancelled=stop
                ),
            )
        except IngestionPhaseChanged:
            continue
        consumed += 1
    return consumed, page.next_cursor


async def serve(coordinator, *, stop, poll_seconds=1):
    if (
        type(poll_seconds) not in {int, float}
        or not math.isfinite(poll_seconds)
        or not 0.01 <= poll_seconds <= 30
    ):
        raise InvalidInput()
    cursor = None
    while not stop.is_set():
        _, cursor = await dispatch_once(coordinator, stop=stop, cursor=cursor)
        if not stop.is_set():
            await asyncio.sleep(poll_seconds)


def _finished(task, stop):
    if not task.cancelled() and not stop.is_set():
        error = task.exception()
        logger.warning(
            "knowledge_ingestion_dispatch_failed exception_type=%s",
            type(error).__name__ if error else "UnexpectedCompletion",
        )


@asynccontextmanager
async def ingestion_lifespan(app, *, enabled=None, coordinator=None):
    enabled = (
        environment.MANAGEMENT_FILE_CLEANSE_ENABLED if enabled is None else enabled
    )
    if type(enabled) is not bool:
        raise InvalidInput()
    if not enabled:
        yield
        return
    stop = Event()
    task = asyncio.create_task(
        serve(
            coordinator if coordinator is not None else default_coordinator(), stop=stop
        ),
        name="management-knowledge-ingestion",
    )
    task.add_done_callback(lambda finished: _finished(finished, stop))
    app.state.required_background_tasks = (
        *getattr(app.state, "required_background_tasks", ()),
        task,
    )
    try:
        yield
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        app.state.required_background_tasks = tuple(
            item for item in app.state.required_background_tasks if item is not task
        )
