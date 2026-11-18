# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management lifespan owns bounded automatic-summary discovery without task restarts."""

import asyncio
import logging
import math
from contextlib import asynccontextmanager
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.constants.constants import SCHEDULER_CHECK_INTERVAL_SECONDS
from contracts.knowledge_summary import SUMMARY_DISPATCH_DATASET
from management.services.knowledge_base.summary_coordinator import SummaryCoordinator
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    NotFound,
    ScopeDenied,
)
from nexent.storage.models import OperationContext, PageRequest, RecordQuery, Sort

from infrastructure.knowledge_summary import summary_dispatch_ports

logger = logging.getLogger(__name__)


async def dispatch_once(coordinator, *, stop, cursor=None):
    if stop.is_set():
        return cursor
    context = OperationContext('knowledge-summary-discovery-' + uuid4().hex, monotonic() + 10, cancelled=stop)

    def discover():
        context.remaining()
        with summary_dispatch_ports(context=context) as records:
            return records.query(SUMMARY_DISPATCH_DATASET, RecordQuery(order_by=(Sort('knowledge_id'),)),
                                 PageRequest(limit=100, cursor=cursor), context=context)
    try:
        async with asyncio.timeout(context.remaining()):
            page = await run_blocking('knowledge-summary-discovery', discover, lane='control-io', owner='management.knowledge.summary')
    except (TimeoutError, DeadlineExceeded) as error:
        logger.warning('knowledge_summary_discovery_timeout operation_id=%s phase=records threshold_seconds=10 exception_type=%s',
                       context.operation_id, type(error).__name__)
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    for candidate in page.items:
        if stop.is_set():
            break
        try:
            await coordinator.advance(candidate)
        except (Conflict, NotFound, ScopeDenied) as error:
            logger.info('knowledge_summary_candidate_skipped knowledge_id=%s exception_type=%s',
                        candidate['knowledge_id'], type(error).__name__)
    return page.next_cursor


async def serve(coordinator, *, stop, poll_seconds=SCHEDULER_CHECK_INTERVAL_SECONDS):
    if type(poll_seconds) not in {int, float} or not math.isfinite(poll_seconds) or not 0 < poll_seconds <= SCHEDULER_CHECK_INTERVAL_SECONDS:
        raise InvalidInput()
    cursor = None
    while not stop.is_set():
        cursor = await dispatch_once(coordinator, stop=stop, cursor=cursor)
        if cursor is None and not stop.is_set():
            await asyncio.sleep(poll_seconds)


def _finished(task, stop):
    if not task.cancelled() and not stop.is_set():
        error = task.exception()
        logger.warning('knowledge_summary_dispatch_failed exception_type=%s',
                       type(error).__name__ if error else 'UnexpectedCompletion')


@asynccontextmanager
async def summary_lifespan(app, *, coordinator=None):
    stop = Event()
    task = asyncio.create_task(serve(coordinator if coordinator is not None else SummaryCoordinator(), stop=stop),
                               name='management-knowledge-summary')
    task.add_done_callback(lambda finished: _finished(finished, stop))
    app.state.required_background_tasks = (*getattr(app.state, 'required_background_tasks', ()), task)
    try:
        yield
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        app.state.required_background_tasks = tuple(item for item in app.state.required_background_tasks if item is not task)
