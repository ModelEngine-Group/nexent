# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Materialize a prepared synthetic evaluation inside Runtime."""

import asyncio
from functools import partial
from uuid import uuid4
from datetime import datetime

from fastapi import HTTPException
from pydantic import ValidationError

from contracts.agentos import EvaluationAgentResult, EvaluationFileTool, FileToolDescription, PreparedEvaluationRun
from contracts.constants.environment import (
    AGENT_WORKSPACE_ROOT, NEXENT_SANDBOX_DEFAULT_LEVEL, NEXENT_TOOL_FASTPATH_ALLOWED_TOOLS, NEXENT_TOOL_FASTPATH_ENABLED,
)
from infrastructure.agent_model_config import create_model_config_from_record
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.object_storage.read_access import require_s3_read_access
from infrastructure.rdb.model_records import get_model_by_model_id
from infrastructure.workspace_paths import create_run_workspace
from nexent.core.agents.agent_model import AgentConfig, AgentHistory, AgentRunInfo, ToolConfig
from nexent.core.agents.context import ContextManagerConfig
from nexent.core.agents.context_input import build_authorized_context_input
from nexent.core.concurrency import run_blocking
from runtime.adapters.nexent.factory import build_run_info
from runtime.adapters.nexent.runner import agent_run
from runtime.agentos.evaluation import collect_observer_output
from runtime.executions import AgentRunAlreadyActiveError, agent_run_manager
from runtime.thread_management import runtime_thread_manager, unregister_after_worker_exit


def _materialize_file_tools(bindings, actor, workspace_path, workspace_run_id):
    if not bindings:
        return []

    from infrastructure.object_storage.client import minio_client

    metadata = {
        "workspace_path": workspace_path,
        "minio_client": minio_client,
        "user_id": actor.user_id,
        "tenant_id": actor.tenant_id,
        "run_id": workspace_run_id,
        "validate_url_access": partial(require_s3_read_access, user_id=actor.user_id, tenant_id=actor.tenant_id),
    }
    tools = []
    seen = set()
    for binding in bindings:
        if binding.version != "1" or binding.credential_ref is not None or binding.tool_id in seen:
            raise ValueError("Unsupported file tool binding")
        builtin = EvaluationFileTool(binding.tool_id)
        description = FileToolDescription.model_validate(binding.parameters)
        tools.append(ToolConfig(
            class_name=builtin.class_name, name=builtin.value, source="builtin", usage="builtin",
            params={"workspace_path": workspace_path}, metadata=metadata,
            **description.model_dump(),
        ))
        seen.add(builtin.value)
    return tools


def _agent_options(resource):
    if resource.evaluation_options is None:
        return {}
    options = resource.evaluation_options.model_dump()
    context_config = options.pop("context_manager_config")
    if context_config is not None:
        if "history_summary_sink" in context_config or "history_summary_status_sink" in context_config:
            raise ValueError("Callbacks must be constructed by Runtime")
        options["context_manager_config"] = ContextManagerConfig(**context_config)
    if options.get("verification_config") is None:
        del options["verification_config"]
    return options


def prepare_evaluation_run(payload: PreparedEvaluationRun, actor: ServicePrincipal) -> AgentRunInfo:
    resource = payload.resource
    if any((
        resource.skill_refs, resource.mcp_server_refs, resource.knowledge_base_refs,
        resource.memory_ref is not None, resource.subagents, resource.sandbox_policy is not None,
        NEXENT_SANDBOX_DEFAULT_LEVEL.strip().lower() != "local",
        payload.input.attachment_refs, payload.models.summary, payload.models.verifier,
        payload.models.embedding, payload.models.rerank,
    )):
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_RESOURCE_UNSUPPORTED"})

    workspace_run_id = uuid4().hex
    workspace_path = create_run_workspace(actor.user_id, workspace_run_id, workspace_root=AGENT_WORKSPACE_ROOT)
    try:
        tools = _materialize_file_tools(resource.tools, actor, workspace_path, workspace_run_id)
        options = _agent_options(resource)
        agent_config = AgentConfig(
            name=resource.name, description=resource.description, prompt_templates=resource.prompt_templates,
            agent_id=resource.agent_id, version_no=resource.version_no, tools=tools, model_name=payload.models.llm.alias,
            max_steps=resource.max_steps, invocation_name=f"agent_{resource.agent_id}_v{resource.version_no}",
            runtime_ref=f"agent:{resource.agent_id}:v{resource.version_no}", **options,
        )
    except (ValidationError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_RESOURCE_UNSUPPORTED"}) from exc

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
        agent_config=agent_config,
        workspace_path=workspace_path,
        workspace_run_id=workspace_run_id,
        capacity_snapshot=agent_config.capacity_snapshot,
        context_budget_snapshot=agent_config.context_budget_snapshot,
        tool_fastpath_enabled=NEXENT_TOOL_FASTPATH_ENABLED,
        tool_fastpath_allowed_tools=list(NEXENT_TOOL_FASTPATH_ALLOWED_TOOLS),
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
