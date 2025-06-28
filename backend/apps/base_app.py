import logging

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .agent_app import router as agent_router
from .config_sync_app import router as config_sync_router
from .conversation_management_app import router as conversation_management_router
from .elasticsearch_app import router as elasticsearch_router
from .me_model_managment_app import router as me_model_manager_router
from .model_managment_app import router as model_manager_router
from .image_app import router as proxy_router
from .file_management_app import router as file_manager_router
from .voice_app import router as voice_router
from .tool_config_app import router as tool_config_router
from .prompt_app import router as prompt_router
from .knowledge_summary_app import router as summary_router
from .tenant_config_app import router as tenant_config_router
from .remote_mcp_app import router as remote_mcp_router 

app = FastAPI(root_path="/api")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

app.include_router(me_model_manager_router)
app.include_router(model_manager_router)
app.include_router(config_sync_router)
app.include_router(agent_router)
app.include_router(conversation_management_router)
app.include_router(elasticsearch_router)
app.include_router(voice_router)
app.include_router(file_manager_router)
app.include_router(proxy_router)
app.include_router(tool_config_router)
app.include_router(summary_router)
app.include_router(prompt_router)
app.include_router(tenant_config_router)
app.include_router(remote_mcp_router)

# Global exception handler for HTTP exceptions
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    logging.error(f"HTTPException: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"message": exc.detail},
    )


# Global exception handler for all uncaught exceptions
@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    logging.error(f"Generic Exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"message": "Internal server error, please try again later."},
    )
