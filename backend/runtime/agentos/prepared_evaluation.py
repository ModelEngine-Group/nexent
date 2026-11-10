# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Materialize a prepared synthetic evaluation inside Runtime."""

import asyncio
from datetime import datetime

from fastapi import HTTPException

from contracts.agentos import EvaluationAgentResult, PreparedEvaluationRun
from contracts.constants.environment import NEXENT_SANDBOX_DEFAULT_LEVEL
from infrastructure.agent_model_config import create_model_config_from_record
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.model_records import get_model_by_model_id
from nexent.core.agents.agent_model import AgentConfig, AgentHistory, AgentRunInfo
from nexent.core.agents.context_input import build_authorized_context_input
from nexent.core.concurrency import run_blocking
from runtime.adapters.nexent.factory import build_run_info
from runtime.adapters.nexent.runner import agent_run
from runtime.agentos.evaluation import collect_observer_output
from runtime.executions import AgentRunAlreadyActiveError, agent_run_manager
from runtime.thread_management import runtime_thread_manager, unregister_after_worker_exit


def prepare_evaluation_run(payload: PreparedEvaluationRun, actor: ServicePrincipal) -> AgentRunInfo:
    resource = payload.resource
    if any((
        resource.tools, resource.skill_refs, resource.mcp_server_refs, resource.knowledge_base_refs,
        resource.memory_ref is not None, resource.subagents, resource.sandbox_policy is not None,
        NEXENT_SANDBOX_DEFAULT_LEVEL.strip().lower() != "local",
        payload.input.attachment_refs, payload.models.summary, payload.models.verifier,
        payload.models.embedding, payload.models.rerank,
    )):
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_RESOURCE_UNSUPPORTED"})

    binding = payload.models.llm
    record = get_model_by_model_id(binding.model_id, actor.tenant_id)
    if not record or record.get("tenant_id") != actor.tenant_id or record.get("delete_flag") != "N":
        raise HTTPException(status_code=404, detail={"code": "MODEL_NOT_FOUND"})
    if record.get("model_type") != "llm":
        raise HTTPException(status_code=422, detail={"code": "MODEL_OPERATION_UNSUPPORTED"})
    revision = record.get("update_time") or record.get("create_time")
    if isinstance(revision, datetime):
        revision = revision.isoformat()
    if (revision or "legacy") != binding.revision:
        raise HTTPException(status_code=409, detail={"code": "MODEL_REVISION_MISMATCH"})

    model = create_model_config_from_record(record).model_copy(update={"cite_name": binding.alias})
    info = build_run_info(
        query=payload.input.query,
        history=[AgentHistory(**message.model_dump()) for message in payload.input.history],
        agent_config=AgentConfig(
            name=resource.name, description=resource.description, prompt_templates=resource.prompt_templates,
            agent_id=resource.agent_id, version_no=resource.version_no, tools=[], model_name=binding.alias,
            max_steps=resource.max_steps,
        ),
        model_config_list=[model],
        language=payload.language,
        conversation_id=payload.conversation_id,
        user_id=actor.user_id,
        tenant_id=actor.tenant_id,
    )
    info.context_input = build_authorized_context_input(info)
    return info


async def execute_prepared_evaluation(payload: PreparedEvaluationRun, actor: ServicePrincipal) -> EvaluationAgentResult:
    info = await run_blocking(
        "agentos-prepare-evaluation", prepare_evaluation_run, payload, actor,
        lane="control-io", owner="runtime",
    )
    try:
        agent_run_manager.register_agent_run(payload.conversation_id, info, actor.user_id)
    except AgentRunAlreadyActiveError as exc:
        raise HTTPException(status_code=409, detail={"code": "AGENTOS_RUN_ALREADY_ACTIVE"}) from exc

    status = "failed"
    try:
        result = await collect_observer_output(info, agent_run, runtime_thread_manager)
        status = info.attempt_outcome or "completed"
        return result
    except asyncio.CancelledError:
        status = "stopped"
        raise
    finally:
        unregister_after_worker_exit(agent_run_manager, payload.conversation_id, actor.user_id, status, info)
