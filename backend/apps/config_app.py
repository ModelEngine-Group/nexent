import logging

from apps.app_factory import create_app
from apps.agent_app import agent_config_router as agent_router
from apps.config_sync_app import router as config_sync_router
from apps.datamate_app import router as datamate_router
from apps.vectordatabase_app import router as vectordatabase_router
from apps.dify_app import router as dify_router
from apps.idata_app import router as idata_router
from apps.file_management_app import (
    file_management_config_router as file_manager_router,
)
from apps.image_app import router as proxy_router
from apps.knowledge_summary_app import router as summary_router
from apps.mock_user_management_app import router as mock_user_management_router
from apps.model_managment_app import router as model_manager_router
from apps.oauth_app import router as oauth_router
from apps.prompt_app import router as prompt_router
from apps.prompt_template_app import router as prompt_template_router
from apps.mcp_management_app import router as mcp_management_router
from apps.remote_mcp_app import router as remote_mcp_router
from apps.skill_app import router as skill_router
from apps.tenant_config_app import router as tenant_config_router
from apps.tool_config_app import router as tool_config_router
from apps.user_management_app import router as user_management_router
from apps.voice_app import voice_config_router as voice_router
from apps.tenant_app import router as tenant_router
from apps.group_app import router as group_router
from apps.user_app import router as user_router
from apps.invitation_app import router as invitation_router
from apps.a2a_client_app import router as a2a_client_router
from apps.monitoring_app import router as monitoring_router
from apps.a2a_server_app import router as a2a_server_router
from apps.haotian_app import router as haotian_router
from consts.const import IS_SPEED_MODE
from services.prompt_template_service import sync_system_default_prompt_template

# Create logger instance
logger = logging.getLogger("base_app")

# Create FastAPI app with common configurations
app = create_app(title="Nexent Config API", description="Configuration APIs")


@app.on_event("startup")
async def sync_default_prompt_template_on_startup():
    """Sync the YAML-backed system default prompt template into the database on startup."""
    try:
        sync_system_default_prompt_template()
        logger.info("System default prompt template synced successfully.")
    except Exception as exc:
        logger.error(f"Failed to sync system default prompt template: {str(exc)}")

app.include_router(model_manager_router)
app.include_router(config_sync_router)
app.include_router(agent_router)
app.include_router(vectordatabase_router)
app.include_router(datamate_router)
app.include_router(voice_router)
app.include_router(file_manager_router)
app.include_router(proxy_router)
app.include_router(tool_config_router)
app.include_router(dify_router)
app.include_router(idata_router)
app.include_router(monitoring_router)

# Choose user management router based on IS_SPEED_MODE
if IS_SPEED_MODE:
    logger.info("Speed mode enabled - using mock user management router")
    app.include_router(mock_user_management_router)
else:
    logger.info("Normal mode - using real user management router")
    app.include_router(user_management_router)

app.include_router(oauth_router)

app.include_router(summary_router)
app.include_router(prompt_router)
app.include_router(prompt_template_router)
app.include_router(skill_router)
app.include_router(tenant_config_router)
app.include_router(mcp_management_router)
app.include_router(remote_mcp_router)
app.include_router(tenant_router)
app.include_router(group_router)
app.include_router(user_router)
app.include_router(invitation_router)
app.include_router(a2a_client_router)
app.include_router(a2a_server_router)
app.include_router(haotian_router)
