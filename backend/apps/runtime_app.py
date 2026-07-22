import logging

from apps.app_factory import create_app
from apps.agent_app import agent_runtime_router as agent_router
from apps.agent_automation_app import conversation_automation_router, router as agent_automation_router
from apps.voice_app import voice_runtime_router as voice_router
from apps.conversation_management_app import router as conversation_management_router
from apps.conversation_share_app import router as conversation_share_router
from apps.memory_config_app import router as memory_config_router
from apps.file_management_app import file_management_runtime_router as file_management_router
from apps.skill_app import skill_creator_router
from middleware.exception_handler import ExceptionHandlerMiddleware

# Create logger instance
logger = logging.getLogger("runtime_app")

# Create FastAPI app with common configurations
app = create_app(title="Nexent Runtime API", description="Runtime APIs")

# Add global exception handler middleware
app.add_middleware(ExceptionHandlerMiddleware)

app.include_router(agent_router)
app.include_router(agent_automation_router)
app.include_router(conversation_automation_router)
app.include_router(conversation_management_router)
app.include_router(conversation_share_router)
app.include_router(memory_config_router)
app.include_router(file_management_router)
app.include_router(voice_router)
app.include_router(skill_creator_router)


@app.on_event("startup")
async def start_agent_automation_scheduler():
    from services.agent_automation.scheduler import agent_automation_scheduler

    await agent_automation_scheduler.start()


@app.on_event("shutdown")
async def stop_agent_automation_scheduler():
    from services.agent_automation.scheduler import agent_automation_scheduler

    await agent_automation_scheduler.stop()
