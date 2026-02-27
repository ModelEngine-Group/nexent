import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.agent_app import agent_runtime_router as agent_router
from apps.voice_app import voice_runtime_router as voice_router
from apps.conversation_management_app import router as conversation_management_router
from apps.memory_config_app import router as memory_config_router
from apps.file_management_app import file_management_runtime_router as file_management_router

# Import monitoring utilities
from utils.monitoring import monitoring_manager
# Import exception handling
from consts.exceptions import AppException
from middleware.exception_handler import ExceptionHandlerMiddleware

# Create logger instance
logger = logging.getLogger("runtime_app")
app = FastAPI(root_path="/api")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add global exception handler middleware
app.add_middleware(ExceptionHandlerMiddleware)

app.include_router(agent_router)
app.include_router(conversation_management_router)
app.include_router(memory_config_router)
app.include_router(file_management_router)
app.include_router(voice_router)

# Initialize monitoring for the application
monitoring_manager.setup_fastapi_app(app)


# Global exception handler for HTTP exceptions
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    logger.error(f"HTTPException: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"message": exc.detail},
    )


# Global exception handler for AppException
@app.exception_handler(AppException)
async def app_exception_handler(request, exc):
    logger.error(f"AppException: {exc.error_code.value} - {exc.message}")
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "code": exc.error_code.value,
            "message": exc.message,
            "details": exc.details if exc.details else None
        },
    )


# Global exception handler for all uncaught exceptions (excluding AppException)
@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    # Don't catch AppException - it has its own handler
    if isinstance(exc, AppException):
        return await app_exception_handler(request, exc)

    logger.error(f"Generic Exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"message": "Internal server error, please try again later."},
    )
