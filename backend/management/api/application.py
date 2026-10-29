# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from management.utils.app_factory import create_app
from contracts.constants.constants import CONFIG_SERVICE_NAME
import asyncio
import logging
from contextlib import asynccontextmanager

from management.utils.app_factory import create_app
from management.api.agent.agent import agent_config_router as agent_router
from management.api.agent.agent_repository import agent_repository_router
from management.api.skill.skill_repository import skill_repository_router
from management.api.configuration.config_sync import router as config_sync_router
from management.api.knowledge_base.datamate import router as datamate_router
from management.api.knowledge_base.vectordatabase import router as vectordatabase_router
from management.api.knowledge_base.dify import router as dify_router
from management.api.knowledge_base.idata import router as idata_router
from management.api.knowledge_base.ragflow import router as ragflow_router
from management.api.file.file_management import file_management_config_router as file_manager_router
from management.api.file.image import router as proxy_router
from management.api.knowledge_base.knowledge_summary import router as summary_router
from management.api.identity.mock_user_management import router as mock_user_management_router
from management.api.model.model_managment import router as model_manager_router
from management.api.identity.oauth import router as oauth_router
from management.api.prompt.prompt import router as prompt_router
from management.api.mcp.mcp_management import router as mcp_management_router
from management.api.mcp.remote_mcp import router as remote_mcp_router
from management.api.skill.skill import router as skill_router
from management.api.configuration.tenant_config import router as tenant_config_router
from management.api.tool.tool_config import router as tool_config_router
from management.api.identity.user_management import router as user_management_router
from management.api.voice.voice import voice_config_router as voice_router
from management.api.identity.tenant import router as tenant_router
from management.api.identity.group import router as group_router
from management.api.identity.user import router as user_router
from management.api.identity.api_key import router as api_key_router
from management.api.identity.invitation import router as invitation_router
from management.api.notification.notification import router as notification_router
from management.api.a2a.a2a_client import router as a2a_client_router
from management.api.monitoring.monitoring import router as monitoring_router
from management.api.a2a.a2a_server import router as a2a_server_router
from management.api.knowledge_base.haotian import router as haotian_router
from management.api.knowledge_base.ind_aidp import router as ind_aidp_router
from management.api.evaluation.evaluation_set import router as evaluation_set_router
from management.api.evaluation.agent_evaluation import router as agent_evaluation_router
from management.api.evaluation.evaluator import router as evaluator_router
from management.api.evaluation.evaluation_annotation import router as evaluation_annotation_router
from management.api.identity.cas import router as cas_router
from management.api.memory.memory_config import router as memory_config_router
from management.api.memory.memory_record import router as memory_record_router
from management.api.memory.memory_long_term import router as memory_long_term_router
from management.api.memory.memory_dreaming import router as memory_dreaming_router
from management.api.memory.memory_provider import router as memory_provider_router
from management.api.tag.tag_management import router as tag_management_router
from management.api.knowledge_base.quota import tenant_quota_router, platform_quota_router, personal_quota_router
from contracts.constants.environment import AIDP_API_KEY, AIDP_SERVER_URL, ENABLE_AIDP_KNOWLEDGE, ENABLE_AGENT_WORKBENCH, IS_SPEED_MODE, RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS
from nexent.core.concurrency import (
    ManagedTaskSpec,
    ManagerState,
    clear_default_thread_manager,
    run_blocking,
    set_default_thread_manager,
)
from contracts.constants.constants import CONFIG_SERVICE_NAME
from infrastructure.concurrency import config_thread_manager

logger = logging.getLogger("base_app")


async def recover_config_tasks_on_startup():
    from management.services.evaluation.maintenance import start as start_eval_maintenance
    from management.recovery import (
        recover_config_tasks,
        schedule_interrupted_upload_cleanup,
        schedule_workbench_main_backfill,
    )

    await config_thread_manager.run(
        "control-io",
        ManagedTaskSpec(
            task_name="recover-config-tasks",
            owner="management.api.application",
        ),
        recover_config_tasks,
    )
    start_eval_maintenance(config_thread_manager)
    await schedule_interrupted_upload_cleanup(CONFIG_SERVICE_NAME)
    if ENABLE_AGENT_WORKBENCH:
        schedule_workbench_main_backfill()


async def validate_external_service_configuration():
    """Validate enabled external service configuration before startup."""
    if ENABLE_AIDP_KNOWLEDGE and (not AIDP_SERVER_URL or not AIDP_API_KEY):
        raise RuntimeError("AIDP_SERVER_URL and AIDP_API_KEY are required when ENABLE_AIDP_KNOWLEDGE=true")



async def start_dreaming_scheduler():
    from management.services.memory.dreaming.scheduler import dreaming_scheduler

    await dreaming_scheduler.start()


async def stop_dreaming_scheduler():
    from management.services.memory.dreaming.scheduler import dreaming_scheduler

    await dreaming_scheduler.stop()


@asynccontextmanager
async def config_lifespan(_app):
    if config_thread_manager.state is ManagerState.CREATED:
        config_thread_manager.start()
    set_default_thread_manager(config_thread_manager)
    try:
        from management.services.model.outlet_migration import migrate_legacy_outlets

        migration = await run_blocking("model-outlet-upgrade", migrate_legacy_outlets)
        logger.info("LLM outlet upgrade: migrated=%s failed=%s", migration["migrated"], migration["failed"])
        await recover_config_tasks_on_startup()
        await validate_external_service_configuration()
        await start_dreaming_scheduler()
        yield
    finally:
        # Preserve the scheduler's existing graceful shutdown behavior. Task
        # state recovery remains exclusively in the startup path above.
        await stop_dreaming_scheduler()
        from management.services.evaluation.maintenance import stop as stop_eval_maintenance

        stop_eval_maintenance()
        try:
            await config_thread_manager.shutdown(timeout=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS)
        finally:
            clear_default_thread_manager(config_thread_manager)


app = create_app(
    title="Nexent Config API",
    description="Configuration APIs",
    lifespan=config_lifespan,
)
if hasattr(app, "state"):
    app.state.thread_manager = config_thread_manager


@app.get("/internal/thread-capacity", include_in_schema=False)
async def thread_capacity():
    """Return process-local Config capacity for trusted service probes."""
    return config_thread_manager.snapshot()


app.include_router(model_manager_router)
app.include_router(config_sync_router)
app.include_router(agent_router)
app.include_router(agent_repository_router)
app.include_router(skill_repository_router)
app.include_router(vectordatabase_router)
app.include_router(datamate_router)
app.include_router(voice_router)
app.include_router(file_manager_router)
app.include_router(proxy_router)
app.include_router(tool_config_router)
app.include_router(dify_router)
app.include_router(idata_router)
app.include_router(ragflow_router)
app.include_router(monitoring_router)

# Choose user management router based on IS_SPEED_MODE
if IS_SPEED_MODE:
    logger.info("Speed mode enabled - using mock user management router")
    app.include_router(mock_user_management_router)
else:
    logger.info("Normal mode - using real user management router")
    app.include_router(user_management_router)

app.include_router(oauth_router)
app.include_router(cas_router)

app.include_router(summary_router)
app.include_router(prompt_router)
app.include_router(skill_router)
app.include_router(tenant_config_router)
app.include_router(mcp_management_router)
app.include_router(remote_mcp_router)
app.include_router(tenant_router)
app.include_router(group_router)
app.include_router(user_router)
app.include_router(api_key_router)
app.include_router(invitation_router)
app.include_router(notification_router)
app.include_router(a2a_client_router)
app.include_router(a2a_server_router)
app.include_router(haotian_router)
app.include_router(ind_aidp_router)
app.include_router(evaluation_set_router)
app.include_router(agent_evaluation_router)
app.include_router(evaluator_router)
app.include_router(evaluation_annotation_router)
if ENABLE_AIDP_KNOWLEDGE:
    from ext_components.aidp.apps.aidp_mgmt_app import aidp_mgmt_router

    app.include_router(aidp_mgmt_router)
# New memory architecture routers (upstream #3497)
app.include_router(memory_config_router)
app.include_router(memory_record_router)
app.include_router(memory_long_term_router)
app.include_router(tenant_quota_router)
app.include_router(platform_quota_router)
app.include_router(personal_quota_router)
app.include_router(memory_dreaming_router)
app.include_router(memory_provider_router)
app.include_router(tag_management_router)
