import logging
import time
from contextlib import asynccontextmanager

from apps.app_factory import create_app
from apps.agent_app import agent_runtime_router as agent_router
from apps.agent_automation_app import (
    conversation_automation_router,
    router as agent_automation_router,
)
from apps.agent_evaluation_runtime_app import router as agent_evaluation_runtime_router
from apps.voice_app import voice_runtime_router as voice_router
from apps.conversation_management_app import router as conversation_management_router
from apps.conversation_share_app import router as conversation_share_router
from apps.file_management_app import (
    file_management_runtime_router as file_management_router,
)
from apps.skill_app import skill_creator_router
from apps.human_interaction_app import router as human_interaction_router
from apps.human_interaction_app import internal_router as internal_human_interaction_router
from consts.const import RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS
from middleware.exception_handler import ExceptionHandlerMiddleware
from nexent.core.concurrency import (
    ManagedTaskSpec,
    ManagerState,
    clear_default_thread_manager,
    set_default_thread_manager,
)
from services.thread_lifecycle_service import runtime_thread_manager
from services.runtime_state_service import runtime_state_service

logger = logging.getLogger("runtime_app")


async def start_agent_automation_scheduler():
    from consts.const import HITL_ENABLED
    from services.agent_automation.scheduler import agent_automation_scheduler
    from services.human_interaction.application import get_service, human_run_scheduler
    from services.startup_recovery_service import recover_runtime_tasks
    from services.workspace_cleanup_service import cleanup_orphaned_agent_workspaces

    await runtime_thread_manager.run(
        "control-io",
        ManagedTaskSpec(
            task_name="recover-runtime-tasks",
            owner="apps.runtime_app",
        ),
        recover_runtime_tasks,
    )
    cleanup_orphaned_agent_workspaces()
    await agent_automation_scheduler.start()
    if HITL_ENABLED:
        get_service()
        await human_run_scheduler.start()


async def stop_agent_automation_scheduler():
    from services.agent_automation.scheduler import agent_automation_scheduler
    from services.human_interaction.application import human_run_scheduler

    await agent_automation_scheduler.stop()
    await human_run_scheduler.stop()


@asynccontextmanager
async def runtime_lifespan(_app):
    if runtime_thread_manager.state is ManagerState.CREATED:
        runtime_thread_manager.start()
    set_default_thread_manager(runtime_thread_manager)
    runtime_state_service.set_thread_manager(runtime_thread_manager)
    await start_agent_automation_scheduler()
    try:
        yield
    finally:
        shutdown_deadline = (
            time.monotonic() + RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS
        )
        await stop_agent_automation_scheduler()
        from management.services.agent.run import shutdown_agent_stream_tasks

        pending_stream_tasks = await shutdown_agent_stream_tasks(
            timeout=max(0, shutdown_deadline - time.monotonic())
        )
        if pending_stream_tasks:
            logger.warning(
                "Agent stream tasks exceeded shutdown grace pending=%s",
                pending_stream_tasks,
            )
        from nexent.core.agents.sandbox import SandboxPoolManager

        sandbox_pool = SandboxPoolManager._instance
        if sandbox_pool is not None:
            sandbox_pool.shutdown(logger)
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
app.include_router(conversation_management_router)
app.include_router(conversation_share_router)
app.include_router(file_management_router)
app.include_router(voice_router)
app.include_router(skill_creator_router)
app.include_router(human_interaction_router)
app.include_router(internal_human_interaction_router)
