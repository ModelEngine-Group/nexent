# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from management.api.northbound_application import northbound_lifespan
from management.api.northbound import router as northbound_router, a2a_router
from management.api.identity.gateway_identity import router as gateway_identity_router
import logging
from contextlib import asynccontextmanager

from backend.http.server.app_factory import create_app
from management.api.agent.agent import agent_config_router as agent_router
from management.api.agent.conversation_run import router as conversation_run_router
from management.api.automation.agent_automation import (
    conversation_automation_router,
    router as agent_automation_router,
)
from management.api.automation.agentos_callback import router as automation_callback_router
from management.api.conversation.conversation_management import router as conversation_router
from management.api.conversation.workbench_pins import router as workbench_pins_router
from management.api.conversation.conversation_share import router as conversation_share_router
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
from management.api.file.storage import router as file_storage_router
from management.api.knowledge_base.knowledge_summary import router as summary_router
from management.api.identity.mock_user_management import router as mock_user_management_router
from management.api.model.model_managment import router as model_manager_router
from management.api.identity.oauth import router as oauth_router
from management.api.mcp.mcp_management import router as mcp_management_router
from management.api.mcp.remote_mcp import router as remote_mcp_router
from management.api.skill.skill import router as skill_router
from management.api.configuration.tenant_config import router as tenant_config_router
from management.api.tool.tool_config import router as tool_config_router
from management.api.identity.user_management import router as user_management_router
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
from contracts.constants.environment import AIDP_API_KEY, AIDP_SERVER_URL, ENABLE_AIDP_KNOWLEDGE, ENABLE_AGENT_WORKBENCH, IS_SPEED_MODE
from nexent.core.concurrency import (
    ManagedTaskSpec,
)
from management.thread_management import config_thread_manager

logger = logging.getLogger("base_app")


async def recover_config_tasks_on_startup():
    from management.services.evaluation.maintenance import start as start_eval_maintenance
    from management.recovery import (
        recover_config_tasks,
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
async def automation_lifespan():
    from management.services.automation.scheduler import agent_automation_scheduler, recover_automation_runs

    await config_thread_manager.run(
        "control-io",
        ManagedTaskSpec(task_name="recover-automation-runs", owner="management.api.application"),
        recover_automation_runs,
    )
    await agent_automation_scheduler.start()
    try:
        yield
    finally:
        await agent_automation_scheduler.stop()


@asynccontextmanager
async def config_lifespan(_app):
    from management.services.agent.prepared_turn import prepared_turn_lifespan

    # One Management manager owns ordinary and Northbound requests and recovery.
    async with northbound_lifespan(_app):
        maintenance_started = False
        dreaming_started = False
        try:
            await recover_config_tasks_on_startup()
            maintenance_started = True
            await validate_external_service_configuration()
            dreaming_started = True
            await start_dreaming_scheduler()
            async with automation_lifespan(), prepared_turn_lifespan():
                yield
        finally:
            try:
                if dreaming_started:
                    await stop_dreaming_scheduler()
            finally:
                if maintenance_started:
                    from management.services.evaluation.maintenance import stop as stop_eval_maintenance

                    stop_eval_maintenance()


app = create_app(
    title="Nexent Config API",
    description="Configuration APIs",
    lifespan=config_lifespan,
    gateway_identity_audience="management",
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
app.include_router(conversation_run_router)
app.include_router(agent_automation_router)
app.include_router(automation_callback_router)
app.include_router(conversation_automation_router)
app.include_router(workbench_pins_router)
app.include_router(conversation_share_router)
app.include_router(conversation_router)
app.include_router(agent_repository_router)
app.include_router(skill_repository_router)
app.include_router(vectordatabase_router)
app.include_router(datamate_router)
app.include_router(file_manager_router)
app.include_router(file_storage_router)
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

# Northbound and A2A business routes share Management lifecycle and ownership.
app.include_router(northbound_router)
app.include_router(a2a_router)
app.include_router(gateway_identity_router)
