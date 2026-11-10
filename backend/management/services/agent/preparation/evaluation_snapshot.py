# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Export the portable subset of the existing evaluation compiler."""

from datetime import datetime

from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from contracts.agent import AgentRequest
from contracts.agentos import (
    AgentResource, EvaluationAgentOptions, EvaluationAgentRun, EvaluationFileTool, FileToolDescription,
    ModelBindings, PreparedEvaluationRun, RunHistoryMessage, RunInput, RunModelBinding, ToolBinding,
)
from contracts.constants.environment import NEXENT_SANDBOX_DEFAULT_LEVEL
from infrastructure.agent_model_config import create_model_config_from_record
from infrastructure.rdb.model_records import get_model_records


async def prepare_evaluation_snapshot(request: EvaluationAgentRun, user_id: str, tenant_id: str):
    if NEXENT_SANDBOX_DEFAULT_LEVEL.strip().lower() != "local":
        return None

    from management.services.agent.preparation.run import create_agent_run_info

    history = AgentRequest(
        agent_id=request.agent_id, query=request.query, history=request.history, is_debug=True,
    ).history
    return await create_agent_run_info(
        agent_id=request.agent_id, minio_files=None, query=request.query, history=history,
        tenant_id=tenant_id, user_id=user_id, allow_memory_search=False, is_debug=True,
        override_version_no=request.version_no, conversation_id=request.conversation_id,
        enable_automation_tool=False, export_evaluation=True,
    )


def _file_tool_binding(tool):
    builtin = next((item for item in EvaluationFileTool if item.value == tool.name), None)
    if builtin is None or tool.class_name != builtin.class_name or tool.source != "builtin":
        return None
    if (set(tool.params or {}) - {"workspace_path"}) or (set(tool.metadata or {}) - {
        "workspace_path", "minio_client", "user_id", "tenant_id", "run_id", "validate_url_access",
    }):
        return None
    description = FileToolDescription(
        description=tool.description, description_zh=tool.description_zh,
        inputs=tool.inputs, output_type=tool.output_type,
    )
    return ToolBinding(tool_id=builtin.value, version="1", parameters=description.model_dump(mode="json"))


def export_snapshot(agent, models, query, history, *, tenant_id, conversation_id, language):
    if any((
        agent.worker_agents, agent.external_a2a_agents, agent.pre_run_tool_events,
        agent.sandbox_policy is not None, agent.enable_planning,
    )):
        return None

    tools = []
    for tool in agent.tools:
        binding = _file_tool_binding(tool)
        if binding is None:
            return None
        tools.append(binding)

    # Resolve a single exact record. Custom overrides stay on the compatibility path.
    candidates = get_model_records({"display_name": agent.model_name, "model_type": "llm"}, tenant_id)
    if len(candidates) != 1:
        return None
    record = candidates[0]
    effective = next((model for model in models if model.cite_name == agent.model_name), None)
    if effective is None or effective != create_model_config_from_record(record):
        return None
    revision = record.get("update_time") or record.get("create_time")
    if isinstance(revision, datetime):
        revision = revision.isoformat()
    try:
        profile = agent.model_dump(mode="json", include=set(EvaluationAgentOptions.model_fields))
        context_config = profile.get("context_manager_config")
        if context_config is not None:
            for key in ("history_summary_sink", "history_summary_status_sink"):
                if context_config.pop(key, None) is not None:
                    return None
        for item in profile.get("context_items") or []:
            if item["type"] in {"skill", "memory", "long_term_memory"}:
                return None
        return PreparedEvaluationRun(
            mode="nexent", language=language, conversation_id=conversation_id,
            resource=AgentResource(
                agent_id=agent.agent_id, version_no=agent.version_no, name=agent.name,
                description=agent.description, prompt_templates=agent.prompt_templates or {},
                max_steps=agent.max_steps, tools=tools, evaluation_options=EvaluationAgentOptions(**profile),
            ),
            models=ModelBindings(llm=RunModelBinding(
                model_id=record["model_id"], alias=agent.model_name, revision=revision or "legacy",
            )),
            input=RunInput(
                query=query, history=[RunHistoryMessage(role=item.role, content=item.content) for item in (history or [])],
            ),
        )
    except (ValidationError, PydanticSerializationError):
        return None
