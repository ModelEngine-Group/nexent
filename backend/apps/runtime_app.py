import asyncio
import logging
from contextlib import asynccontextmanager

from apps.app_factory import create_app
from apps.agent_app import agent_runtime_router as agent_router
from apps.agent_automation_app import conversation_automation_router, router as agent_automation_router
from apps.agent_evaluation_runtime_app import router as agent_evaluation_runtime_router
from apps.voice_app import voice_runtime_router as voice_router
from apps.conversation_management_app import router as conversation_management_router
from apps.conversation_share_app import router as conversation_share_router
from apps.file_management_app import file_management_runtime_router as file_management_router
from apps.skill_app import skill_creator_router
from middleware.exception_handler import ExceptionHandlerMiddleware

logger = logging.getLogger("runtime_app")

async def start_agent_automation_scheduler():
    from services.agent_automation.scheduler import agent_automation_scheduler
    from services.startup_recovery_service import recover_runtime_tasks
    from services.workspace_cleanup_service import cleanup_orphaned_agent_workspaces

    await asyncio.to_thread(recover_runtime_tasks)
    cleanup_orphaned_agent_workspaces()
    await agent_automation_scheduler.start()


async def stop_agent_automation_scheduler():
    from services.agent_automation.scheduler import agent_automation_scheduler

    await agent_automation_scheduler.stop()


@asynccontextmanager
async def runtime_lifespan(_app):
    await start_agent_automation_scheduler()
    try:
        yield
    finally:
        await stop_agent_automation_scheduler()


app = create_app(
    title="Nexent Runtime API",
    description="Runtime APIs",
    lifespan=runtime_lifespan,
)

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
