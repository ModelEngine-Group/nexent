# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management-owned Northbound composition and shared process lifecycle.

The main Management application includes these routers and enters this lifespan.
The component app supports isolated Northbound contract verification.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from contracts.constants.environment import RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS
from contracts.constants.constants import CONFIG_SERVICE_NAME, NORTHBOUND_SERVICE_NAME
from management.api.northbound import a2a_router
from management.api.northbound import router as northbound_router
from management.thread_management import config_thread_manager
from infrastructure.redis.run_state import runtime_state_service
from backend.http.server.app_factory import create_app
from nexent.core.concurrency import (
    ManagedTaskSpec,
    ManagerState,
    clear_default_thread_manager,
    set_default_thread_manager,
)

logger = logging.getLogger("northbound_base_app")


async def recover_northbound_tasks_on_startup(cleanup_tasks=None):
    from management.recovery import (
        recover_northbound_tasks,
        schedule_interrupted_upload_cleanup,
    )

    await config_thread_manager.run(
        "control-io",
        ManagedTaskSpec(
            task_name="recover-northbound-tasks",
            owner="management.api.northbound_application",
        ),
        recover_northbound_tasks,
    )
    for owner in (CONFIG_SERVICE_NAME, NORTHBOUND_SERVICE_NAME):
        task = await schedule_interrupted_upload_cleanup(owner, thread_manager=config_thread_manager)
        if cleanup_tasks is not None and isinstance(task, asyncio.Task):
            cleanup_tasks.append(task)


@asynccontextmanager
async def northbound_lifespan(_app):
    if config_thread_manager.state is ManagerState.CREATED:
        config_thread_manager.start()
    set_default_thread_manager(config_thread_manager)
    runtime_state_service.set_thread_manager(config_thread_manager)
    cleanup_tasks = []
    try:
        await recover_northbound_tasks_on_startup(cleanup_tasks)
        yield
    finally:
        for task in cleanup_tasks:
            task.cancel()
        try:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        finally:
            try:
                await config_thread_manager.shutdown(timeout=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS)
            finally:
                runtime_state_service.set_thread_manager(None)
                clear_default_thread_manager(config_thread_manager)


northbound_app = create_app(
    title="Nexent Northbound API",
    description="Northbound APIs for partners",
    version="1.0.0",
    cors_methods=["GET", "POST", "PUT", "DELETE"],
    enable_monitoring=False,  # Disable monitoring if not needed
    lifespan=northbound_lifespan,
    gateway_identity_audience="management",
)
if hasattr(northbound_app, "state"):
    northbound_app.state.thread_manager = config_thread_manager


@northbound_app.get("/internal/thread-capacity", include_in_schema=False)
async def thread_capacity():
    """Return the Northbound process-local thread capacity snapshot."""
    return config_thread_manager.snapshot()


northbound_app.include_router(northbound_router)
# Include A2A router into main app
northbound_app.include_router(a2a_router)
