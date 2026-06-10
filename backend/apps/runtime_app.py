import logging

from apps.app_factory import create_app
from apps.agent_app import agent_runtime_router as agent_router
from apps.voice_app import voice_runtime_router as voice_router
from apps.conversation_management_app import router as conversation_management_router
from apps.memory_config_app import router as memory_config_router
from apps.file_management_app import file_management_runtime_router as file_management_router
from apps.skill_app import skill_creator_router
from middleware.exception_handler import ExceptionHandlerMiddleware
from services.scheduled_task_scheduler import scheduled_task_scheduler

# Create logger instance
logger = logging.getLogger("runtime_app")


async def _start_scheduler():
    scheduled_task_scheduler.start()


async def _stop_scheduler():
    scheduled_task_scheduler.stop()


# Create FastAPI app with common configurations and scheduler lifecycle hooks
app = create_app(
    title="Nexent Runtime API",
    description="Runtime APIs",
    lifespan_startup=_start_scheduler,
    lifespan_shutdown=_stop_scheduler,
)

# Add global exception handler middleware
app.add_middleware(ExceptionHandlerMiddleware)

app.include_router(agent_router)
app.include_router(conversation_management_router)
app.include_router(memory_config_router)
app.include_router(file_management_router)
app.include_router(voice_router)
app.include_router(skill_creator_router)
