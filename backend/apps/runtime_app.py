import logging

from apps.app_factory import create_app
from apps.agent_app import agent_runtime_router as agent_router
from apps.voice_app import voice_runtime_router as voice_router
from apps.conversation_management_app import router as conversation_management_router
from apps.memory_config_app import router as memory_config_router
from apps.file_management_app import file_management_runtime_router as file_management_router
from middleware.exception_handler import ExceptionHandlerMiddleware

# Create logger instance
logger = logging.getLogger("runtime_app")

# Create FastAPI app with common configurations
app = create_app(title="Nexent Runtime API", description="Runtime APIs")

# Add global exception handler middleware
app.add_middleware(ExceptionHandlerMiddleware)

app.include_router(agent_router)
app.include_router(conversation_management_router)
app.include_router(memory_config_router)
app.include_router(file_management_router)
app.include_router(voice_router)
