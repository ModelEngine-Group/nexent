import logging
from contextlib import asynccontextmanager

from apps.app_factory import create_app
from apps.agent_app import agent_runtime_router as agent_router
from apps.internal_agent_app import router as internal_agent_router
from apps.agent_automation_app import conversation_automation_router, router as agent_automation_router
from apps.voice_app import voice_runtime_router as voice_router
from apps.conversation_management_app import router as conversation_management_router
from apps.conversation_share_app import router as conversation_share_router
from apps.file_management_app import file_management_runtime_router as file_management_router
from apps.skill_app import skill_creator_router
from middleware.exception_handler import ExceptionHandlerMiddleware
from services.runtime_state_service import runtime_state_service

# Create logger instance
logger = logging.getLogger("runtime_app")

@asynccontextmanager
async def runtime_lifespan(_app):
    """Verify distributed state and manage the automation scheduler lifecycle."""
    from services.agent_automation.scheduler import agent_automation_scheduler

    await runtime_state_service.ping_async()
    await agent_automation_scheduler.start()
    try:
        yield
    finally:
        await agent_automation_scheduler.stop()


# Create FastAPI app with common configurations
app = create_app(
    title="Nexent Runtime API",
    description="Runtime APIs",
    lifespan=runtime_lifespan,
)

# Add global exception handler middleware
app.add_middleware(ExceptionHandlerMiddleware)

app.include_router(agent_router)
app.include_router(internal_agent_router)
app.include_router(agent_automation_router)
app.include_router(conversation_automation_router)
app.include_router(conversation_management_router)
app.include_router(conversation_share_router)
app.include_router(file_management_router)
app.include_router(voice_router)
app.include_router(skill_creator_router)
