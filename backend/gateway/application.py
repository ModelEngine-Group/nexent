# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""
Northbound API with A2A support.

This module combines northbound app with A2A server endpoints.
Assemble Gateway routers and manage the process-local thread lifecycle.
"""

import logging
from contextlib import asynccontextmanager

from contracts.constants.environment import NORTHBOUND_THREAD_SHUTDOWN_GRACE_SECONDS
from contracts.constants.constants import NORTHBOUND_SERVICE_NAME
from gateway.api.northbound import a2a_router
from gateway.api.northbound import router as northbound_router
from infrastructure.concurrency import northbound_thread_manager
from management.services.agent.run_state import runtime_state_service
from management.utils.app_factory import create_app
from nexent.core.concurrency import (
    ManagedTaskSpec,
    ManagerState,
    clear_default_thread_manager,
    set_default_thread_manager,
)

logger = logging.getLogger("northbound_base_app")


async def recover_northbound_tasks_on_startup():
    from management.recovery import (
        recover_northbound_tasks,
        schedule_interrupted_upload_cleanup,
    )

    await northbound_thread_manager.run(
        "control-io",
        ManagedTaskSpec(
            task_name="recover-northbound-tasks",
            owner="gateway.application",
        ),
        recover_northbound_tasks,
    )
    await schedule_interrupted_upload_cleanup(NORTHBOUND_SERVICE_NAME)


@asynccontextmanager
async def northbound_lifespan(_app):
    if northbound_thread_manager.state is ManagerState.CREATED:
        northbound_thread_manager.start()
    set_default_thread_manager(northbound_thread_manager)
    runtime_state_service.set_thread_manager(northbound_thread_manager)
    await recover_northbound_tasks_on_startup()
    try:
        yield
    finally:
        try:
            await northbound_thread_manager.shutdown(timeout=NORTHBOUND_THREAD_SHUTDOWN_GRACE_SECONDS)
        finally:
            clear_default_thread_manager(northbound_thread_manager)


northbound_app = create_app(
    title="Nexent Northbound API",
    description="Northbound APIs for partners",
    version="1.0.0",
    cors_methods=["GET", "POST", "PUT", "DELETE"],
    enable_monitoring=False,  # Disable monitoring if not needed
    lifespan=northbound_lifespan,
)
if hasattr(northbound_app, "state"):
    northbound_app.state.thread_manager = northbound_thread_manager


@northbound_app.get("/internal/thread-capacity", include_in_schema=False)
async def thread_capacity():
    """Return the Northbound process-local thread capacity snapshot."""
    return northbound_thread_manager.snapshot()


northbound_app.include_router(northbound_router)
# Include A2A router into main app
northbound_app.include_router(a2a_router)
