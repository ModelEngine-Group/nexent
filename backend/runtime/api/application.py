# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
import time
from contextlib import asynccontextmanager

from backend.http.server.app_factory import create_app
from runtime.api.agent.execution import agent_runtime_router as agent_router
from runtime.api.evaluation.execution import router as agent_evaluation_runtime_router
from runtime.api.voice.streaming import voice_runtime_router as voice_router
from management.api.automation.agent_automation import (
    conversation_automation_router,
)
from management.api.automation.agent_automation import (
    router as agent_automation_router,
)
from management.api.conversation.conversation_management import (
    router as conversation_management_router,
)
from management.api.conversation.conversation_share import (
    router as conversation_share_router,
)
from management.api.conversation.workbench_pins import router as workbench_pins_router
from runtime.api.file.upload import file_management_runtime_router as file_management_router
from runtime.api.skill.creation import skill_creator_router
from contracts.constants.environment import RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS
from runtime.api.exception_handler import ExceptionHandlerMiddleware
from runtime.api.identity_routes import is_runtime_service_request
from management.configuration.runtime import (
    start_system_configuration,
    stop_system_configuration,
)
from nexent.core.concurrency import (
    ManagedTaskSpec,
    ManagedThreadSpec,
    ManagerState,
    clear_default_thread_manager,
    set_default_thread_manager,
)
from runtime.thread_management import runtime_thread_manager
from infrastructure.redis.run_state import runtime_state_service

logger = logging.getLogger("runtime_app")


async def start_agent_automation_scheduler():
    from management.recovery import recover_runtime_tasks
    from management.services.automation.scheduler import agent_automation_scheduler
    from management.services.agent.workspace_cleanup import cleanup_orphaned_agent_workspaces

    await runtime_thread_manager.run(
        "control-io",
        ManagedTaskSpec(
            task_name="recover-runtime-tasks",
            owner="runtime.api.application",
        ),
        recover_runtime_tasks,
    )
    cleanup_orphaned_agent_workspaces()
    await agent_automation_scheduler.start()


async def stop_agent_automation_scheduler():
    from management.services.automation.scheduler import agent_automation_scheduler

    await agent_automation_scheduler.stop()


@asynccontextmanager
async def runtime_lifespan(_app):
    if runtime_thread_manager.state is ManagerState.CREATED:
        runtime_thread_manager.start()
    set_default_thread_manager(runtime_thread_manager)
    runtime_state_service.set_thread_manager(runtime_thread_manager)

    async def run_configuration_io(fn):
        return await runtime_thread_manager.run(
            "control-io",
            ManagedTaskSpec(
                task_name="system-configuration-refresh",
                owner="management.configuration.runtime",
            ),
            fn,
        )

    from infrastructure.trace.bootstrap import local_trajectory_processor

    try:
        configuration_runtime = await start_system_configuration(run_configuration_io)
        if _app is not None:
            _app.state.configuration_runtime = configuration_runtime
        if local_trajectory_processor is not None:
            from infrastructure.trace.trajectory_runtime import (
                conversation_deleted,
            )

            local_trajectory_processor.deleted_conversation_check = conversation_deleted
            local_trajectory_processor.start(
                runtime_thread_manager,
                ManagedThreadSpec(
                    task_name="trajectory-file-writer",
                    owner="infrastructure.trace.trajectory_runtime",
                    close_hook=local_trajectory_processor.request_stop,
                ),
            )
        await start_agent_automation_scheduler()
        yield
    finally:
        shutdown_deadline = time.monotonic() + RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS
        try:
            await stop_agent_automation_scheduler()
            from management.services.agent.execution import (
                shutdown_agent_stream_tasks,
            )
            from management.services.conversation.creator_runtime import (
                shutdown_creator_streams,
            )

            await shutdown_creator_streams(
                timeout=max(0, shutdown_deadline - time.monotonic())
            )
            pending_stream_tasks = await shutdown_agent_stream_tasks(
                timeout=max(0, shutdown_deadline - time.monotonic())
            )
            if pending_stream_tasks:
                logger.warning(
                    "Agent stream tasks exceeded shutdown grace pending=%s",
                    pending_stream_tasks,
                )
            from nexent.core.agents.sandbox.execution import SandboxPoolManager

            sandbox_pool = SandboxPoolManager._instance
            if sandbox_pool is not None:
                sandbox_pool.shutdown(logger)
        finally:
            try:
                if local_trajectory_processor is not None:
                    local_trajectory_processor.request_stop()
                    await runtime_thread_manager.run(
                        "control-io",
                        ManagedTaskSpec(
                            task_name="trajectory-file-shutdown",
                            owner="runtime.api.application",
                        ),
                        local_trajectory_processor.shutdown,
                    )
            finally:
                try:
                    await stop_system_configuration()
                finally:
                    try:
                        await runtime_thread_manager.shutdown(
                            timeout=max(0, shutdown_deadline - time.monotonic())
                        )
                    finally:
                        clear_default_thread_manager(runtime_thread_manager)

app = create_app(
    title="Nexent Runtime API",
    description="Runtime APIs",
    lifespan=runtime_lifespan,
    gateway_identity_audience="runtime",
    internal_runtime_request=is_runtime_service_request,
)
if hasattr(app, "state"):
    app.state.thread_manager = runtime_thread_manager


@app.get("/internal/thread-capacity", include_in_schema=False)
async def thread_capacity():
    """Return the Runtime process-local thread capacity snapshot."""
    return runtime_thread_manager.snapshot()


app.add_middleware(ExceptionHandlerMiddleware)

app.include_router(agent_router)
app.include_router(agent_evaluation_runtime_router)
app.include_router(agent_automation_router)
app.include_router(conversation_automation_router)
app.include_router(workbench_pins_router)
app.include_router(conversation_management_router)
app.include_router(conversation_share_router)
app.include_router(file_management_router)
app.include_router(voice_router)
app.include_router(skill_creator_router)
