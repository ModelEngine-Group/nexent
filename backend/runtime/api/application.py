# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
import time
from contextlib import asynccontextmanager

from backend.http.server.app_factory import create_app
from runtime.agentos.compatibility import create_background_router, create_compatibility_router
from runtime.agentos.middleware import AgentOSMiddleware
from runtime.agentos.model import create_model_router
from runtime.agentos.model_administration import create_model_administration_router
from runtime.agentos.resume import create_resume_router
from runtime.model.service import ModelService
from runtime.recovery import recover_streaming_runs
from runtime.api.agent.execution import (
    agent_runtime_router as agent_router,
    inspect_agentos_conversation,
    run_agentos_background,
    run_agentos_compatibility,
    run_agentos_conversation,
    stop_agentos_compatibility,
)
from infrastructure.rdb.model_records import fail_detecting_models_on_startup, get_model_by_model_id
from infrastructure.model_adapter import get_adapter_from_config
from runtime.agentos.evaluation import create_evaluation_router
from runtime.api.voice.streaming import voice_runtime_router as voice_router
from runtime.api.skill.creation import skill_creator_router
from contracts.constants.environment import RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS
from runtime.api.exception_handler import ExceptionHandlerMiddleware
from runtime.api.identity_routes import is_runtime_service_request
from nexent.core.concurrency import (
    ManagedTaskSpec,
    ManagerState,
    clear_default_thread_manager,
    set_default_thread_manager,
)
from runtime.thread_management import runtime_thread_manager, shutdown_agent_stream_tasks
from infrastructure.redis.run_state import runtime_state_service

logger = logging.getLogger("runtime_app")


async def recover_runtime_state():
    from services.workspace_cleanup_service import cleanup_orphaned_agent_workspaces

    await runtime_thread_manager.run(
        "control-io",
        ManagedTaskSpec(
            task_name="recover-runtime-tasks",
            owner="runtime.api.application",
        ),
        recover_streaming_runs,
    )
    cleanup_orphaned_agent_workspaces()


@asynccontextmanager
async def runtime_lifespan(_app):
    if runtime_thread_manager.state is ManagerState.CREATED:
        runtime_thread_manager.start()
    set_default_thread_manager(runtime_thread_manager)
    runtime_state_service.set_thread_manager(runtime_thread_manager)
    try:
        await runtime_thread_manager.run(
            "control-io",
            ManagedTaskSpec(task_name="recover-model-connectivity", owner="runtime"),
            fail_detecting_models_on_startup,
        )
        await recover_runtime_state()
        yield
    finally:
        shutdown_deadline = time.monotonic() + RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS

        pending_stream_tasks = await shutdown_agent_stream_tasks(timeout=max(0, shutdown_deadline - time.monotonic()))
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
            await runtime_thread_manager.shutdown(timeout=max(0, shutdown_deadline - time.monotonic()))
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
app.add_middleware(AgentOSMiddleware)
app.include_router(create_compatibility_router(
    run_agentos_compatibility, stop_agentos_compatibility, conversation_run=run_agentos_conversation,
))
app.include_router(create_background_router(run_agentos_background, inspect_agentos_conversation))

app.include_router(create_model_router(ModelService(get_model_by_model_id, get_adapter_from_config)))
app.include_router(create_model_administration_router())
app.include_router(agent_router)
app.include_router(create_evaluation_router())
app.include_router(create_resume_router())
app.include_router(voice_router)
app.include_router(skill_creator_router)
