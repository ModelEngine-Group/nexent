# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management lifespan owns one separate root; an exited root stays unhealthy."""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from contracts.constants import environment
from nexent.storage.errors import InvalidInput

from infrastructure.file_processing.root_process import CleanseProcess

logger = logging.getLogger(__name__)


async def _watch(process):
    code = await process.wait()
    raise RuntimeError(f"Cleansing root exited with status {code}")


def _finished(task):
    if not task.cancelled():
        error = task.exception()
        logger.warning(
            "cleanse_root_exited phase=watch exception_type=%s", type(error).__name__
        )


@asynccontextmanager
async def cleanse_lifespan(app, *, enabled=None, factory=CleanseProcess):
    enabled = (
        environment.MANAGEMENT_FILE_CLEANSE_ENABLED if enabled is None else enabled
    )
    if type(enabled) is not bool:
        raise InvalidInput()
    if not enabled:
        yield
        return
    process = factory()
    await process.start()
    app.state.cleanse_root = process
    task = asyncio.create_task(_watch(process), name="management-file-cleanse-root")
    task.add_done_callback(_finished)
    app.state.required_background_tasks = (
        *getattr(app.state, "required_background_tasks", ()),
        task,
    )
    try:
        yield
    finally:
        task.cancel()
        try:
            with suppress(asyncio.CancelledError, RuntimeError):
                await task
        finally:
            await process.stop()
            app.state.required_background_tasks = tuple(
                item for item in app.state.required_background_tasks if item is not task
            )
            app.state.cleanse_root = None
