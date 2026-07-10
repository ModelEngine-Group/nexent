"""Runtime preparation boundary for legacy smolagents-compatible runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from consts.const import AGENT_RUNTIME_PROVIDER_SMOLAGENTS, LANGUAGE

from .models import AgentRunRequestContext, AssemblyState
from .providers import KnowledgeProvider
from .tool_schema import tool_spec_from_legacy_tool_config


@dataclass(frozen=True)
class RuntimeMemoryPreview:
    """Request-scoped memory state needed by the Runtime API Layer."""

    enabled: bool
    metadata: dict[str, Any]
    user_config: Any | None = None


@dataclass(frozen=True)
class RuntimeRunPreparation:
    """Prepared runtime inputs consumed by the streaming layer."""

    agent_run_info: Any
    memory_context: Any


def preview_runtime_memory(
    user_id: str,
    tenant_id: str,
    agent_id: int | str,
    *,
    skip_query: bool = False,
) -> RuntimeMemoryPreview:
    """Return memory preview metadata without exposing DB/service calls to API code."""
    from services.memory_config_service import build_memory_context

    memory_context = build_memory_context(
        user_id,
        tenant_id,
        agent_id,
        skip_query=skip_query,
    )
    user_config = getattr(memory_context, "user_config", None)
    return RuntimeMemoryPreview(
        enabled=bool(getattr(user_config, "memory_switch", False)),
        metadata={
            "agent_share_option": getattr(user_config, "agent_share_option", "unknown"),
            "disable_agent_ids": list(getattr(user_config, "disable_agent_ids", []) or []),
            "disable_user_agent_ids": list(
                getattr(user_config, "disable_user_agent_ids", []) or []
            ),
        },
        user_config=user_config,
    )


async def prepare_runtime_agent_run(
    agent_request: Any,
    user_id: str,
    tenant_id: str,
    *,
    language: str = LANGUAGE["ZH"],
    allow_memory_search: bool = True,
    run_request_context: AgentRunRequestContext | None = None,
) -> RuntimeRunPreparation:
    """Prepare a legacy AgentRunInfo through the runtime preparation boundary."""
    from agents.create_agent_info import create_agent_run_info
    from services.memory_config_service import build_memory_context

    memory_context = build_memory_context(
        user_id,
        tenant_id,
        agent_request.agent_id,
        skip_query=not allow_memory_search,
    )
    agent_run_info = await create_agent_run_info(
        agent_id=agent_request.agent_id,
        minio_files=agent_request.minio_files,
        query=agent_request.query,
        history=agent_request.history,
        tenant_id=tenant_id,
        user_id=user_id,
        language=language,
        allow_memory_search=allow_memory_search,
        is_debug=agent_request.is_debug,
        override_version_no=agent_request.version_no,
        override_model_id=agent_request.model_id,
        requested_output_tokens=agent_request.requested_output_tokens,
        tool_params=agent_request.tool_params,
    )

    request_context = run_request_context or _request_context_from_agent_request(
        agent_request,
        user_id=user_id,
        tenant_id=tenant_id,
        language=language,
    )
    enhance_legacy_knowledge_tools(agent_run_info, request_context)
    _mount_conversation_context_manager(agent_request, agent_run_info)
    _register_prepared_run(
        agent_request,
        agent_run_info,
        user_id=user_id,
        run_request_context=run_request_context,
    )
    return RuntimeRunPreparation(
        agent_run_info=agent_run_info,
        memory_context=memory_context,
    )


def enhance_legacy_knowledge_tools(
    agent_run_info: Any,
    request_context: AgentRunRequestContext,
) -> None:
    """Enhance legacy KB ToolConfig values through KnowledgeProvider output."""
    agent_config = getattr(agent_run_info, "agent_config", None)
    tools = getattr(agent_config, "tools", None)
    if not isinstance(tools, list):
        return

    knowledge_positions: list[int] = []
    knowledge_specs = []
    for index, tool_config in enumerate(tools):
        class_name = str(getattr(tool_config, "class_name", "") or "")
        if class_name != "KnowledgeBaseSearchTool":
            continue
        metadata = getattr(tool_config, "metadata", None) or {}
        if isinstance(metadata, dict) and metadata.get("capability") == "knowledge":
            continue
        knowledge_positions.append(index)
        knowledge_specs.append(tool_spec_from_legacy_tool_config(tool_config))

    if not knowledge_specs:
        return

    agent_name = str(getattr(agent_config, "name", "") or "root")
    provider = _default_knowledge_provider()
    contribution = provider.contribute(
        request_context,
            AssemblyState(
                agent_record={"name": agent_name},
                tools_by_agent={
                    agent_name: [
                        spec.model_dump() if hasattr(spec, "model_dump") else spec
                        for spec in knowledge_specs
                    ]
                },
            ),
        )
    enhanced_specs = list(contribution.tools_by_agent.get(agent_name, []))
    if len(enhanced_specs) != len(knowledge_positions):
        raise ValueError("KnowledgeProvider did not return all enhanced knowledge tools.")

    updated_tools = list(tools)
    for position, enhanced_spec in zip(knowledge_positions, enhanced_specs):
        original_source = getattr(updated_tools[position], "source", "local")
        updated_tools[position] = _legacy_tool_config_from_spec(
            enhanced_spec,
            source=original_source,
        )
    agent_config.tools = updated_tools


def _legacy_tool_config_from_spec(
    tool_spec: Any,
    *,
    source: str,
) -> Any:
    from nexent.core.agents.agent_model import ToolConfig

    inputs = tool_spec.raw_inputs
    if inputs is None:
        inputs = json.dumps(tool_spec.input_schema or {}, ensure_ascii=False)
    return ToolConfig(
        class_name=tool_spec.class_name or tool_spec.name,
        name=tool_spec.name,
        description=tool_spec.description,
        inputs=inputs,
        output_type=tool_spec.output_type,
        params=dict(tool_spec.params),
        source=source,
        usage=tool_spec.usage,
        metadata=dict(tool_spec.metadata or {}),
    )


def _default_knowledge_provider() -> KnowledgeProvider:
    from database.knowledge_db import get_knowledge_name_map_by_index_names
    from services.vectordatabase_service import (
        ElasticSearchService,
        get_embedding_model_by_index_name,
        get_rerank_model,
        get_vector_db_core,
    )

    return KnowledgeProvider(
        embedding_model_resolver=get_embedding_model_by_index_name,
        rerank_model_resolver=get_rerank_model,
        vector_db_resolver=get_vector_db_core,
        knowledge_name_map_resolver=get_knowledge_name_map_by_index_names,
        knowledge_summary_resolver=lambda index_name: ElasticSearchService().get_summary(
            index_name=index_name
        ),
    )


def _mount_conversation_context_manager(agent_request: Any, agent_run_info: Any) -> None:
    from agents.agent_run_manager import agent_run_manager

    agent_config = getattr(agent_run_info, "agent_config", None)
    cm_config = getattr(agent_config, "context_manager_config", None)
    if not (cm_config and getattr(cm_config, "enabled", False)):
        return
    agent_run_info.context_manager = agent_run_manager.get_or_create_context_manager(
        conversation_id=str(agent_request.conversation_id),
        config=cm_config,
        max_steps=agent_config.max_steps,
    )


def _register_prepared_run(
    agent_request: Any,
    agent_run_info: Any,
    *,
    user_id: str,
    run_request_context: AgentRunRequestContext | None,
) -> None:
    from agents.agent_run_manager import agent_run_manager

    if run_request_context is not None:
        agent_run_manager.register_agent_run(
            agent_request.conversation_id,
            agent_run_info,
            user_id,
            request_id=run_request_context.request_id,
            runtime_provider=run_request_context.runtime_provider,
        )
        return
    agent_run_manager.register_agent_run(
        agent_request.conversation_id,
        agent_run_info,
        user_id,
    )


def _request_context_from_agent_request(
    agent_request: Any,
    *,
    user_id: str,
    tenant_id: str,
    language: str,
) -> AgentRunRequestContext:
    return AgentRunRequestContext(
        request_id="legacy-runtime-preparation",
        runtime_provider=AGENT_RUNTIME_PROVIDER_SMOLAGENTS,
        agent_id=int(agent_request.agent_id or 0),
        conversation_id=agent_request.conversation_id,
        query=agent_request.query or "",
        history=agent_request.history,
        minio_files=agent_request.minio_files,
        user_id=user_id,
        tenant_id=tenant_id,
        language=language,
        is_debug=bool(agent_request.is_debug),
        version_no=agent_request.version_no,
        override_model_id=agent_request.model_id,
        requested_output_tokens=agent_request.requested_output_tokens,
        tool_params=agent_request.tool_params,
    )
